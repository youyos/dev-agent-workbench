import pytest

from app.catalog import ContextResolver, build_default_registry
from app.models import AgentRunRequest, MentionKind, MentionRef
from app.pipeline import AgentPipeline
from app.providers.demo import DemoModelProvider


@pytest.mark.asyncio
async def test_pipeline_emits_structured_stages_in_order():
    registry, catalog = build_default_registry()
    pipeline = AgentPipeline(
        registry=registry,
        resolver=ContextResolver(catalog),
        provider=DemoModelProvider(),
    )
    request = AgentRunRequest(
        message="帮我定位支付为什么失败，并给出验证方案",
        mentions=[
            MentionRef(kind=MentionKind.SKILL, id="debug-code", label="支付故障诊断"),
            MentionRef(kind=MentionKind.FILE, id="checkout.py", label="checkout.py"),
            MentionRef(kind=MentionKind.RESOURCE, id="order-1024", label="订单 #1024"),
        ],
    )

    events = [event async for event in pipeline.run(request)]
    event_types = [event.type for event in events]

    assert event_types[0] == "run.started"
    assert event_types.index("context.resolved") < event_types.index("intent.detected")
    assert event_types.index("intent.detected") < event_types.index("route.selected")
    assert event_types.index("route.selected") < event_types.index("plan.created")
    assert event_types[-1] == "run.completed"
    route = next(event for event in events if event.type == "route.selected")
    assert any(item["capability_id"] == "debug-code" for item in route.data["selections"])


@pytest.mark.asyncio
async def test_explicit_skill_is_forced():
    registry, catalog = build_default_registry()
    pipeline = AgentPipeline(
        registry=registry,
        resolver=ContextResolver(catalog),
        provider=DemoModelProvider(),
    )
    request = AgentRunRequest(
        message="随便看看",
        mentions=[MentionRef(kind=MentionKind.SKILL, id="code-review", label="代码审查")],
    )

    events = [event async for event in pipeline.run(request)]
    route = next(event for event in events if event.type == "route.selected")
    selected = {item["capability_id"]: item for item in route.data["selections"]}

    assert selected["code-review"]["forced"] is True

