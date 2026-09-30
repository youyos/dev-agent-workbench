import {
  Check,
  ChevronRight,
  CloudCog,
  KeyRound,
  LoaderCircle,
  PackageOpen,
  PlugZap,
  ServerCog,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";

import { addMcpServer, getMcpServers, getSkills, importSkill, removeMcpServer } from "../lib/api";

type Tab = "skills" | "mcp" | "model";

interface Props {
  open: boolean;
  onClose: () => void;
  health: { provider: string; model: string; qwen_configured?: boolean } | null;
}

export function ExtensionDrawer({ open, onClose, health }: Props) {
  const [tab, setTab] = useState<Tab>("skills");
  const [skills, setSkills] = useState<any[]>([]);
  const [servers, setServers] = useState<any[]>([]);
  const [events, setEvents] = useState<Array<{ stage: string; message: string }>>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function reload() {
    Promise.all([getSkills(), getMcpServers()])
      .then(([skillItems, serverItems]) => {
        setSkills(skillItems);
        setServers(serverItems);
      })
      .catch((reason) => setError(String(reason)));
  }

  useEffect(() => {
    if (open) reload();
  }, [open]);

  async function upload(file?: File) {
    if (!file) return;
    setBusy(true);
    setError("");
    setEvents([{ stage: "upload.started", message: `正在上传 ${file.name}` }]);
    try {
      const result = await importSkill(file);
      setEvents(result.events);
      reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function createMcp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const name = String(form.get("name") ?? "");
    const id = String(form.get("id") ?? "");
    const url = String(form.get("url") ?? "");
    const token = String(form.get("token") ?? "");
    const transport = String(form.get("transport")) as "streamable_http" | "sse";
    setBusy(true);
    setError("");
    setEvents([{ stage: "mcp.connecting", message: `正在连接 ${name}` }]);
    try {
      const result = await addMcpServer({
        id,
        name,
        url,
        transport,
        headers: token ? { Authorization: token } : {},
      });
      setEvents(result.events);
      reload();
      formElement.reset();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function removeServer(server: any) {
    if (!window.confirm(`确认移除 MCP「${server.name}」及其 ${server.tool_count} 个工具？`)) return;
    setBusy(true);
    setError("");
    setEvents([{ stage: "mcp.removing", message: `正在移除 ${server.name}` }]);
    try {
      const result = await removeMcpServer(server.id);
      setEvents(result.events);
      reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;
  return (
    <div className="drawer-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="extension-drawer">
        <header>
          <div><span className="eyebrow">RUNTIME EXTENSIONS</span><h2>扩展管理</h2></div>
          <button className="icon-button" onClick={onClose}><X size={17} /></button>
        </header>
        <nav className="drawer-tabs">
          <button className={tab === "skills" ? "active" : ""} onClick={() => setTab("skills")}><PackageOpen size={14} /> Skills</button>
          <button className={tab === "mcp" ? "active" : ""} onClick={() => setTab("mcp")}><PlugZap size={14} /> MCP</button>
          <button className={tab === "model" ? "active" : ""} onClick={() => setTab("model")}><Sparkles size={14} /> 千问</button>
        </nav>

        <div className="drawer-content">
          {tab === "skills" && (
            <>
              <section className="extension-intro"><h3>外部 Skill</h3><p>上传包含一个 `SKILL.md` 的 ZIP。导入后会立即加入 @ 菜单和能力路由。</p></section>
              <input ref={inputRef} hidden type="file" accept=".zip,application/zip" onChange={(e) => upload(e.target.files?.[0])} />
              <button className="primary-wide" disabled={busy} onClick={() => inputRef.current?.click()}>
                {busy ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />} 导入 Skill ZIP
              </button>
              <div className="extension-list">
                {skills.map((skill) => (
                  <article key={skill.id}>
                    <span className="extension-logo"><Sparkles size={15} /></span>
                    <div><strong>{skill.name}</strong><small>{skill.description}</small><em>{skill.metadata?.source ?? "built-in"}</em></div>
                    <ChevronRight size={14} />
                  </article>
                ))}
              </div>
            </>
          )}

          {tab === "mcp" && (
            <>
              <section className="extension-intro"><h3>MCP Server</h3><p>连接后会立即发现工具，并把每个工具注册成可路由的 Capability。</p></section>
              <form className="mcp-form" onSubmit={createMcp}>
                <div className="field-row"><label>名称<input name="name" required placeholder="OpenAI Docs" /></label><label>ID<input name="id" pattern="[a-z0-9-]+" required placeholder="openai-docs" /></label></div>
                <label>Server URL<input name="url" required type="url" placeholder="https://example.com/mcp" /></label>
                <div className="field-row"><label>传输<select name="transport"><option value="streamable_http">Streamable HTTP</option><option value="sse">SSE</option></select></label><label>Authorization<input name="token" type="password" placeholder="Bearer ...（可选）" /></label></div>
                <button className="primary-wide" disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <PlugZap size={15} />} 连接并发现工具</button>
              </form>
              <div className="extension-list">
                {servers.map((server) => (
                  <article key={server.id}>
                    <span className="extension-logo server"><ServerCog size={15} /></span>
                    <div><strong>{server.name}</strong><small>{server.url}</small><em>{server.tool_count} tools · {server.transport}</em></div>
                    <span className="connected"><Check size={11} /> 已连接</span>
                    <button
                      className="remove-extension"
                      disabled={busy}
                      onClick={() => removeServer(server)}
                      title="移除 MCP"
                      type="button"
                    ><Trash2 size={13} /></button>
                  </article>
                ))}
              </div>
            </>
          )}

          {tab === "model" && (
            <>
              <section className="model-card">
                <span className="extension-logo qwen"><CloudCog size={18} /></span>
                <div><span className="eyebrow">ACTIVE PROVIDER</span><h3>{health?.provider === "qwen" ? "通义千问" : "Demo Provider"}</h3><p>{health?.model}</p></div>
                <span className={health?.qwen_configured ? "connected" : "not-configured"}>{health?.qwen_configured ? "已配置" : "未配置"}</span>
              </section>
              <section className="env-guide">
                <KeyRound size={17} /><div><h4>服务端环境变量</h4><pre>DASHSCOPE_API_KEY=sk-...{"\n"}QWEN_MODEL=qwen-plus{"\n"}AGENT_PROVIDER=qwen</pre><p>密钥只配置在后端，不会返回浏览器。</p></div>
              </section>
            </>
          )}

          {(events.length > 0 || error) && (
            <section className="import-trace">
              <span className="eyebrow">LIVE PROCESS</span>
              {events.map((item, index) => <div key={`${item.stage}-${index}`}><Check size={12} /><span><strong>{item.stage}</strong>{item.message}</span></div>)}
              {error && <p className="drawer-error">{error}</p>}
            </section>
          )}
        </div>
      </aside>
    </div>
  );
}
