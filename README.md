# AI Incident Triage Agent

> PagerDuty fires → Claude classifies the alert, fetches logs, checks recent deploys, generates a step-by-step runbook, and creates the Jira ticket — before your on-call engineer opens their laptop.

---

## What it does

When a production alert fires, this agent runs the full triage pipeline automatically:

| Step | What happens |
|------|-------------|
| 1. Alert ingested | PagerDuty webhook triggers the n8n workflow |
| 2. Context fetched | K8s logs + recent deploy history pulled for the affected service |
| 3. Claude classifies | Alert categorized, root cause hypothesized, confidence scored |
| 4. Runbook generated | Step-by-step remediation written by Claude based on actual log + deploy context |
| 5. Jira ticket created | Ticket with summary, priority, labels, and full runbook auto-created |
| 6. Slack notified | On-call channel gets classification + root cause + Jira link |

**Mean time to triage: under 90 seconds. Zero manual steps.**

---

## Architecture

```
PagerDuty Alert
      │
      ▼
n8n Webhook Node
      │
      ▼
Normalize Alert (n8n Code Node)
      │
      ▼
Python Agent (Execute Command Node)
  ├── fetch_logs(service)         ← mock_data/k8s_logs.json
  ├── fetch_deploys(service)      ← mock_data/github_deploys.json
  └── Claude API (claude-haiku)
        └── classification + runbook JSON
      │
      ▼
Parse Output (n8n Code Node)
      │
      ├──▶ Jira REST API → create ticket
      └──▶ Slack Webhook → notify #incidents
```

---

## Tech stack

| Layer | Tool | Cost |
|-------|------|------|
| Orchestration | n8n (self-hosted via Docker) | Free |
| AI classification + runbook | Anthropic Claude API (claude-haiku) | Free tier |
| Ticket creation | Jira Cloud | Free plan |
| Notifications | Slack Incoming Webhooks | Free |
| Containerization | Docker + Docker Compose | Free |

---

## Project structure

```
ai-incident-triage-agent/
├── agent/
│   ├── agent.py          # Main Python agent (Claude API calls live here)
│   ├── requirements.txt
│   └── Dockerfile
├── n8n/
│   └── workflow.json     # Import this into n8n to get the full pipeline
├── mock_data/
│   ├── pagerduty_alerts.json   # 3 realistic test alerts (P1/P2/P3)
│   ├── k8s_logs.json           # Mock Kubernetes logs per service
│   └── github_deploys.json     # Mock recent deploy history per service
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/Thiru-2004-varul/ai-incident-triage-agent
cd ai-incident-triage-agent
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY at minimum
```

### 2. Test the Python agent locally (no n8n needed)

```bash
cd agent
pip install -r requirements.txt

# Run against a mock alert
python agent.py --mock PD-001   # P1 — CrashLoopBackOff
python agent.py --mock PD-002   # P2 — High latency
python agent.py --mock PD-003   # P3 — Disk usage
```

You'll see the full JSON output: classification, root cause, runbook steps, Jira summary, Slack message.

### 3. Run the full stack with Docker Compose

```bash
docker compose up -d
```

- n8n UI: http://localhost:5678 (admin / admin123)
- Import `n8n/workflow.json` via n8n → Settings → Import workflow

### 4. Configure n8n

1. Open the **Run Triage Agent** node → update the path to your repo
2. Add **Jira credential**: Basic Auth → your email + Jira API token
3. Add **Slack credential**: Incoming Webhook URL from your Slack app
4. Activate the workflow

### 5. Fire a test alert

```bash
curl -X POST http://localhost:5678/webhook/pagerduty-webhook \
  -H "Content-Type: application/json" \
  -d @mock_data/pagerduty_alerts.json
```

Check n8n executions, your Jira project, and Slack channel.

---

## Sample output

**Claude classification for PD-001 (CrashLoopBackOff):**

```json
{
  "classification": "Kubernetes Pod Failure",
  "confidence": "97%",
  "root_cause": "OOMKilled — container exceeded 512Mi memory limit after deploy v2.4.1 introduced an in-memory cache with no eviction policy.",
  "severity_confirmed": "P1",
  "runbook": [
    "Rollback immediately: kubectl rollout undo deploy/payments-api -n prod",
    "Confirm pod running: kubectl get pods -n prod -l app=payments-api",
    "Check memory post-rollback: kubectl top pods -n prod",
    "Alert deploy author to add LRU eviction cap (max 128Mi) before re-deploying",
    "Add PodMemoryUsage alert rule at 80% threshold to catch this earlier next time"
  ],
  "jira_summary": "[P1] CrashLoopBackOff payments-api — OOMKilled after deploy v2.4.1",
  "jira_priority": "Highest",
  "jira_labels": ["incident", "kubernetes", "oom", "payments"],
  "slack_message": "payments-api is down in prod (OOMKilled). Rollback to v2.4.0 is the fix. Jira ticket created."
}
```

---

## Key metrics

- **Triage time**: under 90 seconds from alert to Jira ticket
- **Zero manual triage steps**: engineer wakes up to classification + runbook already done
- **3 alert types handled**: Pod failure, DB degradation, Infrastructure exhaustion

---

## Extending this project

To connect real data sources (when you have access):

| Mock | Real replacement |
|------|-----------------|
| `k8s_logs.json` | `kubectl logs` via Python `kubernetes` client |
| `github_deploys.json` | GitHub Releases API or Actions API |
| Mock PagerDuty payload | Real PagerDuty v3 webhook subscription |
| `claude-haiku` model | Swap to `claude-sonnet` for higher accuracy |

---

