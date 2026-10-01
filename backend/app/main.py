from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .catalog import ContextResolver, build_default_registry, register_skill
from .config import get_settings
from .mcp_manager import McpConnectionError, McpManager
from .models import AgentRunRequest, McpServerConfig, MentionKind, MentionRef
from .pipeline import AgentPipeline
from .providers import DemoModelProvider, OpenAIModelProvider, QwenModelProvider
from .scenario_fixture import register_unpublished_homework_fixture
from .scenario_policy import ScenarioPolicyRegistry
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

pipeline = AgentPipeline(
    registry=registry,
    resolver=resolver,
    provider=provider,
    scenario_registry=(
        ScenarioPolicyRegistry()
        if settings.enable_unpublished_homework_scenario
        else None
    ),
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
            item.model_dump(mode="json")
            for item in registry.list()
            if item.kind.value == "skill"
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
    kind: Annotated[MentionKind | None, Query()] = None,
) -> dict:
    return {
        "items": [item.model_dump(mode="json") for item in mention_catalog.search(q, kind)]
    }


@app.post("/api/runs/stream")
async def stream_run(request: AgentRunRequest) -> StreamingResponse:
    async def generate():
        try:
            async for event in pipeline.run(request):
                payload = event.model_dump_json()
                yield f"event: {event.type}\ndata: {payload}\n\n"
        except Exception as exc:  # noqa: BLE001 - normalize pipeline failures into SSE
            payload = json.dumps(
                {"type": "run.error", "data": {"message": str(exc)}},
                ensure_ascii=False,
            )
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
