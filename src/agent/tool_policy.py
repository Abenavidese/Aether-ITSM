"""
Deterministic authorization for every MCP tool call (Fase 11.1-11.4).

The LLM PROPOSES a tool call (ExecutionPlanResult / ConciergeResult); this
module DECIDES whether it runs, and with which arguments. Nothing here
consults a model, so no prompt injection, misclassification or
hallucination can widen what the agent is allowed to do:

- Default deny: a tool without a policy entry never runs, even if the MCP
  server exposes it (test_every_mcp_tool_has_a_policy keeps them in sync).
- Risk ceiling: a tool riskier than the ticket's assessed risk is refused.
  Before this, a risk-1 ticket could reach modify_iam_access whenever the
  risk-floor regex didn't match the wording (e.g. Spanish).
- Human approval: risk-3 tools run only after an admin approved that exact
  call (see nodes.draft_plan_node / execution_agent_node).
- Identity binding: "who" a tool acts on comes from the ticket's
  requester, never from the model — an employee can't get the agent to
  reset someone else's VPN by asking nicely.
- Argument validation: exact parameter set, bounded strings, per-tool
  rules (software whitelist, ARN shape, access-level enum, healthcheck URL
  must be one the tenant configured).
"""
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from src.config import get_settings

APPROVAL_RISK = 3
_MAX_ARG_CHARS = 256


class ToolPolicyViolation(Exception):
    """A proposed tool call was refused. `reason` is safe to show/log."""

    def __init__(self, tool_name: str, reason: str):
        super().__init__(f"Tool call '{tool_name}' refused: {reason}")
        self.tool_name = tool_name
        self.reason = reason


@dataclass(frozen=True)
class ToolCallContext:
    """Everything authorization depends on — all of it from code/state, none from the LLM."""
    requester: Optional[str]            # email of the person the ticket/chat is for
    assessed_risk: int                  # after risk floors (risk_policy.py)
    human_approved: bool = False
    allowed_service_urls: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class AuthorizedToolCall:
    name: str
    args: dict

    def describe(self) -> str:
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(self.args.items()))
        return f"{self.name}({rendered})"

    def to_dict(self) -> dict:
        return {"tool_name": self.name, "tool_args": dict(self.args)}


ArgValidator = Callable[[dict, ToolCallContext], None]


@dataclass(frozen=True)
class ToolPolicy:
    risk: int
    params: frozenset[str]
    identity_param: Optional[str] = None
    validate: Optional[ArgValidator] = None

    @property
    def requires_approval(self) -> bool:
        return self.risk >= APPROVAL_RISK


# ── per-tool validators ───────────────────────────────────────────────────────

_ARN_PATTERN = re.compile(r"^arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d{0,12}:[\w+=,.@/:*-]{1,200}$")
_ACCESS_LEVELS = {"read", "write", "admin"}


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/").lower()


def _validate_software(args: dict, ctx: ToolCallContext) -> None:
    if args["software_id"] not in get_settings().get_mdm_whitelist_list:
        raise ValueError("software_id is not in the MDM whitelist")


def _validate_iam(args: dict, ctx: ToolCallContext) -> None:
    if not _ARN_PATTERN.fullmatch(args["resource_arn"]):
        raise ValueError("resource_arn is not a valid AWS ARN")
    if args["access_level"].lower() not in _ACCESS_LEVELS:
        raise ValueError(f"access_level must be one of {sorted(_ACCESS_LEVELS)}")
    args["access_level"] = args["access_level"].lower()


def _validate_service_url(args: dict, ctx: ToolCallContext) -> None:
    # SSRF, layer 1: only URLs the tenant admin configured. Layer 2 (public
    # addresses only, no redirects) runs inside the tool itself.
    if normalize_url(args["service_url"]) not in ctx.allowed_service_urls:
        raise ValueError("service_url is not one of the tenant's monitored services")


