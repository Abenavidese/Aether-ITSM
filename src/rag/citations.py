"""
Citations in answers (Fase 14.5, roadmap 3.3).

The model is shown numbered passages ([1]..[n], RetrievalResult.to_prompt)
and asked to cite them. What it writes is then checked by code, not
trusted: a citation to a passage that doesn't exist is removed (a small
model does invent "[4]" when it was given two passages), and only passages
actually cited are returned as the answer's sources — the UI shows those,
never "everything we retrieved".
"""
import re
from dataclasses import dataclass, field

from .retrieval import Passage
from .text import extract_entities, query_terms

_CITATION = re.compile(r"\s?\[(\d{1,2})\]")
# Evidence-based attribution: the answer reuses at least this many distinctive
# words of a passage that the question didn't contain (or one exact identifier).
_MIN_SHARED_TERMS = 3
_MIN_TERM_CHARS = 4


def _distinctive(text: str) -> set[str]:
    return {t for t in query_terms(text, limit=10_000) if len(t) >= _MIN_TERM_CHARS or any(c.isdigit() for c in t)}


def attribute(answer: str, question: str, passages: list[Passage]) -> list[int]:
    """
    Passages the answer demonstrably used, whether or not the model cited
    them. Found live: the 8B model grounded 4 of 4 answers in the passages
    but cited 1. Deterministic and conservative — words the user already
    wrote don't count, so echoing the question never "proves" a source.
    """
    asked = _distinctive(question) | set(extract_entities(question))
    said = _distinctive(answer)
    said_entities = set(extract_entities(answer)) - asked
    used = []
    for p in passages:
        shared = (_distinctive(p.text) & said) - asked
        if len(shared) >= _MIN_SHARED_TERMS or (said_entities & set(extract_entities(p.text))):
            used.append(p.n)
    return used


@dataclass
class CitationReport:
    text: str
    sources: list[dict] = field(default_factory=list)
    cited: list[int] = field(default_factory=list)        # by the model, validated
    attributed: list[int] = field(default_factory=list)   # by evidence in the text (attribute())
    removed: list[int] = field(default_factory=list)

    @property
    def uncited_with_context(self) -> bool:
        """Passages were given but the answer cites none (tracked, not blocked:
        "I couldn't find that" legitimately cites nothing)."""
        return not self.cited

    def stats(self, passages: int) -> dict:
        return {"passages": passages, "cited": len(self.cited), "attributed": len(self.attributed),
                "removed": len(self.removed), "uncited_with_context": passages > 0 and self.uncited_with_context}


def validate_citations(reply: str, passages: list[Passage], declared: list[int] | tuple[int, ...] = (),
                       question: str | None = None) -> CitationReport:
    """
    `declared`: passage numbers the model listed in its structured output
    (ConciergeResult.cited_passages) — merged with the inline [n] markers,
    and held to the same rule: only numbers that exist survive.
    `question`: when given, passages the answer demonstrably used but didn't
    cite are added as sources too (attribute()).
    """
    valid = {p.n: p for p in passages}
    cited: list[int] = []
    removed: list[int] = []
    for n in declared:
        if n in valid and n not in cited:
            cited.append(n)
        elif n not in valid:
            removed.append(n)

    def check(match: re.Match) -> str:
        n = int(match.group(1))
        if n in valid:
            if n not in cited:
                cited.append(n)
            return match.group(0)
        removed.append(n)
        return ""

    text = _CITATION.sub(check, reply)
    text = re.sub(r"[ \t]+([.,;:])", r"\1", text)
    attributed = [n for n in attribute(text, question, passages) if n not in cited] if question is not None else []
    used = sorted(set(cited) | set(attributed))
    return CitationReport(text=text, sources=[valid[n].source() for n in used], cited=sorted(cited),
                          attributed=sorted(attributed), removed=removed)
