# Running Raqib through CoCo (Cortex Code) — every phase

The hackathon requires CoCo across **plan → build → execute → test**. Each phase below is a prompt file
that CoCo runs against your Snowflake account, so the work and its session history happen in CoCo.
Session transcripts are saved automatically in `~/.snowflake/cortex/conversations/`. Export them with
`cortex conversations` and keep screenshots, as `coco/EVIDENCE.md` describes.

> Prerequisites: a Snowflake account with Cortex Code access, `cortex` installed, and a connection named
> `raqib` (see the root README → "Connect").

| Phase | Run | What CoCo does | Evidence to capture |
|---|---|---|---|
| 1. Plan | `cortex -c raqib` then paste `coco/01_plan.md`, or `cortex exec -c raqib --file coco/01_plan.md` | Explores the generated data, frames the problem, and reviews and critiques the data model, ontology and workflow in `docs/` | Plan output and its suggested changes |
| 2. Build | `cortex exec -c raqib --file coco/02_build.md --bypass` | Generates and loads synthetic data, builds dynamic tables, detection, the document pipeline, tools, semantic views, the agent and the app, fixing errors as it goes | Session log, objects in Snowsight |
| 3. Execute | `cortex exec -c raqib --file coco/03_execute.md --bypass` | Runs the end-to-end flow (live injection → alert → case → STR → notification) and turns on schedules | Notifications, tasks, Slack messages |
| 4. Test | `cortex exec -c raqib --file coco/04_test.md --bypass` | Recall and false-positive checks, governance checks, the golden eval, edge cases, and fixes | `OPS.EVAL_RESULTS`, test output |

Interactive alternatives (best for the demo video): start `cortex -c raqib` in the repo root and type
`$synthetic-banking-data`, `$aml-investigation Tariq Mahmoud Haddad`, `$copilot-eval`, `$alert-dispatch`.

## Multi-agent workflow
`coco/05_multi_agent_investigation.md` runs `pipeline-engineer` → `fincrime-investigator` → `report-validator`
(`.cortex/agents/`). The handoffs are explicit HANDOFF blocks, and the validator re-derives every claim independently.

## MCP & automations
- `coco/mcp/README.md`: connect Slack and Jira MCP servers to CoCo.
- `coco/automations/README.md`: schedule the alert dispatch and morning briefing.
