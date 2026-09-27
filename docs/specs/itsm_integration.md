# ITSM Integration Spec

> **Status** (reviewed against the code on 2026-09-26, roadmap 1.3): only the inbound
> direction exists. There is no Jira/ServiceNow client and no mock of one: Aether does not
> comment on, resolve or transition ITSM tickets yet. Sections marked **Planned** describe
> the target contract, not running code.

## 1. Inbound webhook (ITSM → Aether) — Implemented

`POST /api/webhook/ticket`, authenticated with the tenant's API key in the `x-api-key`
header (stored hashed; shown once in Settings). Answers `202` at once; the agent run goes
through the durable job queue.

```json
{
  "ticket_id": "IT-123",
  "summary": "VPN connection dropping",
  "description": "I can't connect to the corporate VPN since this morning.",
  "user_email": "j.doe@company.com",
  "image_base64": "data:image/png;base64,..."
}
```

- `user_email` must belong to a real Aether user of that tenant (`404` otherwise).
- `image_base64` is optional: a real png/jpeg/webp as an inline data URI, ≤ 5 MB. It is read
  by the vision model into text before the agents see the ticket (`src/agent/vision.py`).
- A re-delivered `ticket_id` is acknowledged and not processed twice.
- The original draft of this doc specified a Jira-shaped payload at `/api/webhook/jira`;
  that endpoint was never built. An adapter from Jira/ServiceNow payloads to this one is
  **Planned**.

## 2. Aether → ITSM (comment / resolve) — Planned

Not implemented. Today the outcome is visible in Aether's dashboard and, on escalation, in a
GitHub issue. Roadmap 3.6 plans a callback to the tenant's ITSM when a ticket is resolved or
escalated, signed with HMAC so the receiver can verify it came from Aether. The Jira comment
payload below is the intended shape for a Jira adapter:

```json
POST /rest/api/3/issue/IT-123/comment
{"body": {"type": "doc", "version": 1, "content": [{"type": "paragraph",
  "content": [{"type": "text", "text": "🤖 Aether AI: VPN session reset successfully."}]}]}}
```

## 3. Approval mechanism (the human gate) — Implemented in Aether, not in the ITSM

Risk-3 tickets pause after `draft_plan`. An `admin`/`superadmin` of the same tenant approves
or rejects in Aether's dashboard (`HumanGatePanel`), which calls:

```
POST /api/approve/IT-123            (session cookie auth, own tenant only)
{"approved": true, "approver_id": "admin.smith"}
```

Approving from inside Jira/ServiceNow (a transition triggering this endpoint) is **Planned**;
it would need a signed request, since the ITSM would not hold an Aether session.
