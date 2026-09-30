import pytest

from app.catalog import ContextResolver, build_default_registry
from app.models import MentionKind, MentionRef


def test_mention_search_filters_kind_and_query():
    _, catalog = build_default_registry()

    results = catalog.search("checkout", MentionKind.FILE)

    assert [item.id for item in results] == ["checkout.py"]


def test_builtin_skills_are_discovered_from_directories():
    registry, _ = build_default_registry()

    skill = registry.get("debug-code")

    assert skill is not None
    assert skill.descriptor.kind.value == "skill"
    assert "失败" in skill.descriptor.triggers


def test_empty_mention_search_balances_mcp_with_other_categories():
    _, catalog = build_default_registry()
    for index in range(32):
        catalog.add(
            MentionRef(
                kind=MentionKind.MCP,
                id=f"mcp-demo-tool-{index}",
                label=f"MCP Tool {index}",
            )
        )

    results = catalog.search()

    assert sum(item.kind == MentionKind.MCP for item in results) == 6
    assert any(item.kind == MentionKind.SKILL for item in results)
    assert any(item.kind == MentionKind.FILE for item in results)


@pytest.mark.asyncio
async def test_context_resolver_creates_snapshot_with_provenance():
    _, catalog = build_default_registry()
    resolver = ContextResolver(catalog)

    items = await resolver.resolve(
        [MentionRef(kind=MentionKind.FILE, id="checkout.py", label="checkout.py")]
    )

    assert items[0].source == "demo-file-resolver"
    assert items[0].metadata["snapshot"] is True
    assert "charge_order" in items[0].content
