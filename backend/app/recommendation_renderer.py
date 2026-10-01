from __future__ import annotations

import json
from typing import Any

from .models import (
    CapabilityResult,
    RecommendationItem,
    RecommendationPlan,
    RecommendationSection,
)
from .scenario_policy import UNPUBLISHED_HOMEWORK_CONTRACT


class RecommendationRenderError(ValueError):
    pass


class RecommendationRenderer:
    """Render validated recommendation cards from normalized capability results."""

    def render(
        self,
        output_contract: str,
        results: list[CapabilityResult],
    ) -> RecommendationPlan:
        if output_contract != UNPUBLISHED_HOMEWORK_CONTRACT:
            raise RecommendationRenderError(f"不支持的输出协议：{output_contract}")
        homeworks, section_meta, is_demo = _extract_homeworks(results)
        if not homeworks:
            raise RecommendationRenderError("查询结果中没有可生成卡片的未发布作业")
        items = [RecommendationItem.model_validate(_normalize_homework(item)) for item in homeworks]
        count = len(items)
        return RecommendationPlan(
            text=f"当前课堂共有 {count} 份未发布作业。",
            title="未发布作业",
            description=(
                "以下为场景 Fixture 模拟数据；接入真实 Skill 和 MCP 后将显示本轮 Educoder 查询结果。"
                if is_demo
                else "可查看作业详情或继续发布操作。"
            ),
            card_type="homework",
            sections=[
                RecommendationSection(
                    key="unpublished_homeworks",
                    title="待发布",
                    items=items,
                    meta=section_meta,
                )
            ],
        )


def _extract_homeworks(
    results: list[CapabilityResult],
) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    best_items: list[dict[str, Any]] = []
    best_meta: dict[str, Any] = {}
    best_score = -1
    best_is_demo = False
    for result in results:
        if not result.success:
            continue
        value = _decode_nested(result.data)
        for candidate, meta in _candidate_lists(value):
            normalized = [item for item in candidate if isinstance(item, dict)]
            if not normalized:
                continue
            score = sum(_homework_item_score(item) for item in normalized)
            if score > best_score:
                best_items = normalized
                best_meta = meta
                best_score = score
                best_is_demo = _contains_demo_marker(value)
    return [item for item in best_items if not _is_published(item)], best_meta, best_is_demo


def _decode_nested(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return _decode_nested(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return value
    if isinstance(value, dict):
        return {key: _decode_nested(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_nested(item) for item in value]
    return value


def _contains_demo_marker(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("_demo") is True:
            return True
        return any(_contains_demo_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_demo_marker(item) for item in value)
    return False


def _candidate_lists(
    value: Any,
    depth: int = 0,
    inherited_meta: dict[str, Any] | None = None,
) -> list[tuple[list[Any], dict[str, Any]]]:
    if depth > 6:
        return []
    if isinstance(value, list):
        candidates = (
            [(value, dict(inherited_meta or {}))]
            if value and all(isinstance(item, dict) for item in value)
            else []
        )
        for item in value:
            candidates.extend(_candidate_lists(item, depth + 1, inherited_meta))
        return candidates
    if not isinstance(value, dict):
        return []
    current_meta = value.get("meta") if isinstance(value.get("meta"), dict) else inherited_meta
    preferred: list[tuple[list[Any], dict[str, Any]]] = []
    fallback: list[tuple[list[Any], dict[str, Any]]] = []
    for key, item in value.items():
        found = _candidate_lists(item, depth + 1, current_meta)
        if key.casefold() in {"homeworks", "homework_list", "items", "list", "records", "results", "data"}:
            preferred.extend(found)
        else:
            fallback.extend(found)
    return [*preferred, *fallback]


def _homework_item_score(item: dict[str, Any]) -> int:
    keys = {str(key).casefold() for key in item}
    score = 0
    if keys & {"id", "homework_id", "work_id"}:
        score += 3
    if keys & {"name", "title", "homework_name", "work_name"}:
        score += 4
    if keys & {"status", "publish_status", "published", "is_published"}:
        score += 2
    if keys & {"homework_type", "work_type", "type"}:
        score += 1
    return score


def _normalize_homework(item: dict[str, Any]) -> dict[str, Any]:
    homework_id = _first(item, "homework_id", "id", "work_id")
    title = _first(item, "homework_name", "name", "title", "work_name")
    if not title:
        raise RecommendationRenderError("作业数据缺少 title/name")
    homework_type = _first(item, "homework_type", "work_type", "type") or "作业"
    status = _first(item, "status_name", "publish_status", "status") or "未发布"
    normalized: dict[str, Any] = dict(item)
    normalized.setdefault("id", str(homework_id or ""))
    normalized.setdefault("type", str(homework_type))
    normalized.setdefault("title", str(title))
    normalized.setdefault("status", str(status))
    normalized.setdefault("action_label", "查看详情")
    url = _first(item, "url", "action_url", "detail_url")
    if url and not normalized.get("url"):
        normalized["url"] = str(url)
    return normalized


def _is_published(item: dict[str, Any]) -> bool:
    published = _first(item, "published", "is_published")
    if isinstance(published, bool):
        return published
    status = str(_first(item, "status_name", "publish_status", "status") or "").casefold()
    if "未发布" in status or "待发布" in status or status in {"draft", "unpublished", "0"}:
        return False
    return status in {"published", "已发布", "1"}


def _first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None
