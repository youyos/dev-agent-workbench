import pytest

from app.catalog import ContextResolver, build_default_registry
from app.models import AgentRunRequest, ChatMessage, MentionKind, MentionRef, TaskIntent
from app.pipeline import AgentPipeline
from app.providers.demo import DemoModelProvider


class NeedsInputProvider(DemoModelProvider):
    async def analyze_intent(self, message, context):
        return TaskIntent(
            goal=message,
            intent="unknown",
            needs_clarification=True,
            clarification_question="请问您输入 123 是想执行什么操作？",
        )


@pytest.mark.asyncio
async def test_simple_fact_style_is_direct():
    intent = await DemoModelProvider().analyze_intent("你好", [])

    assert intent.response_style == "direct"


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


@pytest.mark.asyncio
async def test_needs_input_is_also_emitted_as_assistant_message():
    registry, catalog = build_default_registry()
    pipeline = AgentPipeline(
        registry=registry,
        resolver=ContextResolver(catalog),
        provider=NeedsInputProvider(),
    )

    events = [event async for event in pipeline.run(AgentRunRequest(message="123"))]

    assert [event.type for event in events][-2:] == ["run.needs_input", "message.completed"]
    assert events[-1].data["content"] == "请问您输入 123 是想执行什么操作？"


@pytest.mark.asyncio
async def test_pipeline_carries_bounded_conversation_history():
    registry, catalog = build_default_registry()
    pipeline = AgentPipeline(
        registry=registry,
        resolver=ContextResolver(catalog),
        provider=DemoModelProvider(),
    )
    request = AgentRunRequest(
        message="继续",
        history=[
            ChatMessage(role="user", content="请分析支付失败"),
            ChatMessage(role="assistant", content="请提供相关文件"),
        ],
    )

    events = [event async for event in pipeline.run(request)]

    assert events[0].data["history_count"] == 2
    assert events[-1].type == "run.completed"
    assert events[-1].data["history_count"] == 2
