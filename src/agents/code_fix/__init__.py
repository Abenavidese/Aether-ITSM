"""
Code-fix proposals (Fase 16): from a diagnosed incident (file:line from the
stack trace + redacted error lines) to ONE small edit a human reviews as a
draft pull request. The model proposes; code decides whether the edit is
acceptable (proposal.validate_edit). Nothing here writes anywhere.
"""
from .proposal import CodeFixProposal, FixEdit, RejectedFix, propose_fix

__all__ = ["CodeFixProposal", "FixEdit", "RejectedFix", "propose_fix"]
