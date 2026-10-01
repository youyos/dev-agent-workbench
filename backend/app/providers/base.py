from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..models import (
    Capability,
    CapabilityResult,
    NextAction,
    ResolvedContextItem,
    RouteDecision,
    TaskIntent,
)


class ModelProvider(ABC):
    supports_history: bool = False

    async def next_action(
        self,
        intent: TaskIntent,
        context: list[ResolvedContextItem],
        results: list[CapabilityResult],
        candidates: list[Capability],
    ) -> NextAction:
        """Providers without iterative planning retain a single execution pass."""
        return NextAction(action="finish", reason="当前计划已执行完毕")

    @abstractmethod
    async def analyze_intent(
        self,
        message: str,
        context: list[ResolvedContextItem],
    ) -> TaskIntent:
        raise NotImplementedError

    @abstractmethod
    async def choose_capabilities(
        self,
        intent: TaskIntent,
        candidates: list[Capability],
        forced_ids: set[str],
    ) -> RouteDecision:
        raise NotImplementedError

    @abstractmethod
    async def prepare_capability_arguments(
        self,
        capability: Capability,
        message: str,
        intent: TaskIntent,
        context: list[ResolvedContextItem],
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def stream_answer(
        self,
        message: str,
        intent: TaskIntent,
        context: list[ResolvedContextItem],
        results: list[CapabilityResult],
    ) -> AsyncIterator[str]:
        raise NotImplementedError
