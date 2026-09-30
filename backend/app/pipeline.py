from __future__ import annotations

from collections.abc import AsyncIterator
from time import perf_counter
from uuid import uuid4

from .catalog import CapabilityRegistry, ContextResolver
from .models import (
    AgentRunRequest,
    CapabilityResult,
    ChatMessage,
    ExecutionPlan,
    MentionKind,
    MentionRef,
    PlanStep,
    ResolvedContextItem,
    RunEvent,
)
from .providers.base import ModelProvider


class AgentPipeline:
    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        resolver: ContextResolver,
        provider: ModelProvider,
    ) -> None:
        self._registry = registry
        self._resolver = resolver
        self._provider = provider

    async def run(self, request: AgentRunRequest) -> AsyncIterator[RunEvent]:
        run_id = str(uuid4())
        sequence = 0
        run_started_at = perf_counter()
        provider_name = type(self._provider).__name__
        history = _trim_history(request.history)

        def event(event_type: str, data: dict) -> RunEvent:
            nonlocal sequence
            sequence += 1
            return RunEvent(run_id=run_id, sequence=sequence, type=event_type, data=data)

        yield event(
            "run.started",
            {
                "message": request.message,
                "mention_count": len(request.mentions),
                "history_count": len(history),
                "history_preview": [item.model_dump() for item in history[-4:]],
                "provider": provider_name,
                "explanation": "创建一次独立运行，并固定本轮用户输入与显式 @ 引用。",
            },
        )

        stage_started_at = perf_counter()
        context = await self._resolver.resolve(request.mentions)
        yield event(
            "context.resolved",
            {
                "input_mentions": [item.model_dump(mode="json") for item in request.mentions],
                "items": [
                    {
                        "kind": item.mention.kind,
                        "id": item.mention.id,
                        "title": item.title,
                        "source": item.source,
                        "preview": item.content[:220],
                    }
                    for item in context
                ],
                "duration_ms": round((perf_counter() - stage_started_at) * 1_000, 2),
                "explanation": (
                    "把前端提交的结构化引用交给对应 Resolver，生成带来源的上下文快照；"
                    "后续模型只接收这些已解析内容。"
                ),
            },
        )
        model_context = _context_with_history(
            context,
            history,
            include_history=provider_name in {"QwenModelProvider", "DemoModelProvider"},
        )

        stage_started_at = perf_counter()
        intent = await self._provider.analyze_intent(request.message, model_context)
        yield event(
            "intent.detected",
            {
                **intent.model_dump(),
                "provider": provider_name,
                "duration_ms": round((perf_counter() - stage_started_at) * 1_000, 2),
                "explanation": (
                    "将自然语言整理为目标、意图、实体、约束和期望输出，"
                    "让后续路由面对稳定的数据结构，而不是直接猜测原始文本。"
                ),
            },
        )
        if intent.needs_clarification:
            question = intent.clarification_question or "请补充执行所需信息。"
            yield event(
                "run.needs_input",
                {
                    "question": question,
                    "explanation": (
                        "当前输入无法确定唯一任务目标；继续猜测可能选择错误能力，因此暂停执行并请求补充信息。"
                    ),
                },
            )
            yield event(
                "message.completed",
                {
                    "content": question,
                    "character_count": len(question),
                    "duration_ms": 0,
                    "status": "needs_input",
                },
            )
            return

        forced_ids = {
            mention.id
            for mention in request.mentions
            if mention.kind in {MentionKind.SKILL, MentionKind.TOOL, MentionKind.MCP}
        }
        candidates = self._registry.list()
        stage_started_at = perf_counter()
        route = await self._provider.choose_capabilities(intent, candidates, forced_ids)
        yield event(
            "route.selected",
            {
                **route.model_dump(),
                "forced_ids": sorted(forced_ids),
                "candidate_count": len(candidates),
                "candidates": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "kind": item.kind,
                        "description": item.description,
                    }
                    for item in candidates
                ],
                "duration_ms": round((perf_counter() - stage_started_at) * 1_000, 2),
                "explanation": (
                    "先保留用户通过 @ 强制指定的能力，再从注册中心候选中选择最多三个相关能力。"
                ),
            },
        )

        steps = []
        for index, selection in enumerate(route.selections, start=1):
            registration = self._registry.get(selection.capability_id)
            if registration is None:
                continue
            steps.append(
                PlanStep(
                    id=f"step-{index}",
                    title=f"使用 {registration.descriptor.name}",
                    capability_id=registration.descriptor.id,
                    instruction=selection.reason,
                )
            )
        plan = ExecutionPlan(objective=intent.goal, steps=steps)
        yield event(
            "plan.created",
            {
                **plan.model_dump(),
                "explanation": "把路由结果转成顺序执行的步骤，每一步绑定一个具体 Capability。",
            },
        )

        results: list[CapabilityResult] = []
        context_payload = [item.model_dump(mode="json") for item in context]
        for step in plan.steps:
            registration = self._registry.get(step.capability_id)
            if registration is None:
                continue
            capability_started_at = perf_counter()
            yield event(
                "capability.started",
                {
                    "step_id": step.id,
                    "capability_id": step.capability_id,
                    "name": registration.descriptor.name,
                    "kind": registration.descriptor.kind,
                    "description": registration.descriptor.description,
                    "permissions": registration.descriptor.permissions,
                    "input_schema": registration.descriptor.input_schema,
                    "instruction": step.instruction,
                    "explanation": "准备执行被路由选中的能力，并检查其权限和输入结构。",
                },
            )
            try:
                arguments = await self._provider.prepare_capability_arguments(
                    registration.descriptor,
                    request.message,
                    intent,
                    context,
                )
                if registration.descriptor.input_schema:
                    yield event(
                        "capability.arguments",
                        {
                            "capability_id": step.capability_id,
                            "arguments": arguments,
                            "input_schema": registration.descriptor.input_schema,
                            "provider": provider_name,
                            "explanation": (
                                "根据用户请求、结构化意图和上下文生成符合工具 Schema 的参数。"
                            ),
                        },
                    )
                output = await registration.handler(
                    {
                        "message": request.message,
                        "intent": intent.model_dump(),
                        "instruction": step.instruction,
                        "context": context_payload,
                        "arguments": arguments,
                    }
                )
                result = CapabilityResult(
                    capability_id=step.capability_id,
                    success=True,
                    summary=f"{registration.descriptor.name} 执行完成",
                    data=output,
                )
            except Exception as exc:  # noqa: BLE001 - keep the remaining plan observable
                result = CapabilityResult(
                    capability_id=step.capability_id,
                    success=False,
                    summary=f"执行失败：{exc}",
                )
            results.append(result)
            yield event(
                "capability.completed",
                {
                    **result.model_dump(),
                    "duration_ms": round((perf_counter() - capability_started_at) * 1_000, 2),
                    "explanation": (
                        "能力输出已保存，后续回答合成阶段会把它作为可追溯证据使用。"
                    ),
                },
            )

        full_answer = ""
        yield event(
            "response.synthesizing",
            {
                "provider": provider_name,
                "context_count": len(context),
                "result_count": len(results),
                "successful_results": sum(1 for item in results if item.success),
                "explanation": "组合原始问题、已解析上下文和能力结果，生成面向用户的最终回答。",
            },
        )
        synthesis_started_at = perf_counter()
        async for delta in self._provider.stream_answer(
            request.message,
            intent,
            model_context,
            results,
        ):
            full_answer += delta
            yield event("message.delta", {"delta": delta})
        yield event(
            "message.completed",
            {
                "content": full_answer,
                "character_count": len(full_answer),
                "duration_ms": round((perf_counter() - synthesis_started_at) * 1_000, 2),
            },
        )
        yield event(
            "run.completed",
            {
                "selected_capabilities": [item.capability_id for item in route.selections],
                "context_count": len(context),
                "history_count": len(history),
                "duration_ms": round((perf_counter() - run_started_at) * 1_000, 2),
                "explanation": "本轮所有计划步骤和回答合成均已结束。",
            },
        )


def _trim_history(
    history: list[ChatMessage],
    *,
    max_messages: int = 20,
    max_characters: int = 24_000,
) -> list[ChatMessage]:
    selected: list[ChatMessage] = []
    character_count = 0
    for message in reversed(history[-max_messages:]):
        next_count = character_count + len(message.content)
        if selected and next_count > max_characters:
            break
        if next_count > max_characters:
            selected.append(message.model_copy(update={"content": message.content[-max_characters:]}))
            break
        selected.append(message)
        character_count = next_count
    return list(reversed(selected))


def _context_with_history(
    context: list[ResolvedContextItem],
    history: list[ChatMessage],
    *,
    include_history: bool,
) -> list[ResolvedContextItem]:
    if not include_history or not history:
        return context
    history_text = "\n".join(f"{item.role}: {item.content}" for item in history)
    history_item = ResolvedContextItem(
        mention=MentionRef(
            kind=MentionKind.RESOURCE,
            id="conversation-history",
            label="当前会话历史",
        ),
        source="conversation-history",
        title=f"最近 {len(history)} 条对话历史",
        content=history_text,
        metadata={"history_count": len(history), "shared_with": "qwen-or-local-demo"},
    )
    return [*context, history_item]
