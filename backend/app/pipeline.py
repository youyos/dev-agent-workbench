from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from time import perf_counter

from .catalog import CapabilityRegistry, ContextResolver
from .models import (
    AgentRunContext,
    AgentRunRequest,
    CapabilityKind,
    CapabilityResult,
    CapabilitySelection,
    ChatMessage,
    ExecutionPlan,
    MentionKind,
    PendingApproval,
    PlanStep,
    RunEvent,
)
from .providers.base import ModelProvider
from .runtime_context import model_context
from .runtime_extensions import (
    OutputRegistry,
    PermissionPolicy,
    PolicyRegistry,
    capability_fingerprint,
    validate_arguments,
)
from .runtime_store import MemoryRuntimeStore, RuntimeStore, bounded_history


class AgentPipeline:
    """Provider-neutral runtime. Business rules and output formats are registered by the host."""

    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        resolver: ContextResolver,
        provider: ModelProvider,
        policies: PolicyRegistry | None = None,
        outputs: OutputRegistry | None = None,
        permissions: PermissionPolicy | None = None,
        store: RuntimeStore | None = None,
        max_steps: int = 12,
        operation_timeout: float = 120,
    ) -> None:
        self.registry = registry
        self.resolver = resolver
        self.provider = provider
        self.policies = policies or PolicyRegistry()
        self.outputs = outputs or OutputRegistry()
        self.permissions = permissions or PermissionPolicy()
        self.store = store or MemoryRuntimeStore()
        self.max_steps = max_steps
        self.operation_timeout = operation_timeout
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._cancelled: set[str] = set()

    def _event(self, state: AgentRunContext, kind: str, data: dict) -> RunEvent:
        state.sequence += 1
        event = RunEvent(run_id=state.run_id, sequence=state.sequence, type=kind, data=data)
        self.store.append(event, state)
        return event

    async def _wait(self, state: AgentRunContext, awaitable, timeout: float | None = None):
        if state.run_id in self._cancelled:
            close = getattr(awaitable, "close", None)
            if close:
                close()
            raise asyncio.CancelledError()
        task = asyncio.ensure_future(awaitable)
        self._tasks[state.run_id] = task
        try:
            return await asyncio.wait_for(task, timeout or self.operation_timeout)
        finally:
            self._tasks.pop(state.run_id, None)

    def _model_context(self, state: AgentRunContext):
        return model_context(state, include_history=self.provider.supports_history)

    async def run(self, request: AgentRunRequest, *, identity: dict | None = None):
        sid = request.session_id or self.store.create_session()
        lock = self._session_locks.setdefault(sid, asyncio.Lock())
        if lock.locked():
            raise ValueError("当前会话正在执行，请等待或取消当前运行")
        async with lock:
            if self.store.active_run(sid):
                raise ValueError("当前会话有待确认的操作，请先批准、拒绝或取消")
            stored = self.store.messages(sid)
            if not stored:
                for index, message in enumerate(request.history):
                    self.store.save_message(
                        sid, f"import-{sid}-{index}", message.role, message.content
                    )
                stored = self.store.messages(sid)
            history = bounded_history(
                [
                    ChatMessage(role=item["role"], content=item["content"][:20_000])
                    for item in stored
                    if item["content"]
                ]
            )
            state = AgentRunContext(session_id=sid, request=request, history=history,
                                    identity=identity or {})
            self.store.save(state)
            self.store.save_message(sid, state.run_id, "user", request.message)
            async for event in self._drive(state, initialize=True):
                yield event

    async def resume(self, run_id: str, approval_id: str, approved: bool):
        state = self.store.load(run_id)
        lock = self._session_locks.setdefault(state.session_id, asyncio.Lock())
        if lock.locked():
            raise ValueError("运行已在恢复中")
        async with lock:
            state = self.store.load(run_id)
            pending = state.pending_approval
            if state.status != "awaiting_approval" or not pending or pending.id != approval_id:
                raise ValueError("审批不存在、已处理或运行已结束")
            if pending.created_at < datetime.now(UTC) - timedelta(hours=24):
                raise ValueError("审批已过期，请取消并发起新请求")
            registration = self.registry.get(pending.capability_id)
            if (
                not registration
                or capability_fingerprint(registration.descriptor) != pending.fingerprint
            ):
                raise ValueError("能力配置已变化，请取消并重新发起请求")
            if not self.permissions.check(
                state, registration.descriptor, pending.arguments
            ).allowed:
                raise ValueError("当前策略已拒绝该操作")
            state.status = "running"
            yield self._event(
                state,
                "approval.resolved",
                {
                    "approval_id": approval_id,
                    "approved": approved,
                },
            )
            async for event in self._drive(state, initialize=False, approval=approved):
                yield event

    def cancel(self, run_id: str) -> None:
        state = self.store.load(run_id)
        if state.status not in {"running", "awaiting_approval"}:
            return
        self._cancelled.add(run_id)
        task = self._tasks.get(run_id)
        if task:
            task.cancel()
        elif state.status == "awaiting_approval":
            state.status = "cancelled"
            state.pending_approval = None
            self._event(state, "run.cancelled", {"message": "待审批运行已取消"})

    async def _drive(
        self, state: AgentRunContext, *, initialize: bool, approval: bool | None = None
    ):
        started = perf_counter()
        try:
            if initialize:
                async for event in self._initialize(state):
                    yield event
                if state.status != "running":
                    return
            async for event in self._execute(state, approval):
                yield event
            if state.status != "running":
                return
            if state.run_id in self._cancelled:
                raise asyncio.CancelledError()
            yield self._event(
                state,
                "response.synthesizing",
                {
                    "context_count": len(state.context),
                    "result_count": len(state.results),
                    "successful_results": sum(item.success for item in state.results),
                    "explanation": "使用本轮 Skill、工具结果和会话上下文组织最终输出。",
                },
            )
            if state.route.output_contract:
                renderer = self.outputs.get(state.route.output_contract)
                output_stream = renderer.render(state)
                final_message = False
                try:
                    while True:
                        try:
                            kind, data = await self._wait(state, anext(output_stream))
                        except StopAsyncIteration:
                            break
                        if kind in {"recommendation", "html", "artifact"}:
                            state.output = {"type": kind, **data}
                        if kind == "message.completed":
                            self._save_answer(state, data["content"])
                            final_message = True
                        yield self._event(state, kind, data)
                finally:
                    await output_stream.aclose()
                if not final_message:
                    raise ValueError("Renderer 必须返回 message.completed 作为终态输出")
            else:
                answer = ""
                stream = self.provider.stream_answer(
                    state.request.message, state.intent, self._model_context(state), state.results
                )
                try:
                    while True:
                        try:
                            delta = await self._wait(state, anext(stream))
                        except StopAsyncIteration:
                            break
                        answer += delta
                        yield self._event(state, "message.delta", {"delta": delta})
                finally:
                    await stream.aclose()
                self._save_answer(state, answer)
                yield self._event(
                    state,
                    "message.completed",
                    {
                        "content": answer,
                        "character_count": len(answer),
                    },
                )
            state.status = "completed"
            yield self._event(
                state,
                "run.completed",
                {
                    "session_id": state.session_id,
                    "history_count": len(state.history),
                    "selected_capabilities": [item.capability_id for item in state.results],
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                },
            )
        except (asyncio.CancelledError, GeneratorExit):
            state.status = "cancelled"
            state.pending_approval = None
            self._event(state, "run.cancelled", {"message": "运行已取消"})
            raise
        except Exception as exc:
            state.status = "failed"
            yield self._event(state, "run.error", {"message": str(exc), "code": type(exc).__name__})
        finally:
            self._cancelled.discard(state.run_id)

    async def _initialize(self, state: AgentRunContext):
        yield self._event(
            state,
            "run.started",
            {
                "session_id": state.session_id,
                "history_count": len(state.history),
                "message": state.request.message,
                "mention_count": len(state.request.mentions),
                "provider": type(self.provider).__name__,
            },
        )
        state.context = await self._wait(state, self.resolver.resolve(state.request.mentions))
        yield self._event(
            state,
            "context.resolved",
            {
                "items": [
                    {
                        "id": item.mention.id,
                        "title": item.title,
                        "kind": item.mention.kind,
                        "source": item.source,
                        "preview": item.content[:220],
                    }
                    for item in state.context
                ],
            },
        )
        state.intent = await self._wait(
            state, self.provider.analyze_intent(state.request.message, self._model_context(state))
        )
        yield self._event(state, "intent.detected", state.intent.model_dump())
        if state.intent.needs_clarification:
            for event in self._ask(state, state.intent.clarification_question or "请补充任务信息"):
                yield event
            return
        candidates = self.registry.list()
        forced = {
            item.id
            for item in state.request.mentions
            if item.kind in {MentionKind.SKILL, MentionKind.TOOL, MentionKind.MCP}
        }
        missing = forced - {item.id for item in candidates}
        if missing:
            raise ValueError(f"引用的能力已失效：{', '.join(sorted(missing))}")
        policy = self.policies.resolve(state, candidates)
        if policy.matched:
            yield self._event(state, "policy.matched", {"policy_id": policy.policy_id})
            if policy.question:
                for event in self._ask(state, policy.question):
                    yield event
                return
            state.route = policy.route
        else:
            eligible = [item for item in candidates if not item.explicit_only or item.id in forced]
            state.route = await self._wait(
                state, self.provider.choose_capabilities(state.intent, eligible, forced)
            )
        if state.route is None:
            raise ValueError("路由策略没有返回执行路线")
        if state.route.output_contract:
            self.outputs.get(state.route.output_contract)
        selections = list(state.route.selections)
        for cid in sorted(forced - {item.capability_id for item in selections}):
            selections.append(
                CapabilitySelection(capability_id=cid, forced=True, reason="用户显式指定")
            )
        # Dependencies are resolved before execution, not delegated to the model.
        for selection in list(selections):
            registration = self.registry.get(selection.capability_id)
            if not registration or registration.descriptor.kind != CapabilityKind.SKILL:
                continue
            for dependency in registration.descriptor.metadata.get("required_capabilities", []):
                if not self.registry.get(dependency):
                    raise ValueError(f"Skill {selection.capability_id} 缺少依赖能力 {dependency}")
                selections.append(
                    CapabilitySelection(
                        capability_id=dependency,
                        reason=f"Skill {selection.capability_id} 声明的依赖",
                    )
                )
        # Load all selected Skills before any tool parameters are generated.
        selections.sort(
            key=lambda item: (
                self.registry.get(item.capability_id) is not None
                and self.registry.get(item.capability_id).descriptor.kind != CapabilityKind.SKILL
            )
        )
        steps = []
        for selection in selections:
            registration = self.registry.get(selection.capability_id)
            if not registration:
                raise ValueError(f"模型选择了不存在的能力：{selection.capability_id}")
            if selection.capability_id in state.bindings:
                continue
            state.bindings[selection.capability_id] = capability_fingerprint(
                registration.descriptor
            )
            steps.append(
                PlanStep(
                    id=f"step-{len(steps) + 1}",
                    title=registration.descriptor.name,
                    capability_id=selection.capability_id,
                    instruction=selection.reason,
                )
            )
        state.plan = ExecutionPlan(objective=state.intent.goal, steps=steps)
        yield self._event(
            state,
            "route.selected",
            {
                **state.route.model_dump(),
                "candidate_count": len(candidates),
                "candidates": [item.model_dump() for item in candidates],
            },
        )
        yield self._event(state, "plan.created", state.plan.model_dump())

    async def _execute(self, state: AgentRunContext, approval: bool | None):
        while state.status == "running":
            if state.cursor >= len(state.plan.steps):
                if state.route.output_contract:
                    break
                candidates = [
                    item
                    for item in self.registry.list()
                    if item.kind != CapabilityKind.SKILL
                    and not item.explicit_only
                    and item.id
                    not in {result.capability_id for result in state.results if not result.success}
                ]
                decision = await self._wait(
                    state,
                    self.provider.next_action(
                        state.intent, self._model_context(state), state.results, candidates
                    ),
                )
                yield self._event(state, "execution.decided", decision.model_dump())
                if decision.action == "finish":
                    break
                if decision.action == "ask":
                    for event in self._ask(state, decision.question or "请补充执行信息"):
                        yield event
                    return
                if state.cursor >= self.max_steps:
                    raise ValueError("达到最大执行步骤数，无法继续工具调用")
                capability = next(
                    (item for item in candidates if item.id == decision.capability_id), None
                )
                if not capability:
                    raise ValueError("执行决策选择了不可用的工具")
                state.bindings[capability.id] = capability_fingerprint(capability)
                state.plan.steps.append(
                    PlanStep(
                        id=f"step-{len(state.plan.steps) + 1}",
                        title=capability.name,
                        capability_id=capability.id,
                        instruction=decision.reason,
                    )
                )
                yield self._event(state, "plan.updated", state.plan.model_dump())
            if state.cursor >= self.max_steps:
                raise ValueError("达到最大执行步骤数，运行已停止")
            step = state.plan.steps[state.cursor]
            registration = self.registry.get(step.capability_id)
            if not registration:
                raise ValueError(f"能力已被移除：{step.capability_id}")
            capability = registration.descriptor
            if capability_fingerprint(capability) != state.bindings.get(capability.id):
                raise ValueError("能力定义已变化，请重新发起任务")
            started = perf_counter()
            pending = state.pending_approval
            arguments = (
                pending.arguments
                if pending
                else await self._wait(
                    state,
                    self.provider.prepare_capability_arguments(
                        capability, state.request.message, state.intent, self._model_context(state)
                    ),
                )
            )
            validate_arguments(capability, arguments)
            permission = self.permissions.check(state, capability, arguments)
            if not permission.allowed:
                raise PermissionError(permission.reason)
            if permission.approval_required and approval is None:
                state.pending_approval = PendingApproval(
                    capability_id=capability.id,
                    arguments=arguments,
                    fingerprint=state.bindings[capability.id],
                    reason=permission.reason,
                )
                state.status = "awaiting_approval"
                yield self._event(
                    state,
                    "approval.required",
                    {
                        **state.pending_approval.model_dump(mode="json"),
                        "name": capability.name,
                        "session_id": state.session_id,
                    },
                )
                return
            state.pending_approval = None
            denied = approval is False
            approval = None
            yield self._event(
                state,
                "capability.started",
                {
                    "step_id": step.id,
                    "capability_id": capability.id,
                    "name": capability.name,
                    "kind": capability.kind,
                    "permissions": capability.permissions,
                    "instruction": step.instruction,
                    "description": capability.description,
                    "input_schema": capability.input_schema,
                },
            )
            yield self._event(
                state,
                "capability.arguments",
                {
                    "capability_id": capability.id,
                    "arguments": arguments,
                    "previous_result_count": len(state.results),
                    "explanation": "参数生成读取了已加载 Skill、本轮上下文和此前工具结果；Schema 已校验。",
                },
            )
            if denied:
                result = CapabilityResult(
                    capability_id=capability.id,
                    success=False,
                    summary="用户拒绝执行",
                    arguments=arguments,
                )
            else:
                try:
                    output = await self._wait(
                        state,
                        registration.handler(
                            {
                                "run_id": state.run_id,
                                "session_id": state.session_id,
                                "step_id": step.id,
                                "message": state.request.message,
                                "intent": state.intent.model_dump(),
                                "instruction": step.instruction,
                                "arguments": arguments,
                                "context": [
                                    item.model_dump(mode="json")
                                    for item in self._model_context(state)
                                ],
                                "previous_results": [item.model_dump() for item in state.results],
                                "loaded_skills": list(state.loaded_skills),
                            }
                        ),
                        capability.timeout_seconds,
                    )
                    if not isinstance(output, dict):
                        raise ValueError("Capability handler 必须返回字典")
                    failed = output.get("is_error") is True or output.get("success") is False
                    result = CapabilityResult(
                        capability_id=capability.id,
                        success=not failed,
                        summary=f"{capability.name} {'执行失败' if failed else '执行完成'}",
                        data=output,
                        arguments=arguments,
                    )
                except Exception as exc:
                    result = CapabilityResult(
                        capability_id=capability.id,
                        success=False,
                        summary=f"{capability.name} 执行失败：{exc}",
                        arguments=arguments,
                    )
            state.results.append(result)
            state.cursor += 1
            if capability.kind == CapabilityKind.SKILL and result.success:
                state.loaded_skills.append(capability.id)
            if capability.kind == CapabilityKind.SKILL and not result.success:
                raise ValueError("Skill 加载失败，停止依赖其规则的后续执行")
            yield self._event(
                state,
                "capability.completed",
                {
                    **result.model_dump(),
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                },
            )

    def _ask(self, state: AgentRunContext, question: str):
        state.status = "needs_input"
        self._save_answer(state, question)
        yield self._event(state, "run.needs_input", {"question": question})
        yield self._event(
            state, "message.completed", {"content": question, "status": "needs_input"}
        )

    def _save_answer(self, state: AgentRunContext, content: str):
        self.store.save_message(state.session_id, state.run_id, "assistant", content, state.output)
