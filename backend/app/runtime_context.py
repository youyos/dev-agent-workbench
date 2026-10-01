from __future__ import annotations

import json

from .models import AgentRunContext, MentionKind, MentionRef, ResolvedContextItem


def model_context(state: AgentRunContext, *, include_history: bool, budget: int = 48_000):
    """Bound content centrally. Providers must not truncate the combined history again."""
    blocks = list(state.context)
    for result in state.results:
        if result.capability_id in state.loaded_skills:
            instructions = result.data.get("skill_instructions")
            if instructions:
                blocks.append(_item("skill-instructions", result.capability_id, str(instructions)))
        else:
            blocks.append(
                _item("current-tool-result", result.capability_id, result.model_dump_json())
            )
    if include_history and state.history:
        blocks.append(
            _item(
                "conversation-history",
                "recent-history",
                json.dumps([item.model_dump() for item in state.history], ensure_ascii=False),
            )
        )
    remaining = budget
    selected = []
    for block in blocks:
        if remaining <= 0:
            break
        limit = min(remaining, 24_000 if block.source == "conversation-history" else 12_000)
        content = block.content[:limit]
        selected.append(block.model_copy(update={"content": content}))
        remaining -= len(content)
    return selected


def _item(source: str, identifier: str, content: str) -> ResolvedContextItem:
    return ResolvedContextItem(
        mention=MentionRef(kind=MentionKind.RESOURCE, id=identifier, label=identifier),
        source=source,
        title=identifier,
        content=content,
    )
