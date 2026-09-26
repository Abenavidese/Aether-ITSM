"""
Concierge chat agent (Fase 5), split by responsibility (roadmap 2.6):

- node.py         the LangGraph node: gather context -> model -> tool -> fixed rules
- turn.py         TurnContext: everything one turn gathered
- prompt.py       the system prompt
- repo_view.py    pure repo-tree interpretation + grounding check (no I/O)
- repo_access.py  GitHub reads (search, tree, file contents)
- platform.py     read-only hosting-platform triggers and guards
- reply.py        what the employee finally reads
"""
from .node import CONCIERGE_RISK_CEILING, concierge_node, get_concierge_workflow

__all__ = ["CONCIERGE_RISK_CEILING", "concierge_node", "get_concierge_workflow"]
