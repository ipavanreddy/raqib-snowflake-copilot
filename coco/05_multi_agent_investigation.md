# Multi-agent investigation (CoCo subagents)

Coordinate three subagents from `.cortex/agents/` with explicit handoffs and shared context in `findings/`:
1. **pipeline-engineer:** make sure the pipeline is fresh (refresh RAQIB.DETECT.ALERTS) and list the top 3 CRITICAL customers with no case.
   Write `findings/queue.md`.
2. **fincrime-investigator:** for the #1 customer in `findings/queue.md`, run the investigation, open the case, draft the STR and
   emit a HANDOFF block to `findings/handoff.md`.
3. **report-validator:** read `findings/handoff.md` and independently verify every claim. Write `findings/validation.md` with PASS/FAIL.
Finally, summarise: customer, rules, STR id, validation verdict, and what the MLRO must do next.
