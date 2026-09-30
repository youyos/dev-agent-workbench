from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from ..models import (
    Capability,
    CapabilityResult,
    CapabilitySelection,
    ResolvedContextItem,
    RouteDecision,
    TaskIntent,
)
from .base import ModelProvider


class DemoModelProvider(ModelProvider):
    """Deterministic provider that demonstrates the complete pipeline offline."""

    async def analyze_intent(
        self,
        message: str,
        context: list[ResolvedContextItem],
    ) -> TaskIntent:
        normalized = message.casefold()
        if any(term in normalized for term in ("失败", "异常", "报错", "定位", "debug")):
            intent_name = "diagnose_failure"
            expected = "根因、证据、修复建议和验证方案"
        elif any(term in normalized for term in ("课程", "学生", "学习", "完成率")):
            intent_name = "analyze_learning_data"
            expected = "风险摘要和可执行干预建议"
        elif any(term in normalized for term in ("审查", "review", "代码")):
            intent_name = "review_code"
            expected = "按优先级排列的问题和修改建议"
        else:
            intent_name = "general_assistance"
            expected = "清晰、可执行的回答"

        entities = [item.title for item in context if item.mention.kind.value in {"file", "resource"}]
        constraints = re.findall(r"(?:不要|必须|只允许|限定)[^，。；\n]+", message)
        return TaskIntent(
            goal=message,
            intent=intent_name,
            entities=entities,
            constraints=constraints,
            expected_output=expected,
        )

    async def choose_capabilities(
        self,
        intent: TaskIntent,
        candidates: list[Capability],
        forced_ids: set[str],
    ) -> RouteDecision:
        text = " ".join([intent.goal, intent.intent, *intent.entities]).casefold()
        ranked: list[tuple[int, Capability]] = []
        for candidate in candidates:
            score = 100 if candidate.id in forced_ids else 0
            score += sum(8 for trigger in candidate.triggers if trigger.casefold() in text)
            if candidate.kind.value == "tool" and intent.intent != "general_assistance":
                score += 2
            ranked.append((score, candidate))
        ranked.sort(key=lambda item: (-item[0], item[1].id))

        chosen = [item for item in ranked if item[0] > 0][:3]
        if not chosen and ranked:
            chosen = [ranked[0]]
        selections = [
            CapabilitySelection(
                capability_id=capability.id,
                forced=capability.id in forced_ids,
                reason=(
                    "用户通过 @ 显式指定。"
                    if capability.id in forced_ids
                    else f"与意图 {intent.intent} 及当前上下文匹配。"
                ),
            )
            for _, capability in chosen
        ]
        return RouteDecision(
            selections=selections,
            summary=f"已选择 {len(selections)} 个最相关能力，显式 @ 引用优先。",
        )

    async def stream_answer(
        self,
        message: str,
        intent: TaskIntent,
        context: list[ResolvedContextItem],
        results: list[CapabilityResult],
    ) -> AsyncIterator[str]:
        observations: list[str] = []
        tests: list[str] = []
        for result in results:
            observations.extend(result.data.get("observations", []))
            tests.extend(result.data.get("suggested_tests", []))

        if intent.intent == "diagnose_failure":
            answer = (
                "## 诊断结论\n\n"
                "最可能的根因是支付网关超时没有在业务层被捕获。现有代码直接等待 "
                "`gateway.charge()`，超时会中断正常的失败结果封装；同时缺少幂等保护，重试可能造成重复扣款风险。\n\n"
                "## 建议修改\n\n"
                "1. 捕获网关超时并返回稳定的错误码，例如 `PAYMENT_GATEWAY_TIMEOUT`。\n"
                "2. 使用订单号作为幂等键，并在重试前查询已有支付状态。\n"
                "3. 将支付成功状态更新放入可靠事务或事件流程。\n"
            )
        elif intent.intent == "analyze_learning_data":
            answer = (
                "## 分析结论\n\n"
                "当前课程完成率为 68%，主要风险集中在第 4 章。建议先比较该章节的退出率、"
                "作业正确率和视频观看完成度，再对连续两次未完成学习任务的学生进行分层提醒。\n"
            )
        else:
            answer = "## 处理结果\n\n已根据结构化意图和已选能力完成分析。\n"

        if observations:
            answer += "\n## 证据\n\n" + "\n".join(f"- {item}" for item in observations) + "\n"
        if tests:
            answer += "\n## 验证建议\n\n" + "\n".join(f"- {item}" for item in tests) + "\n"
        answer += f"\n本轮解析了 {len(context)} 个 @ 上下文，并执行了 {len(results)} 个能力。"

        for chunk in _chunk_text(answer, 24):
            await asyncio.sleep(0.015)
            yield chunk

    async def prepare_capability_arguments(
        self,
        capability: Capability,
        message: str,
        intent: TaskIntent,
        context: list[ResolvedContextItem],
    ) -> dict:
        schema = capability.input_schema or {}
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        arguments = {}
        for name in required:
            definition = properties.get(name) or {}
            value_type = definition.get("type")
            if value_type == "array":
                arguments[name] = []
            elif value_type in {"integer", "number"}:
                arguments[name] = 0
            elif value_type == "boolean":
                arguments[name] = True
            else:
                arguments[name] = message
        return arguments


def _chunk_text(text: str, size: int) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)]
