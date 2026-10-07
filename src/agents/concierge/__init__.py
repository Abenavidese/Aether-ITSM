"""
Concierge chat agent (Fase 5; investigation supervisor since Fase 16), split by
responsibility:

- node.py         the LangGraph graph: plan -> investigate -> [replan] -> respond
- plan.py         what a turn looks at: regex floor + validated supervisor proposals
- supervisor.py   the model that picks read-only checks from a closed menu
- workers.py      the read-only readers, run concurrently with injected sources
- turn.py         TurnContext + Investigation records: everything one turn gathered
- repo_view.py    pure repo-tree interpretation + grounding check (no I/O)
- repo_access.py  GitHub reads (search, tree, file contents)
- platform.py     read-only hosting-platform triggers and guards
- reply.py        what the employee finally reads
"""
from .node import CONCIERGE_RISK_CEILING, concierge_node, get_concierge_workflow

__all__ = ["CONCIERGE_RISK_CEILING", "concierge_node", "get_concierge_workflow"]
