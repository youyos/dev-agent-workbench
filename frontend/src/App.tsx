import { Bot, Braces, Circle, Command, Github, Layers3, PlugZap, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

import { MentionComposer } from "./components/MentionComposer";
import { RunInspector } from "./components/RunInspector";
import { ExtensionDrawer } from "./components/ExtensionDrawer";
import { getHealth, streamRun } from "./lib/api";
import { createId } from "./lib/id";
import type { ChatEntry, MentionRef, RunEvent } from "./types";

const starterPrompts = [
  {
    title: "诊断支付失败",
    prompt: "帮我定位支付为什么失败，并给出修改建议和验证方案",
    mentions: [
      { kind: "skill", id: "debug-code", label: "支付故障诊断" },
      { kind: "file", id: "checkout.py", label: "checkout.py" },
      { kind: "resource", id: "order-1024", label: "订单 #1024" },
    ] as MentionRef[],
  },
  {
    title: "分析课程风险",
    prompt: "分析这门课程目前的学习风险，并给出可以量化验证的干预建议",
    mentions: [
      { kind: "skill", id: "course-analysis", label: "教学数据分析" },
      { kind: "resource", id: "python-course", label: "Python 入门课程" },
    ] as MentionRef[],
  },
];

export default function App() {
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [provider, setProvider] = useState("连接中");
  const [health, setHealth] = useState<{ provider: string; model: string; qwen_configured?: boolean } | null>(null);
  const [extensionsOpen, setExtensionsOpen] = useState(false);
  const conversationRef = useRef<HTMLDivElement>(null);

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

  async function submit(message: string, mentions: MentionRef[]) {
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
    setRunning(true);
    try {
      await streamRun(message, mentions, (event) => {
        setEvents((items) => [...items, event]);
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
        if (event.type === "run.error") {
          throw new Error(String(event.data.message ?? "运行失败"));
        }
      });
    } catch (error) {
      setMessages((items) =>
        items.map((item) =>
          item.id === assistantId
            ? { ...item, content: `运行失败：${error instanceof Error ? error.message : String(error)}` }
            : item,
        ),
      );
    } finally {
      setRunning(false);
    }
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
            <div className="pipeline-mini">
              <span>Context</span><i />
              <span>Intent</span><i />
              <span>Route</span><i />
              <span>Execute</span>
            </div>
          </div>

          <div className="conversation" ref={conversationRef}>
            {messages.length === 0 ? (
              <Welcome onStart={submit} />
            ) : (
              messages.map((message) => <Message entry={message} key={message.id} running={running} />)
            )}
            <div />
          </div>

          <div className="composer-wrap">
            <MentionComposer disabled={running} onSubmit={submit} />
          </div>
        </section>

        <RunInspector events={events} running={running} />
      </main>
      <ExtensionDrawer open={extensionsOpen} onClose={() => setExtensionsOpen(false)} health={health} />
    </div>
  );
}

function Welcome({ onStart }: { onStart: (message: string, mentions: MentionRef[]) => void }) {
  return (
    <div className="welcome">
      <div className="orb"><Bot size={28} /></div>
      <span className="eyebrow">STRUCTURED, TRACEABLE, EXTENSIBLE</span>
      <h2>不是把一堆工具塞给模型，<br />而是先理解，再路由，再执行。</h2>
      <p>
        输入 <kbd>@</kbd> 选择 Skill、文件、工具或业务对象。每个决策都会显示在右侧运行轨迹中。
      </p>
      <div className="starter-grid">
        {starterPrompts.map((item, index) => (
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
          entry.content ? <ReactMarkdown>{entry.content}</ReactMarkdown> : (
            <span className="thinking"><i /><i /><i />正在解析意图与能力…</span>
          )
        ) : <p>{entry.content}</p>}
        {entry.role === "assistant" && running && entry.content && <span className="cursor" />}
      </div>
    </article>
  );
}
