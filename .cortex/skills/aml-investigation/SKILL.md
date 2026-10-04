---
name: aml-investigation
description: Investigate a financial-crime alert or customer end to end — signal, evidence, policy basis, decision — and produce a documented finding. Use when asked to investigate, explain or triage an AML/fraud alert, a customer, or a typology (structuring, pass-through, mules, high-risk jurisdictions, sanctions near-matches, account takeover).
tools:
  - sql_execute
  - snowflake_sql_execute
  - read
  - write
---

# AML Investigation (signal → evidence → finding)

A reusable investigation workflow for any bank that exposes alerts, a customer profile and policies in
Snowflake. In this repo it runs against the Raqib objects; to reuse elsewhere, change the names in **Inputs**.

## Inputs (defaults for Raqib)
| Concept | Object |
|---|---|
| Alert queue | `RAQIB.OPS.ALERT_QUEUE` |
| Evidence tool | `CALL RAQIB.OPS.GET_ALERT_EVIDENCE('<alert_id>')` |
| Customer 360 tool | `CALL RAQIB.OPS.GET_CUSTOMER_360('<customer_id>')` |
| Policy search | `SNOWFLAKE.CORTEX.SEARCH_PREVIEW('RAQIB.DOCS.POLICY_SEARCH', ...)` |
| Case tool | `CALL RAQIB.OPS.CREATE_CASE('<customer_id>', '<summary>')` |
| STR draft tool | `CALL RAQIB.OPS.DRAFT_STR('<case_id>')` |

## Steps
1. **Scope.** If given a customer name, resolve it to an ID with
   `SELECT CUSTOMER_ID, FULL_NAME, RISK_SCORE, RISK_BAND, RULE_IDS FROM RAQIB.DETECT.CUSTOMER_RISK WHERE FULL_NAME ILIKE '%<name>%'`.
   If given nothing, start from the top of the queue (highest `RISK_SCORE`, `STATUS = 'NEW'`).
2. **Signal.** List the customer's alerts from `ALERT_QUEUE`, with rule, severity, trigger summary and amount.
3. **Evidence.** For each alert, call `GET_ALERT_EVIDENCE`. Record:
   - the transactions, with dates, amounts, counterparties, countries and branches;
   - the metrics that crossed thresholds;
   - how the activity compares with the KYC profile (occupation or industry, expected monthly turnover, KYC rating, PEP).
4. **Context.** Call `GET_CUSTOMER_360`: score breakdown, other accounts, loans (AML–credit overlap), and top counterparties.
5. **Policy basis.** For each rule, search the policies with the rule's topic and quote the governing clause with its
   `CHUNK_ID`. Always include the threshold that was breached.
6. **Assessment.** Write a short, factual finding using the template below. Separate facts from interpretation.
   Never speculate about guilt, and never suggest contacting the customer about the investigation (tipping-off).
7. **Decision** (confirm with the user before any write):
   - suspicious → `CREATE_CASE`, then `DRAFT_STR`; report the validation result and confidence;
   - explained → `UPDATE_ALERT_STATUS(..., 'CLOSED_FALSE_POSITIVE', '<25+ char rationale citing the evidence>')`.
8. **Record.** Save the finding to `findings/<customer_id>_<date>.md` if the user wants a local copy.

## Finding template
```markdown
# Finding — <customer name> (<customer_id>) — <date>
**Risk:** <score>/100 (<band>) · **Rules:** <TM-xx, ...> · **Recommendation:** <escalate / close>
## Facts
- <dated, amount-exact bullets from evidence>
## Profile comparison
- Declared: <occupation/industry, expected turnover>. Observed: <...> (<n>x).
## Policy basis
- [<DOC_ID> <section>] <clause quoted or paraphrased, with threshold>
## Assessment
<2-4 sentences, neutral>
## Next step
<case/STR or closure rationale>
```

## Quality bar
- Every amount must come from tool output, never from estimation.
- Every rule mentioned must have a policy citation.
- If evidence is missing or a tool errors, say so and stop. Do not fill gaps.
