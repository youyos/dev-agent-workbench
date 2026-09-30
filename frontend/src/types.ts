export type MentionKind = "skill" | "file" | "resource" | "tool" | "mcp";

export interface MentionRef {
  kind: MentionKind;
  id: string;
  label: string;
  metadata?: Record<string, unknown>;
}

export interface RunEvent {
  id: string;
  run_id: string;
  sequence: number;
  type: string;
  timestamp: string;
  data: Record<string, any>;
}

export interface ChatEntry {
  id: string;
  role: "user" | "assistant";
  content: string;
  mentions?: MentionRef[];
}

