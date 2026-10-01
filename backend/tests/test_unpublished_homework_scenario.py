import json

import pytest

from app.catalog import CapabilityRegistry, ContextResolver, MentionCatalog
from app.models import AgentRunRequest, Capability, CapabilityKind, CapabilityResult, TaskIntent
from app.pipeline import AgentPipeline
from app.providers.demo import DemoModelProvider
from app.recommendation_renderer import RecommendationRenderer
from app.scenario_policy import (
    UNPUBLISHED_HOMEWORK_CONTRACT,
    ScenarioPolicyRegistry,
)


def _capabilities():
    return [
        Capability(
            id="educoder-skill",
            name="Educoder 查询助手",
            description="提供只读 Educoder 数据",
            kind=CapabilityKind.SKILL,
        ),
        Capability(
            id="mcp-educoder-homework-list",
            name="查询作业列表",
            description="查询课堂作业列表，可按发布状态筛选未发布作业",
            kind=CapabilityKind.MCP,
            metadata={"mcp_tool_name": "educoder_homework_list"},
        ),
        Capability(
            id="66",
            name="备课助手",
            description="生成作业推荐卡片",
            kind=CapabilityKind.SKILL,
        ),
    ]


def test_policy_assigns_data_provider_and_output_owner():
    resolution = ScenarioPolicyRegistry().resolve(
        "查询未发布的作业列表",
        TaskIntent(goal="查询未发布的作业列表", intent="list_unpublished_homeworks"),
        _capabilities(),
    )

    assert resolution.matched is True
    assert resolution.missing == ()
    assert resolution.route is not None
    assert resolution.route.primary_skill_id == "66"
    assert resolution.route.supporting_skill_ids == ["educoder-skill"]
    assert resolution.route.output_contract == UNPUBLISHED_HOMEWORK_CONTRACT
    assert [item.capability_id for item in resolution.route.selections] == [
        "educoder-skill",
        "mcp-educoder-homework-list",
        "66",
    ]


def test_renderer_builds_ai_hub_compatible_homework_card():
    result = CapabilityResult(
        capability_id="mcp-educoder-homework-list",
        success=True,
        summary="查询完成",
        data={
            "content": json.dumps(
                {
                    "data": {
                        "meta": {"page": 1, "total_count": 1},
                        "homeworks": [
                            {
                                "homework_id": 101,
                                "homework_name": "第一章练习",
                                "homework_type": "普通作业",
                                "publish_status": "未发布",
                                "course_name": "Python 入门",
                                "manage_all_group": False,
                                "custom_field": {"preserved": True},
                            }
                        ]
                    }
                },
                ensure_ascii=False,
            )
        },
    )

    plan = RecommendationRenderer().render(UNPUBLISHED_HOMEWORK_CONTRACT, [result])

    assert plan.card_type == "homework"
    assert plan.title == "未发布作业"
    assert plan.sections[0].key == "unpublished_homeworks"
    assert plan.sections[0].title == "待发布"
    assert plan.sections[0].meta == {"page": 1, "total_count": 1}
    assert plan.sections[0].items[0].id == "101"
    assert plan.sections[0].items[0].title == "第一章练习"
    assert plan.sections[0].items[0].model_extra["manage_all_group"] is False
    assert plan.sections[0].items[0].model_extra["custom_field"] == {"preserved": True}


@pytest.mark.asyncio
async def test_pipeline_emits_validated_recommendation_event():
    registry = CapabilityRegistry()

    async def skill_handler(payload):
        return {"role_applied": payload["instruction"]}

    async def query_handler(payload):
        return {
            "homeworks": [
                {
                    "id": "hw-1",
                    "name": "未发布作业 A",
                    "type": "普通作业",
                    "status": "未发布",
                },
                {
                    "id": "hw-2",
                    "name": "未发布作业 B",
                    "type": "实训作业",
                    "status": "draft",
                },
            ]
        }

    for capability in _capabilities():
        registry.register(
            capability,
            query_handler if capability.kind is CapabilityKind.MCP else skill_handler,
        )
    pipeline = AgentPipeline(
        registry=registry,
        resolver=ContextResolver(MentionCatalog()),
        provider=DemoModelProvider(),
        scenario_registry=ScenarioPolicyRegistry(),
    )

    events = [
        event
        async for event in pipeline.run(
            AgentRunRequest(message="查询未发布的作业列表")
        )
    ]

    event_types = [event.type for event in events]
    assert "scenario.matched" in event_types
    assert "output.validated" in event_types
    assert "recommendation" in event_types
    recommendation = next(event for event in events if event.type == "recommendation")
    assert recommendation.data["content"]["card_type"] == "homework"
    assert len(recommendation.data["content"]["sections"][0]["items"]) == 2
    assert "message.delta" not in event_types
