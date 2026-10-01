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
  recommendation?: RecommendationPlan;
}

export interface RecommendationItem {
  id?: string | number;
  type?: string | number;
  title: string;
  url?: string;
  action_label?: string;
  [key: string]: unknown;
}

export interface RecommendationSection {
  key?: string;
  title: string;
  items: RecommendationItem[];
  meta?: Record<string, unknown>;
}

export interface RecommendationPlan {
  text?: string;
  title: string;
  description?: string;
  card_type: "lesson" | "homework" | "resource";
  sections: RecommendationSection[];
}
