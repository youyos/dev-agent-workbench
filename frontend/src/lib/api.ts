import type { MentionKind, MentionRef, RunEvent } from "../types";

export interface HealthResponse {
  status: string;
  provider: string;
  model: string;
  qwen_configured?: boolean;
  features?: {
    unpublished_homework_scenario?: boolean;
    scenario_fixtures?: boolean;
  };
}

export async function searchMentions(query = "", kind?: MentionKind): Promise<MentionRef[]> {
  const params = new URLSearchParams();
  if (query) params.set("q", query);
  if (kind) params.set("kind", kind);
  const response = await fetch(`/api/mentions?${params}`);
  if (!response.ok) throw new Error("无法加载 @ 候选项");
  const body = await response.json();
  return body.items;
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch("/api/health");
  if (!response.ok) throw new Error("Agent 服务不可用");
  return response.json();
}

export async function getSkills(): Promise<any[]> {
  const response = await fetch("/api/skills");
  if (!response.ok) throw new Error("无法加载 Skill 列表");
  return (await response.json()).items;
}

export async function importSkill(file: File): Promise<any> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/skills/import", { method: "POST", body: form });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail ?? "Skill 导入失败");
  return body;
}

export async function getMcpServers(): Promise<any[]> {
  const response = await fetch("/api/mcp-servers");
  if (!response.ok) throw new Error("无法加载 MCP 列表");
  return (await response.json()).items;
}

export async function addMcpServer(input: {
  id: string;
  name: string;
  url: string;
  transport: "streamable_http" | "sse";
  headers: Record<string, string>;
}): Promise<any> {
  const response = await fetch("/api/mcp-servers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail ?? "MCP 连接失败");
  return body;
}

export async function removeMcpServer(serverId: string): Promise<any> {
  const response = await fetch(`/api/mcp-servers/${encodeURIComponent(serverId)}`, {
    method: "DELETE",
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail ?? "MCP 移除失败");
  return body;
}

export async function streamRun(
  message: string,
  mentions: MentionRef[],
  history: Array<{ role: "user" | "assistant"; content: string }>,
  onEvent: (event: RunEvent) => void,
  signal?: AbortSignal,
  sessionId?: string,
): Promise<void> {
  const response = await fetch("/api/runs/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, mentions, history, session_id: sessionId || null }),
    signal,
  });
  await readEventStream(response, onEvent);
}

export async function readEventStream(response: Response, onEvent: (event: RunEvent) => void) {
  if (!response.ok || !response.body) {
    throw new Error(`Agent 请求失败：${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const dataLine = block.split("\n").find((line) => line.startsWith("data: "));
      if (!dataLine) continue;
      onEvent(JSON.parse(dataLine.slice(6)) as RunEvent);
    }
    if (done) break;
  }
}

export async function getSession(id: string): Promise<any> {
  const response = await fetch(`/api/sessions/${encodeURIComponent(id)}`);
  if (!response.ok) throw new Error("无法恢复会话");
  return response.json();
}

export async function getRun(id: string): Promise<any> {
  const response = await fetch(`/api/runs/${encodeURIComponent(id)}`);
  if (!response.ok) throw new Error("无法加载运行状态");
  return response.json();
}

export async function getRunEvents(id: string): Promise<RunEvent[]> {
  const response = await fetch(`/api/runs/${encodeURIComponent(id)}/events`);
  if (!response.ok) throw new Error("无法加载执行记录");
  return (await response.json()).items;
}

export async function cancelRun(id: string) {
  const response = await fetch(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
  if (!response.ok) throw new Error("取消失败");
}

export async function approveRun(id: string, approvalId: string, approved: boolean,
                                 onEvent: (event: RunEvent) => void, signal?: AbortSignal) {
  const response = await fetch(`/api/runs/${encodeURIComponent(id)}/approval`, {
    method: "POST", headers: { "Content-Type": "application/json" }, signal,
    body: JSON.stringify({ approval_id: approvalId, approved }),
  });
  await readEventStream(response, onEvent);
}
