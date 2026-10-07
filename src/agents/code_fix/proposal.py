"""
One reviewable edit for a failing line (Fase 16).

The model sees a numbered window around the failing line and returns that
window rewritten with the fix (no line numbers). Code computes the diff and
accepts or rejects it — the model's output never reaches a repository
unvalidated:

- exactly one changed block, close to the failing line, and small;
- the replacement must actually change something;
- brackets must stay balanced the way they were (a cheap syntax sanity
  check that works for JS/TS/Python alike);
- the edit may not introduce capabilities the original lines didn't use:
  network calls, URLs, process/env access, eval, child processes. The error
  lines come from logs, which attackers can write into; a "fix" that adds a
  fetch() to an attacker's URL is exactly what this blocks.

Found live (Fase 16.9): asked for start/end line numbers, the local 8B model
returned 0-0. Rewriting a short snippet is what small models do reliably;
the line arithmetic is code's job.
"""
import difflib
import logging
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.llm.structured_output import invoke_structured
from src.prompts.code_fix import code_fix_prompt
from src.security.redaction import redact

logger = logging.getLogger(__name__)

WINDOW_BEFORE, WINDOW_AFTER = 12, 12
# The changed block must touch the failing line or sit right next to it.
MAX_DISTANCE_FROM_FAILING_LINE = 6


class CodeFixProposal(BaseModel):
    can_fix: bool = Field(description="False if the cause is not in the code shown or you are not sure.")
    explanation: str = Field(description="1-3 plain sentences: the cause and what the change does.")
    fixed_code: str = Field(description="The code shown, rewritten with the fix: same lines, no line numbers.")


@dataclass(frozen=True)
class FixEdit:
    path: str
    start_line: int
    end_line: int
    old_code: str
    new_code: str
    new_content: str
    explanation: str


class RejectedFix(Exception):
    """The model declined, or its edit failed validation (the reason says which)."""


_CAPABILITIES = re.compile(
    r"https?://|\bfetch\s*\(|\baxios\b|\bXMLHttpRequest\b|\brequire\(\s*['\"](?:https?|net|child_process|fs|dgram)['\"]"
    r"|\bimport\s+.*\bfrom\s+['\"](?:https?|net|child_process|fs)|\bprocess\.env\b|\bchild_process\b|\beval\s*\("
    r"|\bnew\s+Function\b|\bexec(?:Sync)?\s*\(|\bspawn\s*\(|\bsubprocess\b|\bos\.system\b|\bos\.environ\b",
)
_BRACKETS = "(){}[]"
_NUMBER_PREFIX = re.compile(r"^\s*\d+\s?\|\s?")
_FENCE = re.compile(r"^\s*```")


_SNIPPET_LINES = 3          # an answer this short is a replacement for the failing line(s)
_MAX_NET_LINES = 3          # lines a fix may add or remove overall
_MIN_SIMILARITY = 0.45      # a replacement must look like the line it replaces


def _anchor_snippet(original: list[str], fixed: list[str], failing: int) -> tuple[int, int, int, int]:
    """(i1, i2, j1, j2): the failing line(s) of `original` the short answer replaces."""
    span = min(len(fixed), len(original) - failing)
    old = original[failing:failing + span]
    similarity = difflib.SequenceMatcher(a="\n".join(x.strip() for x in old),
                                         b="\n".join(x.strip() for x in fixed)).ratio()
    if similarity < _MIN_SIMILARITY:
        raise RejectedFix(f"the short answer does not match the failing line (similarity {similarity:.2f})")
    indent = re.match(r"\s*", original[failing]).group(0)  # type: ignore[union-attr]
    # Small models drop the indentation of a lone line; keep the file's.
    if fixed and not fixed[0].startswith((" ", "\t")):
        fixed[:] = [indent + x if x.strip() else x for x in fixed]
    return failing, failing + span, 0, len(fixed)


def window_bounds(lines: list[str], line: int) -> tuple[int, int]:
    return max(1, line - WINDOW_BEFORE), min(len(lines), line + WINDOW_AFTER)


def numbered(lines: list[str], start: int, end: int) -> str:
    return "\n".join(f"{n:>4} | {lines[n - 1]}" for n in range(start, end + 1))


def _bracket_balance(text: str) -> tuple[int, int, int]:
    return tuple(text.count(_BRACKETS[i]) - text.count(_BRACKETS[i + 1]) for i in (0, 2, 4))  # type: ignore[return-value]


