import {
  ArrowRight,
  BookOpenCheck,
  BrainCircuit,
  Check,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Clock3,
  Code2,
  Database,
  Eye,
  FileSearch,
  GitBranch,
  HelpCircle,
  ListChecks,
  LoaderCircle,
  Play,
  Route,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { ReactNode, useEffect, useState } from "react";

import type { RunEvent } from "../types";

const config: Record<string, { label: string; icon: typeof Play; chapter: string }> = {
  "run.started": { label: "接收任务", icon: Play, chapter: "输入" },
  "context.resolved": { label: "解析 @ 上下文", icon: FileSearch, chapter: "理解" },
  "intent.detected": { label: "识别结构化意图", icon: BrainCircuit, chapter: "理解" },
  "route.selected": { label: "选择能力", icon: Route, chapter: "决策" },
  "plan.created": { label: "生成执行计划", icon: ListChecks, chapter: "规划" },
  "capability.started": { label: "准备执行能力", icon: CircleDot, chapter: "执行" },
  "capability.arguments": { label: "生成工具参数", icon: Code2, chapter: "执行" },
  "capability.completed": { label: "能力执行完成", icon: Check, chapter: "执行" },
  "response.synthesizing": { label: "合成最终回答", icon: Sparkles, chapter: "回答" },
  "message.completed": { label: "回答生成完成", icon: BookOpenCheck, chapter: "回答" },
  "run.completed": { label: "运行完成", icon: Check, chapter: "完成" },
  "run.error": { label: "运行失败", icon: CircleDot, chapter: "错误" },
  "run.needs_input": { label: "等待用户补充", icon: HelpCircle, chapter: "交互" },
};

const defaultOpenTypes = new Set([
  "context.resolved",
  "intent.detected",
  "route.selected",
  "plan.created",
  "capability.arguments",
  "capability.completed",
]);

export function RunInspector({ events, running }: { events: RunEvent[]; running: boolean }) {
  const [expandAll, setExpandAll] = useState(false);
  const visible = events.filter((event) => event.type !== "message.delta");
  return (
    <aside className="inspector">
      <div className="panel-heading trace-heading">
        <div>
          <span className="eyebrow">EXPLAINABLE AGENT TRACE</span>
          <h2>执行过程</h2>
        </div>
        <span className={running ? "status-pill running" : "status-pill"}>
          {running ? <LoaderCircle size={12} className="spin" /> : <Check size={12} />}
          {running ? "执行中" : "就绪"}
        </span>
      </div>

      {visible.length === 0 ? (
        <div className="empty-trace">
          <GitBranch size={24} />
          <p>发送消息后，这里会逐步解释 Agent 读取了什么、如何选择能力，以及每一步产出了什么。</p>
        </div>
      ) : (
        <>
          <div className="trace-learning-bar">
            <span><ShieldCheck size={13} /> 展示可验证依据，不展示隐藏思维链</span>
            <button onClick={() => setExpandAll((value) => !value)}>
              <Eye size={13} /> {expandAll ? "收起全部" : "展开全部"}
            </button>
          </div>
          <div className="trace-list explainable">
            {visible.map((event, index) => (
              <TraceItem
                event={event}
                expandAll={expandAll}
                key={event.id}
                last={index === visible.length - 1}
              />
            ))}
          </div>
        </>
      )}
    </aside>
  );
}

function TraceItem({ event, last, expandAll }: { event: RunEvent; last: boolean; expandAll: boolean }) {
  const [open, setOpen] = useState(defaultOpenTypes.has(event.type));
  useEffect(() => setOpen(expandAll || defaultOpenTypes.has(event.type)), [expandAll, event.type]);
  const itemConfig = config[event.type] ?? { label: event.type, icon: CircleDot, chapter: "事件" };
  const Icon = itemConfig.icon;
  const duration = typeof event.data.duration_ms === "number" ? `${event.data.duration_ms} ms` : "";
  return (
    <div className={`trace-item trace-${event.type.replaceAll(".", "-")}`}>
      <div className="trace-rail">
        <span className={last ? "trace-dot current" : "trace-dot"}><Icon size={12} /></span>
        {!last && <span className="trace-line" />}
      </div>
      <div className="trace-card">
        <button className="trace-card-header" onClick={() => setOpen((value) => !value)}>
          <span className="trace-step-index">{String(event.sequence).padStart(2, "0")}</span>
          <span className="trace-heading-copy">
            <span><em>{itemConfig.chapter}</em>{duration && <small><Clock3 size={10} /> {duration}</small>}</span>
            <strong>{itemConfig.label}</strong>
            <span className="trace-summary">{eventSummary(event)}</span>
          </span>
          {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>
        {open && <div className="trace-details"><EventDetails event={event} /></div>}
      </div>
    </div>
  );
}

function EventDetails({ event }: { event: RunEvent }) {
  const data = event.data;
  return (
    <>
      {data.explanation && (
        <DetailBlock icon={<BookOpenCheck size={13} />} title="这一步做了什么">
          <p>{String(data.explanation)}</p>
        </DetailBlock>
      )}
      {event.type === "run.started" && (
        <>
          <KeyValue label="用户输入" value={data.message} />
          <KeyValue label="模型提供方" value={data.provider} />
          <KeyValue label="显式引用" value={`${data.mention_count ?? 0} 个`} />
        </>
      )}
      {event.type === "context.resolved" && <ContextDetails data={data} />}
      {event.type === "intent.detected" && <IntentDetails data={data} />}
      {event.type === "route.selected" && <RouteDetails data={data} />}
      {event.type === "plan.created" && <PlanDetails data={data} />}
      {event.type === "capability.started" && <CapabilityStartDetails data={data} />}
      {event.type === "capability.arguments" && (
        <DetailBlock icon={<Code2 size={13} />} title="生成的调用参数">
          <CodeBlock value={data.arguments} />
        </DetailBlock>
      )}
      {event.type === "capability.completed" && <CapabilityResultDetails data={data} />}
      {event.type === "response.synthesizing" && (
        <div className="metric-grid">
          <Metric label="上下文" value={data.context_count ?? 0} />
          <Metric label="能力结果" value={data.result_count ?? 0} />
          <Metric label="成功结果" value={data.successful_results ?? 0} />
        </div>
      )}
      {event.type === "message.completed" && (
        <div className="metric-grid">
          <Metric label="回答字符" value={data.character_count ?? 0} />
          <Metric label="生成耗时" value={`${data.duration_ms ?? 0} ms`} />
        </div>
      )}
      {event.type === "run.completed" && (
        <>
          <KeyValue label="总耗时" value={`${data.duration_ms ?? 0} ms`} />
          <KeyValue label="使用能力" value={(data.selected_capabilities ?? []).join("、") || "无"} />
        </>
      )}
      {event.type === "run.needs_input" && (
        <div className="needs-input-card">
          <HelpCircle size={14} />
          <div><span>Agent 的追问</span><strong>{String(data.question ?? "请补充更多信息。")}</strong></div>
        </div>
      )}
      <details className="raw-event">
        <summary>查看原始事件数据</summary>
        <CodeBlock value={compactRawData(event)} />
      </details>
    </>
  );
}

function ContextDetails({ data }: { data: Record<string, any> }) {
  return (
    <DetailBlock icon={<Database size={13} />} title="解析结果">
      <div className="context-detail-list">
        {(data.items ?? []).map((item: any) => (
          <div key={`${item.kind}:${item.id}`}>
            <span className="detail-kind">{item.kind}</span>
            <strong>{item.title}</strong>
            <small>{item.source}</small>
            <p>{item.preview}</p>
          </div>
        ))}
        {(data.items ?? []).length === 0 && <p className="detail-empty">本轮没有显式 @ 引用。</p>}
      </div>
    </DetailBlock>
  );
}

function IntentDetails({ data }: { data: Record<string, any> }) {
  return (
    <>
      <div className="metric-grid">
        <Metric label="意图" value={data.intent ?? "unknown"} wide />
        <Metric label="需澄清" value={data.needs_clarification ? "是" : "否"} />
      </div>
      <KeyValue label="目标" value={data.goal} />
      <KeyValue label="识别实体" value={(data.entities ?? []).join("、") || "无"} />
      <KeyValue label="约束" value={(data.constraints ?? []).join("、") || "无"} />
      <KeyValue label="期望输出" value={data.expected_output} />
    </>
  );
}

function RouteDetails({ data }: { data: Record<string, any> }) {
  const selectedIds = new Set((data.selections ?? []).map((item: any) => item.capability_id));
  return (
    <>
      <div className="route-summary-row">
        <Metric label="候选能力" value={data.candidate_count ?? 0} />
        <ArrowRight size={14} />
        <Metric label="最终选择" value={(data.selections ?? []).length} />
      </div>
      <DetailBlock icon={<Route size={13} />} title="选择结果与理由">
        <div className="selection-list">
          {(data.selections ?? []).map((item: any) => (
            <div key={item.capability_id}>
              <span className={item.forced ? "forced-badge" : "auto-badge"}>{item.forced ? "@ 强制" : "自动"}</span>
              <strong>{item.capability_id}</strong>
              <p>{item.reason}</p>
            </div>
          ))}
        </div>
      </DetailBlock>
      <details className="candidate-list">
        <summary>查看全部候选能力</summary>
        {(data.candidates ?? []).map((item: any) => (
          <div className={selectedIds.has(item.id) ? "selected" : ""} key={item.id}>
            <span>{item.kind}</span><strong>{item.name}</strong><small>{item.description}</small>
          </div>
        ))}
      </details>
    </>
  );
}

function PlanDetails({ data }: { data: Record<string, any> }) {
  return (
    <div className="plan-steps">
      {(data.steps ?? []).map((step: any, index: number) => (
        <div key={step.id}>
          <span>{index + 1}</span>
          <div><strong>{step.title}</strong><small>{step.instruction}</small><em>{step.capability_id}</em></div>
        </div>
      ))}
    </div>
  );
}

function CapabilityStartDetails({ data }: { data: Record<string, any> }) {
  return (
    <>
      <KeyValue label="能力" value={`${data.name}（${data.kind}）`} />
      <KeyValue label="用途" value={data.description} />
      <KeyValue label="选择原因" value={data.instruction} />
      <KeyValue label="所需权限" value={(data.permissions ?? []).join("、") || "无"} />
      {Object.keys(data.input_schema ?? {}).length > 0 && (
        <DetailBlock icon={<Code2 size={13} />} title="输入 Schema">
          <CodeBlock value={data.input_schema} />
        </DetailBlock>
      )}
    </>
  );
}

function CapabilityResultDetails({ data }: { data: Record<string, any> }) {
  return (
    <>
      <div className={data.success ? "result-banner success" : "result-banner failed"}>
        {data.success ? <Check size={13} /> : <CircleDot size={13} />}
        <span><strong>{data.success ? "执行成功" : "执行失败"}</strong>{data.summary}</span>
      </div>
      <DetailBlock icon={<Database size={13} />} title="能力输出">
        <CodeBlock value={data.data ?? {}} />
      </DetailBlock>
    </>
  );
}

function DetailBlock({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return <section className="detail-block"><h4>{icon}{title}</h4>{children}</section>;
}

function KeyValue({ label, value }: { label: string; value: unknown }) {
  return <div className="key-value"><span>{label}</span><strong>{String(value ?? "")}</strong></div>;
}

function Metric({ label, value, wide = false }: { label: string; value: unknown; wide?: boolean }) {
  return <div className={wide ? "metric wide" : "metric"}><span>{label}</span><strong>{String(value)}</strong></div>;
}

function CodeBlock({ value }: { value: unknown }) {
  return <pre className="detail-code">{JSON.stringify(value, null, 2)}</pre>;
}

function compactRawData(event: RunEvent) {
  const data = { ...event.data };
  if (event.type === "message.completed") delete data.content;
  return { type: event.type, sequence: event.sequence, timestamp: event.timestamp, data };
}

function eventSummary(event: RunEvent): string {
  if (event.type === "context.resolved") return `${event.data.items?.length ?? 0} 个引用已解析为上下文快照`;
  if (event.type === "intent.detected") return `${event.data.intent ?? "unknown"} · ${event.data.expected_output ?? ""}`;
  if (event.type === "route.selected") return event.data.summary ?? "路由完成";
  if (event.type === "plan.created") return `${event.data.steps?.length ?? 0} 个可执行步骤`;
  if (event.type === "capability.started") return `${event.data.name ?? event.data.capability_id} · ${event.data.kind ?? ""}`;
  if (event.type === "capability.arguments") return `为 ${event.data.capability_id} 准备调用参数`;
  if (event.type === "capability.completed") return event.data.summary;
  if (event.type === "response.synthesizing") return `使用 ${event.data.result_count ?? 0} 个能力结果生成回答`;
  if (event.type === "message.completed") return `${event.data.character_count ?? 0} 个字符`;
  if (event.type === "run.completed") return `总耗时 ${event.data.duration_ms ?? 0} ms`;
  if (event.type === "run.needs_input") return event.data.question ?? "需要用户补充信息";
  return event.data.message ?? "";
}
