import json

import pytest

from app.mcp_manager import McpManager


def test_mcp_server_list_redacts_header_values(tmp_path):
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "id": "private-docs",
                        "name": "Private Docs",
                        "url": "https://example.com/mcp",
                        "transport": "streamable_http",
                        "headers": {"Authorization": "Bearer secret", "X-Tenant": "acme"},
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    manager = McpManager(config_path)
    server = manager.list_servers()[0]

    assert "headers" not in server
    assert server["header_names"] == ["Authorization", "X-Tenant"]
    assert "secret" not in json.dumps(server)


@pytest.mark.asyncio
async def test_remove_mcp_server_updates_persisted_config(tmp_path):
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "id": "demo",
                        "name": "Demo",
                        "url": "https://example.com/mcp",
                        "transport": "streamable_http",
                        "headers": {},
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    manager = McpManager(config_path)

    removed = await manager.remove("demo")

    assert removed == {"id": "demo", "name": "Demo"}
    assert manager.list_servers() == []
    assert json.loads(config_path.read_text(encoding="utf-8")) == {"servers": []}
