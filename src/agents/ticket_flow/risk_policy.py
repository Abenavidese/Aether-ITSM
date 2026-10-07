"""
Deterministic risk-floor enforcement.

This is the actual implementation of the "Risk Matrix Enforcement" principle
already promised in docs/security_guardrails.md:

    "The mapping of 'Incident Type' to 'Risk Level' is hardcoded in Python,
    not decided by the LLM. If the LLM classifies an issue as 'Firewall
    Modification', Python code forces this to Risk Level 4."

Before Fase 2, that promise was aspirational — the classifier's risk_level
went straight to routing with no override. It was harmless while
execution_agent_node only narrated text. Once it started dispatching real
MCP tool calls, a misclassification stopped being cosmetic: a live E2E run
had the 1B classifier rate an "AWS Admin / IAM" request low enough to skip
draft_plan entirely, and modify_iam_access executed with zero human
approval — precisely the scenario this module exists to prevent.

The LLM's own risk_level can only be raised by these rules, never lowered.
"""
import re
from typing import NamedTuple, Optional


class RiskFloorRule(NamedTuple):
    pattern: re.Pattern
    floor: int
    reason: str


# Keep in sync with docs/PLAN_IMPLEMENTACION.txt / scripts/fixtures/guia_politicas_empresa.txt.
# Highest matching floor wins; order in this list doesn't matter.
# Spanish variants matter as much as English ones: users write in both, and
# the first version of these rules (English only) let "dame permisos de
# administrador en AWS" through untouched (Fase 11 audit, hallazgo A).
# The tool policy (tool_policy.py) is the second, independent line: even
# when no rule matches, a risk-3 tool can't run without human approval.
RISK_FLOOR_RULES: list[RiskFloorRule] = [
    RiskFloorRule(
        re.compile(
            r"\b(iam|aws\s*admin|root\s*access|admin(istrator)?\s*(access|rights|permissions?|privileges?)"
            r"|sudo(ers)?|(acceso|permisos?|privilegios?|derechos?|rol)\s+(de\s+)?(admin(istrador)?|root|superusuario)"
            r"|(hazme|hacerme|volverme|ser)\s+admin(istrador)?)\b",
            re.IGNORECASE,
        ),
        3,
        "IAM/administrative access changes always require human approval (company policy).",
    ),
    RiskFloorRule(
        re.compile(
            r"\b(production\s*database|prod(uction)?\s*db|base\s*de\s*datos\s*(de\s*)?(producci[oó]n|prod))\b",
            re.IGNORECASE,
        ),
        4,
        "Production database incidents are always critical and must escalate to SRE.",
    ),
    RiskFloorRule(
        re.compile(r"\b(firewall|cortafuegos|security\s*group|grupo\s*de\s*seguridad)\b", re.IGNORECASE),
        4,
        "Firewall modifications are always treated as critical.",
    ),
]


def enforce_risk_floor(text: str, llm_risk_level: int) -> tuple[int, Optional[str]]:
    """
    Returns (final_risk_level, reason) — reason is None when the LLM's own
    classification already met or exceeded every matching floor.
    """
    floor = 0
    reason: Optional[str] = None
    for rule in RISK_FLOOR_RULES:
        if rule.floor > floor and rule.pattern.search(text):
            floor = rule.floor
            reason = rule.reason

    if floor > llm_risk_level:
        return floor, reason
    return llm_risk_level, None
