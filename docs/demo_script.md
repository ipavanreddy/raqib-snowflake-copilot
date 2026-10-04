# Demo video script (target 4:30)

Record at 1080p. Use the live Snowflake app if it's deployed, otherwise the offline public demo. Keep CoCo visible in a terminal on the right for sections 1 and 6.

| Time | Screen | Say / do |
|---|---|---|
| 0:00–0:25 | Title slide → Command Center | "GCC banks triage AML alerts by hand and write every STR from scratch. Raqib takes a team from signal to evidence to a filed report, inside Snowflake, and we built every layer of it with CoCo." |
| 0:25–0:55 | CoCo terminal | Show `cortex skill list` (5 project skills). Run `$synthetic-banking-data`, then scroll the Build session where CoCo deployed `sql/01-12` and fixed an error. |
| 0:55–1:25 | Command Center | KPIs, the priority queue led by **Tariq Mahmoud Haddad (100, CRITICAL)**, and the LCR dip below the 110% trigger. Click **Inject STRUCTURING**: the pipeline refreshes and a new alert appears, along with a notification. |
| 1:25–2:20 | Copilot | Ask "Explain why Tariq Mahmoud Haddad is critical risk…". Point out the rules, amounts and score breakdown, the policy citations [POL-TM-002 s.4.1], and the "How I answered" panel (tools and SQL). Then ask "Did our LCR breach the 110% trigger? What drove it?" |
| 2:20–3:00 | Investigate | Select his TM-01 alert. Show the evidence table, the **money-flow graph** (Iran / Lebanon counterparties in red), the score breakdown and the policy tab. Click **Open case & escalate**. |
| 3:00–3:40 | Cases & Reports | Click **Draft STR**. Scroll the STR: subject, grounds, transactions and citations, then the **validation block** (amounts reconciled, citations valid, no tipping-off). Switch persona to MLRO, then **Approve & file** to get a goAML reference. |
| 3:40–4:05 | Governance | Audit trail of every tool action, the copilot Q&A log, the outbox, and detection quality at 100% recall. |
| 4:05–4:25 | CoCo terminal + Slack | `$alert-dispatch` posts the new alert to Slack via MCP. `python eval/run_eval.py --connection raqib` shows the scorecard. |
| 4:25–4:30 | Closing slide | "Raqib: governed, explainable, evidence-backed. Built end to end with CoCo." |

**Backup:** if the live agent is slow, switch to the offline demo link, which answers the same questions with the same tools.
