import { Bot, Braces, Circle, Command, Github, Layers3, MessageSquarePlus, PlugZap, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

import { MentionComposer } from "./components/MentionComposer";
import { RunInspector } from "./components/RunInspector";
import { ExtensionDrawer } from "./components/ExtensionDrawer";
import { RecommendationCard } from "./components/RecommendationCard";
import { approveRun, cancelRun, getHealth, getRun, getRunEvents, getSession, streamRun } from "./lib/api";
import type { HealthResponse } from "./lib/api";
import { createId } from "./lib/id";
import type { ChatEntry, MentionRef, RunEvent } from "./types";

interface StarterPrompt {
  title: string;
  prompt: string;
  mentions: MentionRef[];
  feature?: "unpublished_homework_scenario";
}

const starterPrompts: StarterPrompt[] = [
  {
    title: "诊断支付失败",
    prompt: "帮我定位支付为什么失败，并给出修改建议和验证方案",
    mentions: [
      { kind: "skill", id: "debug-code", label: "支付故障诊断" },
      { kind: "file", id: "checkout.py", label: "checkout.py" },
      { kind: "resource", id: "order-1024", label: "订单 #1024" },
    ],
  },
  {
    title: "多 Skill 作业卡片",
    prompt: "查询未发布的作业列表",
    mentions: [],
    feature: "unpublished_homework_scenario",
  },
  {
    title: "分析课程风险",
    prompt: "分析这门课程目前的学习风险，并给出可以量化验证的干预建议",
    mentions: [
      { kind: "skill", id: "course-analysis", label: "教学数据分析" },
      { kind: "resource", id: "python-course", label: "Python 入门课程" },
    ],
  },
];

const CONVERSATION_STORAGE_KEY = "agent-flow-lab:conversation:v1";
const SESSION_STORAGE_KEY = "agent-flow-lab:session:v1";

export default function App() {
  const [messages, setMessages] = useState<ChatEntry[]>(loadConversation);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [sessionId, setSessionId] = useState(() => localStorage.getItem(SESSION_STORAGE_KEY) || "");
  const [runId, setRunId] = useState("");
  const [pending, setPending] = useState<any>(null);
  const [notice, setNotice] = useState("");
  const controller = useRef<AbortController | null>(null);
  const [provider, setProvider] = useState("连接中");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [extensionsOpen, setExtensionsOpen] = useState(false);
  const conversationRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let disposed = false;
    async function restore() {
      if (!sessionId) { setRestoring(false); return; }
      try {
        const session = await getSession(sessionId);
        if (disposed) return;
        const restored = session.messages.map((item: any) => ({
          id: `${item.run_id}:${item.role}`, role: item.role, content: item.content,
          recommendation: item.output?.type === "recommendation" ? item.output.content : undefined,
        }));
        setMessages(restored);
        const latest = session.runs[session.runs.length - 1];
        if (latest) {
          const [state, trace] = await Promise.all([getRun(latest.id), getRunEvents(latest.id)]);
          if (disposed) return;
          setRunId(latest.id);
          setEvents(trace);
          if (state.pending_approval) {
            setMessages([...restored, { id: `${latest.id}:assistant`, role: "assistant", content: "等待确认工具调用。" }]);
            setPending({ ...state.pending_approval, assistantId: `${latest.id}:assistant` });
          }
        }
      } catch {
        if (!disposed) {
          setNotice("服务端会话暂时无法恢复，请重试或新建对话。");
        }
      } finally {
        if (!disposed) setRestoring(false);
      }
    }
    void restore();
    return () => { disposed = true; };
  }, []);

  useEffect(() => {
    getHealth()
      .then((nextHealth) => {
        setHealth(nextHealth);
        setProvider(nextHealth.provider === "demo" ? "Demo Provider" : nextHealth.model);
      })
      .catch(() => setProvider("服务离线"));
  }, []);

  useEffect(() => {
    const conversation = conversationRef.current;
    if (!conversation) return;
    conversation.scrollTo({ top: conversation.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    try {
      localStorage.setItem(CONVERSATION_STORAGE_KEY, JSON.stringify(messages.slice(-50)));
    } catch {
      setNotice("浏览器缓存空间不足，会话仍保存在服务端。");
    }
  }, [messages]);

  async function submit(message: string, mentions: MentionRef[]) {
    if (running || pending || restoring) return;
    const history = messages
      .filter((item) => item.content.trim())
      .slice(-20)
      .map((item) => ({
        role: item.role,
        content: item.role === "user" && item.mentions?.length
          ? `${item.mentions.map((mention) => `@${mention.label}`).join(" ")}\n${item.content}`.slice(0, 20_000)
          : item.content.slice(0, 20_000),
      }));
    const userEntry: ChatEntry = {
      id: createId(),
      role: "user",
      content: message,
      mentions,
    };
    const assistantId = createId();
    setMessages((items) => [
      ...items,
      userEntry,
      { id: assistantId, role: "assistant", content: "" },
    ]);
    setEvents([]);
    setRunId("");
    setNotice("");
    setRunning(true);
    controller.current = new AbortController();
    try {
      await streamRun(message, mentions, history, (event) => {
        setEvents((items) => [...items, event]);
        if (event.type === "run.started") {
          setRunId(event.run_id);
          const nextSession = String(event.data.session_id);
          setSessionId(nextSession);
          localStorage.setItem(SESSION_STORAGE_KEY, nextSession);
        }
        if (event.type === "approval.required") {
          setPending({ ...event.data, assistantId });
          setMessages((items) => items.map((item) => item.id === assistantId
            ? { ...item, content: "等待确认工具调用。" } : item));
        }
        if (event.type === "message.delta") {
          setMessages((items) =>
            items.map((item) =>
              item.id === assistantId
                ? { ...item, content: item.content + String(event.data.delta ?? "") }
                : item,
            ),
          );
        }
        if (event.type === "run.needs_input") {
          setMessages((items) =>
            items.map((item) =>
              item.id === assistantId
                ? { ...item, content: String(event.data.question ?? "请补充更多信息。") }
                : item,
            ),
          );
        }
        if (event.type === "message.completed" && event.data.content) {
          setMessages((items) =>
            items.map((item) =>
              item.id === assistantId && !item.content
                ? { ...item, content: String(event.data.content) }
                : item,
            ),
          );
        }
        if (event.type === "recommendation" && event.data.content) {
          setMessages((items) =>
            items.map((item) =>
              item.id === assistantId
                ? { ...item, recommendation: event.data.content }
                : item,
            ),
          );
        }
        if (event.type === "run.error") {
          throw new Error(String(event.data.message ?? "运行失败"));
        }
      }, controller.current.signal, sessionId);
    } catch (error) {
      setMessages((items) =>
        items.map((item) =>
          item.id === assistantId
            ? { ...item, content: error instanceof DOMException && error.name === "AbortError"
              ? "运行已停止。" : `运行失败：${error instanceof Error ? error.message : String(error)}` }
            : item,
        ),
      );
    } finally {
      setRunning(false);
    }
  }

  async function resolveApproval(approved: boolean) {
    if (!pending || running) return;
    const approval = pending;
    setRunning(true);
    setNotice("");
    controller.current = new AbortController();
    try {
      await approveRun(runId, approval.id, approved, (event) => {
        setEvents((items) => [...items, event]);
        if (event.type === "approval.resolved") {
          setPending(null);
          setMessages((items) => items.map((item) => item.id === approval.assistantId
            ? { ...item, content: "" } : item));
        }
        if (event.type === "approval.required") setPending({ ...event.data, assistantId: approval.assistantId });
        if (event.type === "message.delta") setMessages((items) => items.map((item) => item.id === approval.assistantId
          ? { ...item, content: item.content + String(event.data.delta) } : item));
        if (event.type === "message.completed" || event.type === "run.needs_input") {
          setMessages((items) => items.map((item) => item.id === approval.assistantId
            ? { ...item, content: String(event.data.content || event.data.question || "") } : item));
        }
        if (event.type === "recommendation") setMessages((items) => items.map((item) => item.id === approval.assistantId
          ? { ...item, recommendation: event.data.content } : item));
        if (event.type === "run.error") throw new Error(String(event.data.message));
      }, controller.current.signal);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
      setMessages((items) => items.map((item) => item.id === approval.assistantId
        ? { ...item, content: error instanceof DOMException && error.name === "AbortError"
          ? "运行已停止。" : `恢复运行失败：${error instanceof Error ? error.message : String(error)}` }
        : item));
    } finally {
      setRunning(false);
    }
  }

  async function stopRun() {
    try {
      if (runId) await cancelRun(runId);
      controller.current?.abort();
      if (pending) {
        setMessages((items) => items.map((item) => item.id === pending.assistantId
          ? { ...item, content: "运行已取消。" } : item));
      }
      setPending(null);
      if (runId) setEvents(await getRunEvents(runId));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    }
  }

  function newConversation() {
    setMessages([]);
    setEvents([]);
    localStorage.removeItem(CONVERSATION_STORAGE_KEY);
    localStorage.removeItem(SESSION_STORAGE_KEY);
    setSessionId("");
    setRunId("");
    setNotice("");
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark"><Sparkles size={17} /></span>
          <div>
            <strong>Agent Flow Lab</strong>
            <span>Composable capability runtime</span>
          </div>
        </div>
        <nav className="top-actions">
          <span className="provider-badge"><Circle size={7} fill="currentColor" /> {provider}</span>
          <button className="top-action-button" onClick={() => setExtensionsOpen(true)}><PlugZap size={15} /> 扩展</button>
          <a href="http://127.0.0.1:8421/docs" target="_blank" rel="noreferrer">
            <Braces size={15} /> API
          </a>
          <span className="shortcut"><Command size={14} /> K</span>
        </nav>
      </header>

      <main className="workspace">
        <section className="chat-panel">
          <div className="chat-header">
            <div>
              <span className="eyebrow">PLAYGROUND</span>
              <h1>把能力串成真正的 Agent</h1>
            </div>
            <div className="chat-header-actions">
              {messages.length > 0 && (
                <button className="new-chat-button" disabled={running || Boolean(pending) || restoring} onClick={newConversation}>
                  <MessageSquarePlus size={13} /> 新对话
                </button>
              )}
              <div className="pipeline-mini">
                <span>Context</span><i />
                <span>Intent</span><i />
                <span>Route</span><i />
                <span>Execute</span>
              </div>
            </div>
          </div>

          <div className="conversation" ref={conversationRef}>
            {messages.length === 0 ? (
              <Welcome
                onStart={submit}
                scenarioEnabled={Boolean(health?.features?.unpublished_homework_scenario)}
              />
            ) : (
              messages.map((message) => <Message entry={message} key={message.id} running={running} />)
            )}
            <div />
          </div>

          <div className="composer-wrap">
            {notice && <p className="runtime-notice" role="alert">{notice}</p>}
            {(running || pending) && <button className="new-chat-button" onClick={stopRun}>停止当前运行</button>}
            {pending && <div className="runtime-approval">
              <strong>确认调用：{pending.name || pending.capability_id}</strong>
              <p>{pending.reason}</p>
              <pre>{JSON.stringify(pending.arguments, null, 2)}</pre>
              <button disabled={running} onClick={() => resolveApproval(true)}>批准本次调用</button>
              <button disabled={running} onClick={() => resolveApproval(false)}>拒绝</button>
            </div>}
            <MentionComposer disabled={running || Boolean(pending) || restoring} onSubmit={submit} />
          </div>
        </section>

        <RunInspector events={events} running={running} />
      </main>
      <ExtensionDrawer open={extensionsOpen} onClose={() => setExtensionsOpen(false)} health={health} />
    </div>
  );
}

function loadConversation(): ChatEntry[] {
  try {
    const raw = localStorage.getItem(CONVERSATION_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item) => item && ["user", "assistant"].includes(item.role) && typeof item.content === "string")
      .slice(-50);
  } catch {
    return [];
  }
}

