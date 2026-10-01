from __future__ import annotations

from dataclasses import dataclass

from .models import (
    Capability,
    CapabilityKind,
    CapabilitySelection,
    RouteDecision,
    TaskIntent,
)

UNPUBLISHED_HOMEWORK_SCENARIO = "list-unpublished-homeworks"
UNPUBLISHED_HOMEWORK_CONTRACT = "preparation.unpublished_homework_cards.v1"


@dataclass(frozen=True)
class ScenarioResolution:
    matched: bool
    route: RouteDecision | None = None
    missing: tuple[str, ...] = ()


class ScenarioPolicyRegistry:
    """Deterministic business routing layered above model-based routing."""

    def resolve(
        self,
        message: str,
        intent: TaskIntent,
        candidates: list[Capability],
    ) -> ScenarioResolution:
        if not _is_unpublished_homework_request(message, intent):
            return ScenarioResolution(matched=False)

        query_skill = _find_skill(
            candidates,
            ids={"36", "educoder-query", "educoder-query-assistant", "educoder-skill"},
            names=("educoder 查询助手", "查询助手"),
        )
        preparation_skill = _find_skill(
            candidates,
            ids={"66", "preparation-assistant"},
            names=("备课助手",),
        )
        query_tool = _find_unpublished_homework_tool(candidates)

        missing = []
        if query_skill is None:
            missing.append("Educoder 查询助手")
        if preparation_skill is None:
            missing.append("备课助手")
        if query_tool is None:
            missing.append("未发布作业查询工具")
        if missing:
            return ScenarioResolution(matched=True, missing=tuple(missing))

        return ScenarioResolution(
            matched=True,
            route=RouteDecision(
                selections=[
                    CapabilitySelection(
                        capability_id=query_skill.id,
                        reason="作为 data_provider，为本轮提供真实 Educoder 作业数据。",
                    ),
                    CapabilitySelection(
                        capability_id=query_tool.id,
                        reason="查询当前范围内的未发布作业列表。",
                    ),
                    CapabilitySelection(
                        capability_id=preparation_skill.id,
                        reason="作为 output_owner，按照备课卡片协议组织最终结果。",
                    ),
                ],
                summary="命中特定场景：查询助手提供数据，备课助手拥有最终卡片输出。",
                scenario_id=UNPUBLISHED_HOMEWORK_SCENARIO,
                primary_skill_id=preparation_skill.id,
                supporting_skill_ids=[query_skill.id],
                output_contract=UNPUBLISHED_HOMEWORK_CONTRACT,
            ),
        )


def _is_unpublished_homework_request(message: str, intent: TaskIntent) -> bool:
    text = f"{message} {intent.intent} {intent.goal}".casefold()
    homework = "作业" in text or "homework" in text
    unpublished = any(
        marker in text
        for marker in ("未发布", "待发布", "尚未发布", "没有发布", "unpublished", "draft")
    )
    list_or_query = any(marker in text for marker in ("查询", "查看", "列出", "列表", "哪些", "list"))
    return homework and unpublished and list_or_query


def _find_skill(
    candidates: list[Capability],
    *,
    ids: set[str],
    names: tuple[str, ...],
) -> Capability | None:
    normalized_names = tuple(name.casefold() for name in names)
    for candidate in candidates:
        if candidate.kind is not CapabilityKind.SKILL:
            continue
        if candidate.id.casefold() in ids:
            return candidate
        name = candidate.name.casefold()
        if any(alias in name for alias in normalized_names):
            return candidate
    return None


def _find_unpublished_homework_tool(candidates: list[Capability]) -> Capability | None:
    ranked: list[tuple[int, Capability]] = []
    for candidate in candidates:
        if candidate.kind not in {CapabilityKind.MCP, CapabilityKind.TOOL}:
            continue
        text = " ".join(
            [
                candidate.id,
                candidate.name,
                candidate.description,
                str(candidate.metadata.get("mcp_tool_name") or ""),
            ]
        ).casefold()
        if "作业" not in text and "homework" not in text:
            continue
        is_write_tool = "write" in candidate.permissions or any(
            marker in text for marker in ("批量发布", "立即发布", "publish_homework", "homework_publish")
        )
        if is_write_tool:
            continue
        score = 4
        score += 6 if any(marker in text for marker in ("未发布", "待发布", "unpublished", "draft")) else 0
        score += 3 if any(marker in text for marker in ("列表", "查询", "list")) else 0
        score += 2 if any(marker in text for marker in ("状态", "status")) else 0
        score -= 20 if candidate.metadata.get("fixture") else 0
        ranked.append((score, candidate))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return ranked[0][1]
