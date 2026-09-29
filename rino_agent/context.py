"""Bounded adapters for Rino-owned memory, KG, RAG, and vision context."""
from __future__ import annotations

from typing import Any

_ALLOWED = ("memory", "knowledge_graph", "game_rag", "vision", "life")


def build_context(source: dict[str, Any] | None) -> str:
    if not source:
        return ""
    sections: list[str] = []
    for name in _ALLOWED:
        value = source.get(name)
        if not value:
            continue
        text = str(value).replace("\x00", "").strip()[:2_000]
        if text:
            sections.append(f"[{name}]\n{text}")
    return "\n\n".join(sections)