function Welcome({
  onStart,
  scenarioEnabled,
}: {
  onStart: (message: string, mentions: MentionRef[]) => void;
  scenarioEnabled: boolean;
}) {
  const visiblePrompts = starterPrompts.filter(
    (item) => !item.feature || scenarioEnabled,
  );
  return (
    <div className="welcome">
      <div className="orb"><Bot size={28} /></div>
      <span className="eyebrow">STRUCTURED, TRACEABLE, EXTENSIBLE</span>
      <h2>不是把一堆工具塞给模型，<br />而是先理解，再路由，再执行。</h2>
      <p>
        输入 <kbd>@</kbd> 选择 Skill、文件、工具或业务对象。每个决策都会显示在右侧运行轨迹中。
      </p>
      <div className="starter-grid">
        {visiblePrompts.map((item, index) => (
          <button key={item.title} onClick={() => onStart(item.prompt, item.mentions)}>
            <span className="starter-icon">{index === 0 ? <Github size={17} /> : <Layers3 size={17} />}</span>
            <span><strong>{item.title}</strong><small>{item.prompt}</small></span>
          </button>
        ))}
      </div>
    </div>
  );
}

function Message({ entry, running }: { entry: ChatEntry; running: boolean }) {
  return (
    <article className={`message ${entry.role}`}>
      <div className="avatar">{entry.role === "user" ? "Y" : <Sparkles size={15} />}</div>
      <div className="message-body">
        <div className="message-meta">{entry.role === "user" ? "你" : "Agent"}</div>
        {entry.mentions && entry.mentions.length > 0 && (
          <div className="message-mentions">
            {entry.mentions.map((mention) => (
              <span key={`${mention.kind}:${mention.id}`}>@{mention.label}</span>
            ))}
          </div>
        )}
        {entry.role === "assistant" ? (
          entry.recommendation ? <RecommendationCard plan={entry.recommendation} /> : entry.content ? <ReactMarkdown>{entry.content}</ReactMarkdown> : (
            <span className="thinking"><i /><i /><i />正在解析意图与能力…</span>
          )
        ) : <p>{entry.content}</p>}
        {entry.role === "assistant" && running && entry.content && <span className="cursor" />}
      </div>
    </article>
  );
}
