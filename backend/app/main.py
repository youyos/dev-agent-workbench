from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .catalog import ContextResolver, build_default_registry, register_skill
from .config import get_settings
from .mcp_manager import McpConnectionError, McpManager
from .models import AgentRunRequest, McpServerConfig, MentionKind, MentionRef, RunEvent
from .pipeline import AgentPipeline
from .providers import DemoModelProvider, OpenAIModelProvider, QwenModelProvider
from .runtime_extensions import OutputRegistry, PolicyRegistry
from .runtime_store import SQLiteRuntimeStore
from .scenario_extension import register_homework_extension
from .scenario_fixture import register_unpublished_homework_fixture
from .skill_store import MAX_SKILL_ARCHIVE_BYTES, SkillImportError, SkillStore

settings = get_settings()
logger = logging.getLogger(__name__)
data_dir = Path(settings.agent_data_dir).resolve()
skill_store = SkillStore(data_dir / "skills")
registry, mention_catalog = build_default_registry(skill_store.root)
if settings.enable_unpublished_homework_scenario and settings.enable_scenario_fixtures:
    register_unpublished_homework_fixture(registry)
resolver = ContextResolver(mention_catalog)
mcp_manager = McpManager(data_dir / "mcp_servers.json")

if settings.agent_provider == "qwen" and settings.dashscope_api_key:
    provider = QwenModelProvider(
        api_key=settings.dashscope_api_key,
        model=settings.qwen_model,
        base_url=settings.qwen_base_url,
    )
    provider_name = "qwen"
    provider_model = settings.qwen_model
elif settings.agent_provider == "openai" and settings.openai_api_key:
    provider = OpenAIModelProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        base_url=settings.openai_base_url,
    )
    provider_name = "openai"
    provider_model = settings.openai_model
else:
    provider = DemoModelProvider()
    provider_name = "demo"
    provider_model = "deterministic-demo"

runtime_store = SQLiteRuntimeStore(data_dir / "runtime.db")
policies = PolicyRegistry()
outputs = OutputRegistry()
if settings.enable_unpublished_homework_scenario:
    register_homework_extension(policies, outputs)

pipeline = AgentPipeline(
    registry=registry,
    resolver=resolver,
    provider=provider,
    policies=policies,
    outputs=outputs,
    store=runtime_store,
    max_steps=settings.agent_max_steps,
    operation_timeout=settings.agent_operation_timeout,
)


