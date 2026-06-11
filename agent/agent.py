"""
AI Incident Triage Agent
------------------------
Called by n8n after a PagerDuty alert fires.

Steps:
  1. Receive alert payload (from n8n HTTP Request node)
  2. Fetch mock K8s logs + recent deploy history
  3. Call Claude API → classify alert + generate runbook
  4. Return structured JSON → n8n handles Jira + Slack

Usage:
  python agent.py --alert '{"id":"PD-001","title":"CrashLoopBackOff...","service":"payments-api",...}'
  python agent.py --mock PD-001   # use a pre-built mock alert
"""

import argparse
import json
import os
import sys
from pathlib import Path
import anthropic

MOCK_DATA_DIR = Path(__file__).parent.parent / "mock_data"


def load_mock_data(filename: str) -> dict:
    path = MOCK_DATA_DIR / filename
    with open(path) as f:
        return json.load(f)


def fetch_logs(service: str) -> list[str]:
    """Fetch K8s logs for the affected service (mock)."""
    all_logs = load_mock_data("k8s_logs.json")
    return all_logs.get(service, ["No logs found for service."])


def fetch_deploys(service: str) -> list[dict]:
    """Fetch recent deploy history for the affected service (mock)."""
    all_deploys = load_mock_data("github_deploys.json")
    return all_deploys.get(service, [])


def build_claude_prompt(alert: dict, logs: list[str], deploys: list[dict]) -> str:
    logs_text = "\n".join(logs)
    deploys_text = json.dumps(deploys, indent=2)

    return f"""You are an expert Site Reliability Engineer performing incident triage.

You have received the following PagerDuty alert:

ALERT:
- ID: {alert.get("id")}
- Title: {alert.get("title")}
- Severity: {alert.get("severity")}
- Service: {alert.get("service")}
- Environment: {alert.get("environment")}
- Cluster: {alert.get("cluster")}
- Triggered at: {alert.get("triggered_at")}
- Details: {alert.get("details")}

RECENT KUBERNETES LOGS:
{logs_text}

RECENT DEPLOY HISTORY (last 2 deploys):
{deploys_text}

Based on this information, respond ONLY with a JSON object in exactly this format (no markdown, no preamble):
{{
  "classification": "short category name (e.g. Kubernetes Pod Failure, Database Degradation, Infrastructure Exhaustion)",
  "confidence": "percentage as string (e.g. 97%)",
  "root_cause": "1-2 sentence root cause hypothesis based on logs and deploys",
  "severity_confirmed": "P1 | P2 | P3",
  "runbook": [
    "Step 1: concrete action with exact command or instruction",
    "Step 2: ...",
    "Step 3: ...",
    "Step 4: ...",
    "Step 5: preventive action to stop recurrence"
  ],
  "jira_summary": "short Jira ticket title starting with [{severity}]",
  "jira_priority": "Highest | High | Medium | Low",
  "jira_labels": ["label1", "label2"],
  "slack_message": "one-line Slack alert summary for the on-call channel"
}}"""


def run_triage(alert: dict) -> dict:
    """Main triage function — fetches context, calls Claude, returns structured result."""

    service = alert.get("service", "unknown")
    print(f"[agent] Fetching logs for service: {service}")
    logs = fetch_logs(service)

    print(f"[agent] Fetching deploy history for service: {service}")
    deploys = fetch_deploys(service)

    print("[agent] Calling Claude API for classification + runbook...")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY environment variable not set.")

    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_claude_prompt(alert, logs, deploys)

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",  # fast + cheapest; swap to sonnet for production
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Strip any accidental markdown fences
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(cleaned)

    # Attach original alert context for downstream n8n nodes
    result["alert_id"] = alert.get("id")
    result["alert_title"] = alert.get("title")
    result["service"] = service
    result["environment"] = alert.get("environment")
    result["triggered_at"] = alert.get("triggered_at")
    result["logs_fetched"] = logs
    result["deploys_fetched"] = deploys

    return result


def main():
    parser = argparse.ArgumentParser(description="AI Incident Triage Agent")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--alert", type=str, help="Alert JSON string (from n8n)")
    group.add_argument("--mock", type=str, help="Mock alert ID: PD-001 | PD-002 | PD-003")
    args = parser.parse_args()

    if args.mock:
        alerts = load_mock_data("pagerduty_alerts.json")
        alert = next((a for a in alerts if a["id"] == args.mock), None)
        if not alert:
            print(f"[error] Mock alert {args.mock} not found. Choose PD-001, PD-002, or PD-003.")
            sys.exit(1)
    else:
        try:
            alert = json.loads(args.alert)
        except json.JSONDecodeError as e:
            print(f"[error] Invalid alert JSON: {e}")
            sys.exit(1)

    print(f"[agent] Starting triage for alert: {alert.get('id')} — {alert.get('title')}")
    result = run_triage(alert)

    # Output JSON to stdout — n8n reads this via Execute Command node
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
