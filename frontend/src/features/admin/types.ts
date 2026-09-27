// Shape returned by GET /tenant/dashboard's ticket_stream (see
// src/tenant/router.py get_dashboard_metrics) — the real backend Ticket
// row, not the old useSimulation.ts mock shape (no risk_level/user_id/summary
// fields exist on the persisted model; risk level only ever lives in the
// ephemeral LangGraph state, never on the Ticket row).
export type DashboardTicket = {
  id: string;
  external_id: string | null;
  title: string;
  description: string;
  status: "open" | "resolved" | "escalated" | "pending_human";
  urgency: string;
  category: string;
  created_at: string | null;
  resolution_path: string | null;
  github_issue_url: string | null;
  // Risk-3 plan awaiting approval; ends with the exact action that will run.
  proposed_plan: string | null;
};

// GET /tenant/knowledge (src/rag/documents.py:document_view, Fase 14).
export type KnowledgeStatus = "queued" | "indexing" | "ready" | "failed" | "pending_review" | "rejected";

export type KnowledgeDocument = {
  id: string;
  filename: string;
  source_type: "company_policy" | "technical_repo" | "ai_feedback";
  status: KnowledgeStatus;
  version: number;
  // The version search is serving right now (null until the first one is ready).
  active_version: number | null;
  chunks: number;
  pages: number | null;
  size_bytes: number | null;
  embedding_model: string | null;
  warnings: string[];
  error: string | null;
  // Indexed with another embedding model/chunker than the current one.
  stale: boolean;
  created_at: string | null;
  indexed_at: string | null;
  // Only for ai_feedback: the correction text the reviewer approves.
  content: string | null;
};

// GET /tenant/knowledge/insights (src/rag/insights.py).
export type KnowledgeInsights = {
  days: number;
  searches: number;
  empty_rate: number | null;
  latency_p50_ms: number | null;
  top_documents: { id: string; filename: string; uses: number }[];
  unused_documents: { id: string; filename: string }[];
  unanswered_questions: { query: string; origin: string; at: string | null }[];
  documents: { total: number; ready: number; indexing: number; failed: number; pending_review: number; stale: number };
};
