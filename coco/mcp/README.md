# Connecting Slack and Jira to CoCo via MCP

The alert-dispatch skill and the morning briefing post to Slack and open Jira issues through MCP.
Server packages and tool names vary. After adding a server, run `cortex mcp list`, then update the
`tools:` list in `.cortex/skills/alert-dispatch/SKILL.md` to the tool names it shows (`mcp__<server>__<tool>`).

## Slack
1. Create a Slack app in a test workspace with the bot scopes `chat:write` and `channels:read`, install it, and invite it to `#raqib-alerts`.
2. Add the server. This example uses a community/reference Slack MCP server; use your organisation's approved server if it has one:
   ```bash
   export SLACK_BOT_TOKEN=xoxb-...   SLACK_TEAM_ID=T...
   cortex mcp add slack npx -- -y @modelcontextprotocol/server-slack -e SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN -e SLACK_TEAM_ID=$SLACK_TEAM_ID
   ```
## Jira (optional)
Atlassian provides a remote MCP server. Add it as an HTTP/SSE server and complete the OAuth flow:
```bash
cortex mcp add jira https://mcp.atlassian.com/v1/sse -t sse
```
## Verify
```bash
cortex mcp list
cortex exec -c raqib "Post 'Raqib MCP test' to #raqib-alerts"
```
Keep tokens in environment variables. Never commit them; `.gitignore` excludes secrets files.
