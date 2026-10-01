from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class MentionKind(StrEnum):
    SKILL = "skill"
    FILE = "file"
    RESOURCE = "resource"
    TOOL = "tool"
    MCP = "mcp"


class MentionRef(BaseModel):
    kind: str = Field(min_length=1, max_length=80)
    id: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class AgentRunRequest(BaseModel):
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=50_000)
    mentions: list[MentionRef] = Field(default_factory=list, max_length=20)
    history: list[ChatMessage] = Field(default_factory=list, max_length=40)


class ResolvedContextItem(BaseModel):
    mention: MentionRef
    source: str
    title: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskIntent(BaseModel):
    goal: str
    intent: str
    entities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    expected_output: str = "clear answer"
    response_style: Literal["direct", "concise", "detailed"] = "concise"
    needs_clarification: bool = False
    clarification_question: str = ""


class CapabilityKind(StrEnum):
    SKILL = "skill"
    TOOL = "tool"
    MCP = "mcp"


class Capability(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    name: str
    description: str
    kind: CapabilityKind
    triggers: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    explicit_only: bool = False
    input_schema: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    timeout_seconds: float = Field(default=60, gt=0, le=300)


class McpServerConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$", min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=8, max_length=2_000)
    transport: Literal["streamable_http", "sse"] = "streamable_http"
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    allowed_tools: list[str] = Field(default_factory=list)
    approval_policy: Literal["always", "writes"] = "always"


class McpToolDescriptor(BaseModel):
    server_id: str
    name: str
    title: str = ""
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = False


class CapabilitySelection(BaseModel):
    capability_id: str
    reason: str
    forced: bool = False


class RouteDecision(BaseModel):
    selections: list[CapabilitySelection] = Field(default_factory=list)
    summary: str
    scenario_id: str = ""
    primary_skill_id: str = ""
    supporting_skill_ids: list[str] = Field(default_factory=list)
    output_contract: str = ""


class PlanStep(BaseModel):
    id: str
    title: str
    capability_id: str
    instruction: str


class ExecutionPlan(BaseModel):
    objective: str
    steps: list[PlanStep]


class CapabilityResult(BaseModel):
    capability_id: str
    success: bool
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    arguments: dict[str, Any] = Field(default_factory=dict)


class RecommendationItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | int = ""
    type: str | int = "作业"
    title: str = Field(min_length=1)
    url: str = ""
    action_label: str = "查看"


class RecommendationSection(BaseModel):
    key: str = ""
    title: str = Field(min_length=1)
    items: list[RecommendationItem] = Field(min_length=1)
    meta: dict[str, Any] = Field(default_factory=dict)


class RecommendationPlan(BaseModel):
    text: str = ""
    title: str = Field(min_length=1)
    description: str = ""
    card_type: Literal["lesson", "homework", "resource"]
    sections: list[RecommendationSection] = Field(min_length=1)


class RunEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    sequence: int
    type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)


class NextAction(BaseModel):
    action: Literal["call", "finish", "ask"] = "finish"
    capability_id: str = ""
    reason: str = ""
    question: str = ""


class PendingApproval(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    capability_id: str
    arguments: dict[str, Any]
    fingerprint: str
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentRunContext(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    request: AgentRunRequest
    identity: dict[str, Any] = Field(default_factory=dict)
    status: Literal[
        "running", "awaiting_approval", "needs_input", "completed", "failed", "cancelled"
    ] = "running"
    sequence: int = 0
    history: list[ChatMessage] = Field(default_factory=list)
    context: list[ResolvedContextItem] = Field(default_factory=list)
    intent: TaskIntent | None = None
    route: RouteDecision | None = None
    plan: ExecutionPlan | None = None
    cursor: int = 0
    results: list[CapabilityResult] = Field(default_factory=list)
    loaded_skills: list[str] = Field(default_factory=list)
    bindings: dict[str, str] = Field(default_factory=dict)
    pending_approval: PendingApproval | None = None
    output: dict[str, Any] | None = None
