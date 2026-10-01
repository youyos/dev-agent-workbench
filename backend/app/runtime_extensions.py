from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from jsonschema import Draft202012Validator
from jsonschema.validators import validator_for

from .models import AgentRunContext, Capability, RouteDecision


@dataclass(frozen=True)
class PolicyResolution:
    matched: bool = False
    route: RouteDecision | None = None
    question: str = ""
    policy_id: str = ""


class RoutingPolicy(Protocol):
    def resolve(self, state: AgentRunContext, candidates: list[Capability]) -> PolicyResolution: ...


class PolicyRegistry:
    def __init__(self) -> None:
        self._policies: list[RoutingPolicy] = []

    def register(self, policy: RoutingPolicy) -> None:
        self._policies.append(policy)

    def resolve(self, state: AgentRunContext, candidates: list[Capability]) -> PolicyResolution:
        for policy in self._policies:
            resolution = policy.resolve(state, candidates)
            if resolution.matched:
                return resolution
        return PolicyResolution()


class OutputRenderer(Protocol):
    async def render(self, state: AgentRunContext) -> AsyncIterator[tuple[str, dict]]: ...


class OutputRegistry:
    def __init__(self) -> None:
        self._renderers: dict[str, OutputRenderer] = {}

    def register(self, contract: str, renderer: OutputRenderer) -> None:
        if contract in self._renderers:
            raise ValueError(f"输出协议重复：{contract}")
        self._renderers[contract] = renderer

    def get(self, contract: str) -> OutputRenderer:
        if contract not in self._renderers:
            raise ValueError(f"输出协议未注册：{contract}")
        return self._renderers[contract]


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    approval_required: bool = False
    reason: str = ""


class PermissionPolicy:
    """Host can replace this policy or register target/identity checks."""

    def __init__(self, allowed_permissions: set[str] | None = None) -> None:
        self.allowed_permissions = allowed_permissions or {
            "read",
            "external",
            "network",
            "write",
            "publish",
            "delete",
        }
        self._checks: list[Callable[[AgentRunContext, Capability, dict], PermissionDecision]] = []

    def register(
        self, check: Callable[[AgentRunContext, Capability, dict], PermissionDecision]
    ) -> None:
        self._checks.append(check)

    def check(
        self, state: AgentRunContext, capability: Capability, arguments: dict
    ) -> PermissionDecision:
        unsupported = set(capability.permissions) - self.allowed_permissions
        if unsupported:
            return PermissionDecision(
                False, reason=f"宿主未授权权限：{', '.join(sorted(unsupported))}"
            )
        approval = capability.requires_approval or bool(
            set(capability.permissions) & {"write", "publish", "delete"}
        )
        reason = "工具具有外部操作或写入权限，需要确认本次参数。" if approval else "权限检查通过"
        for check in self._checks:
            decision = check(state, capability, arguments)
            if not decision.allowed:
                return decision
            approval = approval or decision.approval_required
            if decision.reason:
                reason = decision.reason
        return PermissionDecision(True, approval, reason)


def validate_arguments(capability: Capability, arguments: dict[str, Any]) -> None:
    if capability.input_schema:
        validator_type = validator_for(capability.input_schema)
        validator_type.check_schema(capability.input_schema)
        validator = validator_type(capability.input_schema)
    else:
        validator = Draft202012Validator({"type": "object"})
    errors = sorted(validator.iter_errors(arguments), key=lambda item: str(item.path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.path) or "arguments"
        raise ValueError(f"工具参数校验失败（{path}）：{error.message}")


def capability_fingerprint(capability: Capability) -> str:
    binding = capability.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(binding, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