TOOL_POLICIES: dict[str, ToolPolicy] = {
    "query_knowledge_base": ToolPolicy(risk=0, params=frozenset({"query_string"})),
    "check_service_status": ToolPolicy(
        risk=0, params=frozenset({"service_url"}), validate=_validate_service_url,
    ),
    "reset_vpn_session": ToolPolicy(risk=2, params=frozenset({"user_id"}), identity_param="user_id"),
    "provision_standard_software": ToolPolicy(
        risk=2, params=frozenset({"user_id", "software_id"}), identity_param="user_id",
        validate=_validate_software,
    ),
    "modify_iam_access": ToolPolicy(
        risk=3, params=frozenset({"user_id", "resource_arn", "access_level"}), identity_param="user_id",
        validate=_validate_iam,
    ),
}


# ── public API ────────────────────────────────────────────────────────────────

def allowed_tools(ctx: ToolCallContext) -> list[str]:
    """Tools the agent may even be SHOWN for this context (least privilege in the prompt too)."""
    return sorted(
        name for name, p in TOOL_POLICIES.items()
        if p.risk <= ctx.assessed_risk and (not p.requires_approval or ctx.human_approved)
    )


def risk_of_tools(names: Iterable[str]) -> int:
    """Highest known risk among tool names (unknown names ignored) — a risk floor source."""
    return max((TOOL_POLICIES[n].risk for n in names if n in TOOL_POLICIES), default=0)


_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def identity_params() -> dict[str, set[str]]:
    """Params the LLM is never shown (see mcp_client.prompt_catalog): not its decision."""
    return {name: {p.identity_param} for name, p in TOOL_POLICIES.items() if p.identity_param}


def _bind_identity(value: Any, requester: Optional[str], tool_name: str) -> str:
    """
    The acted-on account is ALWAYS the requester. The model isn't shown this
    parameter, but a small model fills it anyway with whatever it has ("Tech
    Lead", "user123" — seen live in the E2E), so a non-address value is just
    ignored. A DIFFERENT email address, though, is an unambiguous attempt to
    target someone else ("reset ceo@acme.com's VPN") and is refused, so the
    ticket goes to a human instead of silently acting on the requester.
    """
    if not requester:
        raise ToolPolicyViolation(tool_name, "no requester identity to act on")
    candidate = str(value or "").strip().lower()
    if _EMAIL.fullmatch(candidate) and candidate != requester.lower():
        raise ToolPolicyViolation(tool_name, "tools can only act on the requester's own account")
    return requester


def authorize(name: Optional[str], args: Any, ctx: ToolCallContext) -> AuthorizedToolCall:
    """Returns the call to execute (with cleaned/bound args) or raises ToolPolicyViolation."""
    tool = name or ""
    policy = TOOL_POLICIES.get(tool)
    if policy is None:
        raise ToolPolicyViolation(tool, "unknown tool (default deny)")
    if policy.risk > ctx.assessed_risk:
        raise ToolPolicyViolation(tool, f"tool risk {policy.risk} exceeds the ticket's risk {ctx.assessed_risk}")
    if policy.requires_approval and not ctx.human_approved:
        raise ToolPolicyViolation(tool, "tool requires human approval")
    if not isinstance(args, dict):
        raise ToolPolicyViolation(tool, "arguments must be an object")

    unexpected = set(args) - policy.params
    if unexpected:
        raise ToolPolicyViolation(tool, f"unexpected arguments {sorted(unexpected)}")

    clean: dict[str, Any] = {}
    for param in policy.params:
        if param == policy.identity_param:
            clean[param] = _bind_identity(args.get(param), ctx.requester, tool)
            continue
        value = args.get(param)
        if not isinstance(value, str) or not value.strip():
            raise ToolPolicyViolation(tool, f"argument '{param}' must be a non-empty string")
        if len(value) > _MAX_ARG_CHARS:
            raise ToolPolicyViolation(tool, f"argument '{param}' is too long")
        clean[param] = value.strip()

    if policy.validate:
        try:
            policy.validate(clean, ctx)
        except ValueError as e:
            raise ToolPolicyViolation(tool, str(e)) from e
    return AuthorizedToolCall(tool, clean)
