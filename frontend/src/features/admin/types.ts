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
