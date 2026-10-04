# Unattended runs

Two layers keep Raqib running without a human:

**1. Inside Snowflake (always on)**
- `RAQIB.OPS.ALERT_ROUTER` runs every 5 minutes, when the stream has data, and writes new HIGH/CRITICAL alerts to the outbox.
- `RAQIB.OPS.DAILY_BRIEFING` runs at 07:00 Asia/Dubai and drafts the AML MI report; `DAILY_LCR_REPORT` runs after it and drafts the LCR report.
- Dynamic tables refresh with a 5-minute target lag.

**2. CoCo scheduled runs (cross-tool action through MCP)**
Use the CoCo Desktop app's scheduled tasks / automations if your build has them. Otherwise schedule the CLI with launchd or cron:
```bash
# every 15 minutes: drain the outbox to Slack/Jira
*/15 * * * * cd /path/to/raqib && ~/.local/bin/cortex exec -c raqib --file coco/automations/alert_dispatch.md --bypass --max-turns 20 >> logs/dispatch.log 2>&1
# 07:05 Gulf time: morning briefing to Slack
5 7 * * * cd /path/to/raqib && ~/.local/bin/cortex exec -c raqib --file coco/automations/morning_briefing.md --bypass --max-turns 20 >> logs/briefing.log 2>&1
```
Each run is a normal CoCo session, so it appears in `cortex conversations` as evidence.
