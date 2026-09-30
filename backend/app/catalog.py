from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Capability, CapabilityKind, MentionKind, MentionRef, ResolvedContextItem

CapabilityHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class CapabilityRegistration:
    descriptor: Capability
    handler: CapabilityHandler


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items: dict[str, CapabilityRegistration] = {}

    def register(self, descriptor: Capability, handler: CapabilityHandler) -> None:
        if descriptor.id in self._items:
            raise ValueError(f"duplicate capability: {descriptor.id}")
        self._items[descriptor.id] = CapabilityRegistration(descriptor, handler)

    def upsert(self, descriptor: Capability, handler: CapabilityHandler) -> None:
        self._items[descriptor.id] = CapabilityRegistration(descriptor, handler)

    def remove_by_metadata(self, key: str, value: str) -> None:
        self._items = {
            item_id: registration
            for item_id, registration in self._items.items()
            if registration.descriptor.metadata.get(key) != value
        }

    def get(self, capability_id: str) -> CapabilityRegistration | None:
        return self._items.get(capability_id)

    def list(self) -> list[Capability]:
        return [item.descriptor for item in self._items.values()]


class MentionCatalog:
    def __init__(self) -> None:
        self._items: list[MentionRef] = []

    def add(self, item: MentionRef) -> None:
        self._items = [
            existing
            for existing in self._items
            if not (existing.kind == item.kind and existing.id == item.id)
        ]
        self._items.append(item)

    def remove_by_metadata(self, key: str, value: str) -> None:
        self._items = [item for item in self._items if item.metadata.get(key) != value]

    def search(self, query: str = "", kind: MentionKind | None = None) -> list[MentionRef]:
        normalized = query.casefold().strip()
        items = self._items
        if kind is not None:
            items = [item for item in items if item.kind == kind]
        if normalized:
            items = [
                item
                for item in items
                if normalized in item.label.casefold() or normalized in item.id.casefold()
            ]
            items.sort(
                key=lambda item: (
                    0 if item.label.casefold().startswith(normalized) else 1,
                    item.label.casefold(),
                )
            )
            return items[:30]
        if kind is not None:
            return sorted(items, key=lambda item: item.label.casefold())[:50]

        # An empty @ menu is a capability overview, not a raw global list.
        # Keep every category visible even when one MCP exposes many tools.
        quotas = {
            MentionKind.SKILL: 6,
            MentionKind.FILE: 6,
            MentionKind.RESOURCE: 6,
            MentionKind.TOOL: 6,
            MentionKind.MCP: 6,
        }
        balanced: list[MentionRef] = []
        for item_kind, quota in quotas.items():
            group = sorted(
                (item for item in items if item.kind == item_kind),
                key=lambda item: item.label.casefold(),
            )
            balanced.extend(group[:quota])
        return balanced


class ContextResolver:
    def __init__(self, catalog: MentionCatalog) -> None:
        self._catalog = catalog

    async def resolve(self, mentions: list[MentionRef]) -> list[ResolvedContextItem]:
        return [self._resolve_one(mention) for mention in mentions]

    def _resolve_one(self, mention: MentionRef) -> ResolvedContextItem:
        if mention.kind == MentionKind.FILE:
            content = DEMO_FILES.get(mention.id, "文件存在于业务系统中，示例未加载正文。")
            return ResolvedContextItem(
                mention=mention,
                source="demo-file-resolver",
                title=mention.label,
                content=content,
                metadata={"snapshot": True, "language": "python"},
            )
        if mention.kind == MentionKind.RESOURCE:
            resource = DEMO_RESOURCES.get(mention.id, {"summary": "业务对象摘要不可用"})
            return ResolvedContextItem(
                mention=mention,
                source="demo-resource-resolver",
                title=mention.label,
                content=str(resource),
                metadata={"snapshot": True},
            )
        if mention.kind == MentionKind.SKILL:
            return ResolvedContextItem(
                mention=mention,
                source="skill-registry",
                title=mention.label,
                content=f"用户显式指定 Skill：{mention.id}",
                metadata={"forced": True},
            )
        return ResolvedContextItem(
            mention=mention,
            source="capability-registry",
            title=mention.label,
            content=f"用户显式指定能力：{mention.id}",
            metadata={"forced": True},
        )


