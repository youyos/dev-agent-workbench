from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from .models import Capability, CapabilityKind, McpServerConfig, McpToolDescriptor


class McpConnectionError(RuntimeError):
    pass


class McpManager:
    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path
        self._configs: dict[str, McpServerConfig] = {}
        self._tools: dict[str, list[McpToolDescriptor]] = {}
        self._lock = asyncio.Lock()
        self._load()

    def list_servers(self) -> list[dict[str, Any]]:
        return [
            {
                "id": config.id,
                "name": config.name,
                "url": config.url,
                "transport": config.transport,
                "enabled": config.enabled,
                "header_names": sorted(config.headers),
                "approval_policy": config.approval_policy,
                "allowed_tools": config.allowed_tools,
                "tool_count": len(self._tools.get(config.id, [])),
            }
            for config in self._configs.values()
        ]

    def get_tools(self, server_id: str) -> list[McpToolDescriptor]:
        return list(self._tools.get(server_id, []))

    async def add_and_discover(
        self,
        config: McpServerConfig,
    ) -> tuple[list[McpToolDescriptor], list[dict[str, str]]]:
        events = [{"stage": "mcp.connecting", "message": f"正在连接 {config.name}"}]
        tools = await self.discover(config)
        events.append({"stage": "mcp.tools_discovered", "message": f"发现 {len(tools)} 个工具"})
        async with self._lock:
            self._configs[config.id] = config
            self._tools[config.id] = tools
            self._save()
        events.append({"stage": "mcp.registered", "message": f"MCP {config.name} 已注册"})
        return tools, events

    async def refresh(self, server_id: str) -> tuple[list[McpToolDescriptor], list[dict[str, str]]]:
        config = self._configs.get(server_id)
        if config is None:
            raise KeyError(f"MCP 不存在：{server_id}")
        return await self.add_and_discover(config)

    async def remove(self, server_id: str) -> dict[str, Any]:
        async with self._lock:
            config = self._configs.pop(server_id, None)
            self._tools.pop(server_id, None)
            if config is None:
                raise KeyError(f"MCP 不存在：{server_id}")
            self._save()
        return {"id": config.id, "name": config.name}

    async def discover(self, config: McpServerConfig) -> list[McpToolDescriptor]:
        try:
            async with self._session(config) as session:
                response = await asyncio.wait_for(session.list_tools(), timeout=20)
        except Exception as exc:
            raise McpConnectionError(f"连接 MCP 失败：{exc}") from exc
        return [
            McpToolDescriptor(
                server_id=config.id,
                name=tool.name,
                title=str(getattr(tool, "title", "") or tool.name),
                description=str(tool.description or ""),
                input_schema=tool.inputSchema or {"type": "object", "properties": {}},
                read_only=bool(getattr(getattr(tool, "annotations", None), "readOnlyHint", False)),
            )
            for tool in response.tools
        ]

    async def call_tool(self, server_id: str, tool_name: str, arguments: dict[str, Any]) -> dict:
        config = self._configs.get(server_id)
        if config is None:
            raise KeyError(f"MCP 不存在：{server_id}")
        if not config.enabled:
            raise PermissionError("MCP 已停用")
        if config.allowed_tools and tool_name not in config.allowed_tools:
            raise PermissionError("工具不在 MCP 允许列表中")
        try:
            async with self._session(config) as session:
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments),
                    timeout=60,
                )
        except Exception as exc:
            raise McpConnectionError(f"MCP 工具调用失败：{exc}") from exc
        content = []
        for item in result.content:
            if hasattr(item, "text"):
                content.append(item.text)
            else:
                content.append(str(item))
        return {
            "server_id": server_id,
            "tool": tool_name,
            "content": "\n".join(content),
            "is_error": bool(getattr(result, "isError", False)),
        }

    def build_capabilities(self, server_id: str) -> list[tuple[Capability, Any]]:
        capabilities = []
        config = self._configs[server_id]
        if not config.enabled:
            return []
        for tool in self.get_tools(server_id):
            if config.allowed_tools and tool.name not in config.allowed_tools:
                continue
            capability_id = f"mcp-{server_id}-{_slug(tool.name)}"[:180]

            async def handler(payload: dict, sid=server_id, name=tool.name):
                return await self.call_tool(sid, name, payload.get("arguments") or {})

            descriptor = Capability(
                id=capability_id,
                name=tool.title or tool.name,
                description=tool.description or f"MCP tool {tool.name}",
                kind=CapabilityKind.MCP,
                triggers=_terms(f"{tool.name} {tool.title} {tool.description}"),
                permissions=["external"] if tool.read_only else ["external", "write"],
                requires_approval=config.approval_policy == "always" or not tool.read_only,
                input_schema=tool.input_schema,
                metadata={
                    "mcp_server_id": server_id,
                    "mcp_tool_name": tool.name,
                    "connection_hash": hashlib.sha256(
                        config.model_dump_json().encode()
                    ).hexdigest(),
                },
            )
            capabilities.append((descriptor, handler))
        return capabilities

    @asynccontextmanager
    async def _session(self, config: McpServerConfig):
        headers = dict(config.headers)
        if config.transport == "sse":
            async with (
                sse_client(config.url, headers=headers or None) as (read, write),
                ClientSession(read, write) as session,
            ):
                await asyncio.wait_for(session.initialize(), timeout=15)
                yield session
            return

        timeout = httpx.Timeout(connect=15, read=300, write=60, pool=30)
        async with (
            httpx.AsyncClient(headers=headers, timeout=timeout) as http_client,
            streamable_http_client(
                config.url,
                http_client=http_client,
            ) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await asyncio.wait_for(session.initialize(), timeout=15)
            yield session

    def _load(self) -> None:
        if not self._config_path.exists():
            return
        raw = json.loads(self._config_path.read_text(encoding="utf-8"))
        self._configs = {
            item["id"]: McpServerConfig.model_validate(item) for item in raw.get("servers", [])
        }

    def _save(self) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(
                {"servers": [item.model_dump() for item in self._configs.values()]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.chmod(self._config_path, 0o600)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower().replace("_", "-")).strip("-")


def _terms(value: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"[a-zA-Z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", value)))[:16]
