---
name: alert-dispatch
description: Drain the Raqib notification outbox (RAQIB.OPS.NOTIFICATIONS) to Slack and/or Jira via MCP, then mark items SENT. Use on a schedule or when asked to notify the team about new critical alerts, cases or STR drafts.
tools:
  - sql_execute
  - snowflake_sql_execute
  - mcp__slack__slack_post_message
  - mcp__jira__create_issue
---

# Alert Dispatch (Snowflake → Slack / Jira via MCP)

Snowflake tasks write to an outbox. This skill turns the outbox into actions in other tools, so read-only analytics become cross-tool work.
Trial accounts cannot make outbound calls (no external access integrations), so delivery happens through CoCo's MCP connectors.

## Steps
1. Fetch pending items, most severe first:
   ```sql
   SELECT NOTIFICATION_ID, SEVERITY, TITLE, BODY, OBJECT_ID, CREATED_AT
   FROM RAQIB.OPS.NOTIFICATIONS WHERE STATUS = 'PENDING'
   ORDER BY IFF(SEVERITY = 'CRITICAL', 0, 1), CREATED_AT LIMIT 20;
   ```
2. For each item, post to Slack channel `#raqib-alerts` (or `$RAQIB_SLACK_CHANNEL`):
   `:rotating_light: *{SEVERITY}* {TITLE}\n{BODY}\nOpen in Raqib → Investigate / Cases & Reports`
   Never post identifiers beyond what is in BODY (customer name and ID), and never post STR content.
   STRs are confidential, so post only that a draft exists.
3. For `CRITICAL` items whose `OBJECT_ID` starts with `AL-` or `CASE-`, also create a Jira issue in project `FCC`.
   The summary is `TITLE`, the description is `BODY`, and the label is `raqib`.
4. Mark each item as sent:
   ```sql
   UPDATE RAQIB.OPS.NOTIFICATIONS SET STATUS = 'SENT', SENT_AT = CURRENT_TIMESTAMP() WHERE NOTIFICATION_ID = '<id>';
   ```
5. If an MCP call fails, leave the item `PENDING` and report it. Never mark it SENT without a successful post.

## Scheduling
See `coco/automations/README.md`. The schedule runs `cortex exec --file coco/automations/alert_dispatch.md` every 15 minutes.
