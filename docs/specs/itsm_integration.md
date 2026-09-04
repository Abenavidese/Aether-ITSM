# ITSM Integration Spec (Mock Jira Service Management)

For the MVP, we will mock Jira Service Management (JSM) using local SQLite or a simple JSON file database, but the API contracts will mimic real JSM REST APIs to prove integration readiness.

## 1. Webhook Payload (From ITSM to Aether)
When a ticket is created in JSM, it sends a POST request to our FastAPI endpoint: `/api/webhook/jira`

```json
{
  "issue": {
    "id": "10001",
    "key": "IT-123",
    "fields": {
      "summary": "VPN connection dropping",
      "description": "I can't connect to the corporate VPN since this morning.",
      "reporter": {
        "emailAddress": "j.doe@company.com"
      },
      "priority": {"name": "High"}
    }
  }
}
```

## 2. Aether to JSM (Add Comment)
When Aether needs to communicate (e.g., adding a Work Note for L3 approval, or resolving a ticket), it makes a REST call to Jira.

**Endpoint:** `POST https://mock-jira.company.com/rest/api/3/issue/IT-123/comment`
**Payload:**
```json
{
  "body": {
    "type": "doc",
    "version": 1,
    "content": [
      {
        "type": "paragraph",
        "content": [
          {
            "text": "🤖 Aether AI: VPN Session reset successfully.",
            "type": "text"
          }
        ]
      }
    ]
  }
}
```

## 3. Approval Mechanism (The Human Gate)
The IT Agent will click a mocked "Approve" transition in Jira, which triggers a webhook to Aether:
`POST /api/approve/IT-123`
`Payload: {"approved": true, "approver_id": "admin.smith"}`
