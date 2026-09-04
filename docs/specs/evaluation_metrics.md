# Evaluation & Metrics Plan (Hackathon MVP)

## 1. Key Performance Indicators (KPIs)
To demonstrate business value to the hackathon judges, we will track and present the following metrics:
1. **L1 Deflection Rate (Simulated):** Target 100% resolution on Level 2 test flows.
2. **Mean Time To Resolution (MTTR):** Target < 30 seconds for Auto-Resolve flows (compared to an assumed 15-minute human benchmark).
3. **Token Efficiency:** Track the ratio of tokens sent to Nano vs Super vs Ultra. Target > 80% usage on Nano/Super to prove cost-effectiveness.

## 2. Test Dataset (Synthetic Tickets)
We will generate a dataset of 30 synthetic tickets stored in `tests/data/tickets.json`.
- **10x Level 1/2 Tickets:** "My VPN is stuck", "I need Docker installed".
- **10x Level 3 Tickets:** "Please grant me AWS Admin access for project X".
- **10x Level 4 Tickets:** "The production database is throwing OOM errors".

**Concurrency Mitigation (SQLite):** To avoid database locking issues with `SqliteSaver` during the live demo, the test script will inject the tickets into the FastAPI webhook with a randomized jitter of 1.5 to 3 seconds between requests.

**Success Criteria per Ticket:**
- The agent assigns the correct Risk Level (100% accuracy required).
- The agent triggers the correct tool with the right parameters (for L2).
- The agent halts and generates a plan (for L3).

## 3. Demo Visualization (React Dashboard)
To maximize impact with hackathon judges, relying solely on LangSmith and mock Jira APIs is insufficient visually. We will build a lightweight frontend:
- **Tech Stack:** React (Vite) or Next.js with TailwindCSS.
- **Features:**
  - Real-time stream of incoming synthetic tickets.
  - Live agent state tracking (Classification -> Execution -> Resolution).
  - A real-time token and cost counter aggregating Nebius Token Factory usage.
  - A dashboard view for the IT Agent to review and click "Approve" for L3 tickets.

## 4. Logging Strategy
- **LangSmith:** We will configure `LANGCHAIN_TRACING_V2=true` to capture a visual trace of every graph execution.
- **Custom Callback:** A callback in LangGraph will aggregate the token usage and push updates via WebSockets to the React Dashboard.