def _clean(fixed_code: str) -> list[str]:
    """The model's snippet as lines: markdown fences dropped, an echoed "  9 | " prefix removed."""
    lines = [line for line in fixed_code.replace("\r\n", "\n").split("\n") if not _FENCE.match(line)]
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and all(_NUMBER_PREFIX.match(line) or not line.strip() for line in lines):
        lines = [_NUMBER_PREFIX.sub("", line, count=1) for line in lines]
    return [line.rstrip() for line in lines]


def validate_edit(path: str, content: str, line: int, proposal: CodeFixProposal, max_changed_lines: int) -> FixEdit:
    if not proposal.can_fix:
        raise RejectedFix(f"model declined: {proposal.explanation[:200]}")
    lines = content.splitlines()
    low, high = window_bounds(lines, line)
    original = [x.rstrip() for x in lines[low - 1:high]]
    while original and not original[-1].strip():
        original.pop()
    fixed = _clean(proposal.fixed_code)
    if not fixed:
        raise RejectedFix("the model returned no code")

    if len(fixed) <= _SNIPPET_LINES < len(original):
        # Found live: asked for the whole snippet, the 8B model returned only
        # the corrected line. Diffing that against the window reads as "delete
        # everything else" — so a short answer is a replacement of the
        # failing line, accepted only if it resembles that line.
        i1, i2, j1, j2 = _anchor_snippet(original, fixed, line - low)
    else:
        changes = [op for op in difflib.SequenceMatcher(a=original, b=fixed, autojunk=False).get_opcodes()
                   if op[0] != "equal"]
        if not changes:
            raise RejectedFix("the replacement changes nothing")
        # One block: from the first changed line to the last one.
        i1, i2 = changes[0][1], changes[-1][2]
        j1, j2 = changes[0][3], changes[-1][4]
    old_block, new_block = original[i1:i2], fixed[j1:j2]
    if old_block == new_block:
        raise RejectedFix("the replacement changes nothing")
    if max(len(old_block), len(new_block)) > max_changed_lines:
        raise RejectedFix(f"edit too large ({max(len(old_block), len(new_block))} lines > {max_changed_lines})")
    if abs(len(new_block) - len(old_block)) > _MAX_NET_LINES:
        raise RejectedFix(f"edit adds or removes {abs(len(new_block) - len(old_block))} lines — a fix is a small change")
    start = low + i1                       # first replaced file line (1-based)
    end = start + len(old_block) - 1       # last replaced line (start - 1 for a pure insertion)
    if not (start - MAX_DISTANCE_FROM_FAILING_LINE <= line <= max(end, start) + MAX_DISTANCE_FROM_FAILING_LINE):
        raise RejectedFix(f"edit at lines {start}-{end} is far from the failing line {line}")
    old_code, new_code = "\n".join(old_block), "\n".join(new_block)
    if _bracket_balance(new_code) != _bracket_balance(old_code):
        raise RejectedFix("brackets unbalanced compared to the original lines")
    added = {m.group(0) for m in _CAPABILITIES.finditer(new_code)} - {m.group(0) for m in _CAPABILITIES.finditer(old_code)}
    if added:
        raise RejectedFix(f"edit adds capabilities the original lines didn't have: {sorted(added)}")

    trailing_newline = "\n" if content.endswith("\n") else ""
    new_content = "\n".join(lines[:start - 1] + new_block + lines[start - 1 + len(old_block):]) + trailing_newline
    return FixEdit(path, start, end, old_code, new_code, new_content, redact(proposal.explanation.strip())[:600])


async def propose_fix(llm, path: str, content: str, line: int, errors: list[str], max_changed_lines: int) -> FixEdit:
    lines = content.splitlines()
    if not 1 <= line <= len(lines):
        raise RejectedFix(f"line {line} is outside {path} ({len(lines)} lines)")
    low, high = window_bounds(lines, line)
    messages = [SystemMessage(content=code_fix_prompt(path, line, numbered(lines, low, high), errors,
                                                      max_changed_lines)),
                HumanMessage(content="Propose the fix now.")]
    proposal: CodeFixProposal = await invoke_structured(llm, CodeFixProposal, messages)
    return validate_edit(path, content, line, proposal, max_changed_lines)