def register_mcp_capabilities(server_id: str) -> None:
    registry.remove_by_metadata("mcp_server_id", server_id)
    mention_catalog.remove_by_metadata("mcp_server_id", server_id)
    for descriptor, handler in mcp_manager.build_capabilities(server_id):
        registry.upsert(descriptor, handler)
        mention_catalog.add(
            MentionRef(
                kind=MentionKind.MCP,
                id=descriptor.id,
                label=descriptor.name,
                metadata={
                    "description": descriptor.description,
                    **descriptor.metadata,
                },
            )
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    runtime_store.recover_interrupted()
    for server in mcp_manager.list_servers():
        if not server["enabled"]:
            continue
        try:
            await mcp_manager.refresh(server["id"])
            register_mcp_capabilities(server["id"])
        except Exception as exc:  # noqa: BLE001 - one unavailable MCP must not block startup
            logger.warning("Unable to reconnect MCP server %s: %s", server["id"], exc)
    yield


app = FastAPI(
    title="Dev Agent Workbench API",
    version="0.1.0",
    description="Context Resolver → Intent → Capability Router → Planner → Executor",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "provider": provider_name,
        "model": provider_model,
        "qwen_configured": bool(settings.dashscope_api_key),
        "features": {
            "unpublished_homework_scenario": settings.enable_unpublished_homework_scenario,
            "scenario_fixtures": settings.enable_scenario_fixtures,
        },
    }


@app.get("/api/capabilities")
async def capabilities() -> dict:
    return {
        "items": [item.model_dump(mode="json") for item in registry.list()],
        "mention_kinds": [item.value for item in MentionKind],
    }


@app.get("/api/skills")
async def skills() -> dict:
    return {
        "items": [
            item.model_dump(mode="json") for item in registry.list() if item.kind.value == "skill"
        ]
    }


@app.post("/api/skills/import")
async def import_skill(file: Annotated[UploadFile, File()]) -> dict:
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 .zip 格式的 Skill")
    archive = await file.read(MAX_SKILL_ARCHIVE_BYTES + 1)
    try:
        loaded, events = skill_store.import_zip(archive)
    except SkillImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    register_skill(registry, mention_catalog, loaded)
    return {"skill": loaded.descriptor.model_dump(mode="json"), "events": events}


@app.get("/api/mcp-servers")
async def mcp_servers() -> dict:
    return {"items": mcp_manager.list_servers()}


@app.post("/api/mcp-servers")
async def add_mcp_server(config: McpServerConfig) -> dict:
    try:
        tools, events = await mcp_manager.add_and_discover(config)
    except McpConnectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    register_mcp_capabilities(config.id)
    return {
        "server": next(item for item in mcp_manager.list_servers() if item["id"] == config.id),
        "tools": [item.model_dump(mode="json") for item in tools],
        "events": events,
    }


@app.post("/api/mcp-servers/{server_id}/refresh")
async def refresh_mcp_server(server_id: str) -> dict:
    try:
        tools, events = await mcp_manager.refresh(server_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except McpConnectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    register_mcp_capabilities(server_id)
    return {"tools": [item.model_dump(mode="json") for item in tools], "events": events}


@app.delete("/api/mcp-servers/{server_id}")
async def remove_mcp_server(server_id: str) -> dict:
    try:
        removed = await mcp_manager.remove(server_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    registry.remove_by_metadata("mcp_server_id", server_id)
    mention_catalog.remove_by_metadata("mcp_server_id", server_id)
    return {
        "server": removed,
        "events": [
            {"stage": "mcp.tools_unregistered", "message": "已注销该 MCP 的全部工具"},
            {"stage": "mcp.removed", "message": f"已移除 {removed['name']}"},
        ],
    }


@app.get("/api/mentions")
async def mentions(
    q: Annotated[str, Query(max_length=100)] = "",
    kind: Annotated[str | None, Query(max_length=80)] = None,
) -> dict:
    return {"items": [item.model_dump(mode="json") for item in mention_catalog.search(q, kind)]}


@app.post("/api/runs/stream")
async def stream_run(request: AgentRunRequest) -> StreamingResponse:
    return event_response(pipeline.run(request))


def event_response(events) -> StreamingResponse:
    async def generate():
        try:
            async for event in events:
                payload = event.model_dump_json()
                yield f"event: {event.type}\ndata: {payload}\n\n"
        except Exception as exc:  # noqa: BLE001 - normalize pipeline failures into SSE
            payload = RunEvent(
                run_id="request-error", sequence=0, type="run.error", data={"message": str(exc)}
            ).model_dump_json()
            yield f"event: run.error\ndata: {payload}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/sessions")
async def create_session() -> dict:
    return {"id": runtime_store.create_session()}


@app.get("/api/sessions")
async def sessions() -> dict:
    return {"items": runtime_store.list_sessions()}


@app.get("/api/sessions/{session_id}")
async def session_detail(session_id: str) -> dict:
    try:
        return {
            "id": session_id,
            "messages": runtime_store.messages(session_id),
            "runs": runtime_store.runs(session_id),
        }
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/runs/{run_id}")
async def run_detail(run_id: str) -> dict:
    try:
        state = runtime_store.load(run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "run_id": state.run_id,
        "session_id": state.session_id,
        "status": state.status,
        "cursor": state.cursor,
        "plan": state.plan,
        "output": state.output,
        "pending_approval": state.pending_approval,
    }


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, after: Annotated[int, Query(ge=0)] = 0) -> dict:
    try:
        return {"items": runtime_store.events(run_id, after)}
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict:
    try:
        pipeline.cancel(run_id)
        return {"status": "cancellation_requested"}
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


class ApprovalDecision(BaseModel):
    approval_id: str
    approved: bool


@app.post("/api/runs/{run_id}/approval")
async def resolve_approval(run_id: str, decision: ApprovalDecision) -> StreamingResponse:
    try:
        state = runtime_store.load(run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    if state.status != "awaiting_approval" or not state.pending_approval:
        raise HTTPException(409, "运行没有待处理审批")
    return event_response(pipeline.resume(run_id, decision.approval_id, decision.approved))
