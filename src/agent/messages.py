"""
Plain text of a chat message, whatever shape its content has.

A LangChain message's content is either a string or a list of parts
(text / image_url dicts). Every consumer here — risk floor regexes, RAG
queries, keyword triggers — needs a string. Attached images are now turned
into text before they reach the graph (src/agent/vision.py), but threads
checkpointed before that still hold list content, so readers go through
this instead of assuming `.content` is a str (mypy flagged every such site).
"""
from typing import Sequence

from langchain_core.messages import BaseMessage


def message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict) and part.get("type") == "text":
            parts.append(str(part.get("text", "")))
    return "\n".join(parts)


def latest_text(messages: Sequence[BaseMessage]) -> str:
    return message_text(messages[-1]) if messages else ""
