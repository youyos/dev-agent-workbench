from __future__ import annotations

from .catalog import CapabilityRegistry
from .models import Capability, CapabilityKind


def register_unpublished_homework_fixture(registry: CapabilityRegistry) -> None:
    """Register replaceable demo roles and data for the scenario playground."""

    async def role_handler(payload: dict) -> dict:
        return {
            "fixture": True,
            "role": payload["instruction"],
            "note": "这是场景 Fixture；导入同 ID 的真实 Skill 后会被替换。",
        }

    async def query_handler(_: dict) -> dict:
        return {
            "_demo": True,
            "homeworks": [
                {
                    "homework_id": "hw-demo-101",
                    "homework_name": "Python 基础语法练习",
                    "homework_type": "普通作业",
                    "publish_status": "未发布",
                    "course_name": "Python 程序设计",
                    "end_time": "2026-10-08 23:59",
                },
                {
                    "homework_id": "hw-demo-102",
                    "homework_name": "列表与字典实训",
                    "homework_type": "实训作业",
                    "publish_status": "draft",
                    "course_name": "Python 程序设计",
                    "end_time": "2026-10-10 23:59",
                },
            ],
        }

    registry.upsert(
        Capability(
            id="36",
            name="Educoder 查询助手（Fixture）",
            description="场景演示的数据提供者；导入真实查询 Skill 后替换。",
            kind=CapabilityKind.SKILL,
            permissions=["read"],
            metadata={"fixture": True, "role": "data_provider", "can_own_output": False},
        ),
        role_handler,
    )
    registry.upsert(
        Capability(
            id="demo-unpublished-homework-list",
            name="查询未发布作业（Fixture）",
            description="返回场景演示使用的未发布作业列表。",
            kind=CapabilityKind.TOOL,
            permissions=["read"],
            metadata={"fixture": True},
        ),
        query_handler,
    )
    registry.upsert(
        Capability(
            id="66",
            name="备课助手（Fixture）",
            description="场景演示的卡片输出所有者；导入真实备课 Skill 后替换。",
            kind=CapabilityKind.SKILL,
            permissions=["read"],
            metadata={
                "fixture": True,
                "role": "business_workflow",
                "can_own_output": True,
                "output_contracts": ["preparation.unpublished_homework_cards.v1"],
            },
        ),
        role_handler,
    )
