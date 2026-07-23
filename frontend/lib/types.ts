export type Theme = "light" | "dark";
export type Language = "en" | "ar";

export interface AgentDescriptor {
  agent_id: string;
  label_en: string;
  label_ar: string;
}

export interface AgentEvent {
  agent_id: string;
  label_en: string;
  label_ar: string;
  latency_ms: number;
  decision: string | null;
  cycle: number;
  provider: string | null;
  is_replan: boolean;
}

export interface Citation {
  id: string;
  type: string;
  dataset_or_doc: string;
  source_url: string;
  row_id_or_chunk_id: string | null;
  captured_at: string | null;
  source_tier: string;
  is_synthetic: boolean;
}

export interface TurnMeta {
  session_id: string;
  turn_id: string;
  language: Language;
  intent: string;
  confidence: "high" | "medium" | "low";
  citations: Citation[];
  replan_cycles: number;
  evidence_count: number;
  degraded_mode: boolean;
  data_freshness: string;
  latency_ms: number;
  agents_used: string[];
  trace_id?: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  language: Language;
  streaming?: boolean;
  meta?: TurnMeta;
  agents?: AgentEvent[];
  replanGaps?: string[];
  error?: string;
}

export interface StationMarker {
  id: string;
  name_en: string;
  name_ar: string | null;
  mode: string;
  line: string | null;
  zone: number | null;
  lat: number;
  lon: number;
}
