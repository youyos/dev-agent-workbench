import { CornerDownLeft, FileCode2, Puzzle, Search, Sparkles, Wrench, X } from "lucide-react";
import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import { searchMentions } from "../lib/api";
import type { MentionKind, MentionRef } from "../types";

const iconByKind: Record<MentionKind, typeof Puzzle> = {
  skill: Sparkles,
  file: FileCode2,
  resource: Puzzle,
  tool: Wrench,
  mcp: Puzzle,
};

const labelByKind: Record<MentionKind, string> = {
  skill: "Skill",
  file: "文件",
  resource: "业务对象",
  tool: "工具",
  mcp: "MCP",
};

interface Props {
  disabled?: boolean;
  onSubmit: (message: string, mentions: MentionRef[]) => void;
}

export function MentionComposer({ disabled, onSubmit }: Props) {
  const [value, setValue] = useState("");
  const [mentions, setMentions] = useState<MentionRef[]>([]);
  const [options, setOptions] = useState<MentionRef[]>([]);
  const [active, setActive] = useState(0);
  const [kindFilter, setKindFilter] = useState<MentionKind | "all">("all");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const match = useMemo(() => value.match(/(?:^|\s)@([^\s@]*)$/), [value]);
  const mentionQuery = match?.[1] ?? null;

  useEffect(() => {
    if (mentionQuery === null) {
      setOptions([]);
      setKindFilter("all");
      return;
    }
    const timer = window.setTimeout(() => {
      searchMentions(mentionQuery, kindFilter === "all" ? undefined : kindFilter)
        .then((items) => {
          setOptions(items);
          setActive(0);
        })
        .catch(() => setOptions([]));
    }, 100);
    return () => window.clearTimeout(timer);
  }, [kindFilter, mentionQuery]);

  function choose(item: MentionRef) {
    const start = match?.index ?? value.length;
    const prefix = value.slice(0, start).trimEnd();
    setValue(prefix ? `${prefix} ` : "");
    setMentions((current) =>
      current.some((mention) => mention.kind === item.kind && mention.id === item.id)
        ? current
        : [...current, item],
    );
    setOptions([]);
    setActive(0);
    requestAnimationFrame(() => textareaRef.current?.focus());
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (options.length) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive((current) => (current + 1) % options.length);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive((current) => (current - 1 + options.length) % options.length);
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        choose(options[active]);
        return;
      }
      if (event.key === "Escape") {
        setOptions([]);
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  function submit() {
    const message = value.trim();
    if (!message || disabled) return;
    onSubmit(message, mentions);
    setValue("");
    setMentions([]);
  }

  return (
    <div className="composer-shell">
      {options.length > 0 && (
        <div className="mention-menu">
          <div className="mention-menu-title"><Search size={13} /> 选择要加入本轮的上下文或能力</div>
          <div className="mention-filters">
            {(["all", "skill", "file", "resource", "tool", "mcp"] as const).map((kind) => (
              <button
                className={kindFilter === kind ? "active" : ""}
                key={kind}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => setKindFilter(kind)}
                type="button"
              >{kind === "all" ? "全部" : labelByKind[kind]}</button>
            ))}
          </div>
          {Array.from(new Set(options.map((item) => item.kind))).map((kind) => {
            const group = options.filter((item) => item.kind === kind);
            if (!group.length) return null;
            return (
              <div className="mention-group" key={kind}>
                {kindFilter === "all" && <div className="mention-group-title"><span>{labelByKind[kind] || kind}</span><em>{group.length}</em></div>}
                {group.map((item) => {
                  const index = options.indexOf(item);
                  const Icon = iconByKind[item.kind] || Puzzle;
                  return (
                    <button
                      className={index === active ? "mention-option active" : "mention-option"}
                      key={`${item.kind}:${item.id}`}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => choose(item)}
                    >
                      <span className={`mention-icon kind-${item.kind}`}><Icon size={15} /></span>
                      <span className="mention-copy">
                        <strong>{item.label}</strong>
                        <small>{String(item.metadata?.description ?? item.id)}</small>
                      </span>
                      <span className="kind-label">{labelByKind[item.kind] || item.kind}</span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}

      {mentions.length > 0 && (
        <div className="mention-chips">
          {mentions.map((mention) => {
            const Icon = iconByKind[mention.kind] || Puzzle;
            return (
              <span className={`mention-chip kind-${mention.kind}`} key={`${mention.kind}:${mention.id}`}>
                <Icon size={13} /> {mention.label}
                <button onClick={() => setMentions((items) => items.filter((item) => item !== mention))}>
                  <X size={12} />
                </button>
              </span>
            );
          })}
        </div>
      )}

      <textarea
        ref={textareaRef}
        value={value}
        disabled={disabled}
        placeholder="描述你的目标，输入 @ 选择 Skill、文件、工具或业务对象…"
        rows={3}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      <div className="composer-footer">
        <span><kbd>@</kbd> 引用能力和上下文 · <kbd>Shift Enter</kbd> 换行</span>
        <button className="send-button" onClick={submit} disabled={disabled || !value.trim()}>
          {disabled ? "运行中" : "发送"}<CornerDownLeft size={15} />
        </button>
      </div>
    </div>
  );
}