DEMO_FILES = {
    "checkout.py": '''async def charge_order(order, gateway):
    result = await gateway.charge(order.total)
    if result.status != "ok":
        return {"success": False, "reason": result.message}
    order.status = "paid"
    return {"success": True}
''',
    "payment_test.py": '''async def test_charge_timeout(gateway, order):
    gateway.charge.side_effect = TimeoutError()
    result = await charge_order(order, gateway)
    assert result["success"] is False
''',
}

DEMO_RESOURCES = {
    "order-1024": {
        "order_id": "1024",
        "status": "payment_failed",
        "gateway_code": "TIMEOUT",
        "attempts": 3,
    },
    "python-course": {
        "course": "Python 入门",
        "students": 128,
        "completion_rate": "68%",
        "risk": "第 4 章退出率偏高",
    },
}


async def _inspect_handler(payload: dict[str, Any]) -> dict[str, Any]:
    contexts = payload.get("context", [])
    observations = []
    for item in contexts:
        content = item.get("content", "")
        if "TimeoutError" in content or "TIMEOUT" in content:
            observations.append("发现超时路径，但业务函数没有捕获网关超时异常。")
        if "result.status" in content:
            observations.append("支付结果仅判断 status，缺少异常与幂等保护。")
    return {"observations": observations or ["已检查上下文，未发现明确异常模式。"]}


async def _test_handler(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "suggested_tests": [
            "网关超时应返回结构化失败结果",
            "重复支付请求不得产生二次扣款",
            "成功后应持久化 paid 状态",
        ]
    }


def register_skill(
    registry: CapabilityRegistry,
    catalog: MentionCatalog,
    skill,
) -> None:
    registry.upsert(skill.descriptor, skill.build_handler())
    catalog.add(
        MentionRef(
            kind=MentionKind.SKILL,
            id=skill.descriptor.id,
            label=skill.descriptor.name,
            metadata={
                "description": skill.descriptor.description,
                **skill.descriptor.metadata,
            },
        )
    )


def build_default_registry(
    external_skill_root: Path | None = None,
) -> tuple[CapabilityRegistry, MentionCatalog]:
    from .skill_loader import discover_skills

    registry = CapabilityRegistry()
    catalog = MentionCatalog()

    for skill in discover_skills(Path(__file__).parent / "skills", source="built-in"):
        register_skill(registry, catalog, skill)
    if external_skill_root is not None:
        for skill in discover_skills(external_skill_root, source="external"):
            register_skill(registry, catalog, skill)

    tool_capabilities = [
        Capability(
            id="inspect-context",
            name="上下文检查器",
            description="从引用的文件和业务对象中提取事实、异常模式和约束。",
            kind=CapabilityKind.TOOL,
            triggers=["分析", "检查", "定位", "为什么", "失败"],
            permissions=["read"],
        ),
        Capability(
            id="suggest-tests",
            name="测试建议器",
            description="根据上下文和意图生成关键测试场景。",
            kind=CapabilityKind.TOOL,
            triggers=["测试", "修复", "验证", "代码"],
            permissions=["read"],
        ),
    ]

    for capability in tool_capabilities:
        handler = _inspect_handler
        if capability.id == "inspect-context":
            handler = _inspect_handler
        elif capability.id == "suggest-tests":
            handler = _test_handler
        registry.register(capability, handler)
        catalog.add(
            MentionRef(
                kind=MentionKind.TOOL,
                id=capability.id,
                label=capability.name,
                metadata={"description": capability.description},
            )
        )

    for file_id in DEMO_FILES:
        catalog.add(MentionRef(kind=MentionKind.FILE, id=file_id, label=file_id))
    catalog.add(MentionRef(kind=MentionKind.RESOURCE, id="order-1024", label="订单 #1024"))
    catalog.add(MentionRef(kind=MentionKind.RESOURCE, id="python-course", label="Python 入门课程"))
    return registry, catalog
