# Raqib — Solution Design

## 1. Problem
GCC banks and NBFCs run financial-crime and prudential-risk work in silos. Transaction-monitoring alerts are triaged by
hand across core banking screens, policy PDFs and spreadsheets. Most alerts turn out to be false positives, and every
STR narrative is written from scratch. Liquidity (Basel III LCR) and credit (IFRS 9) reporting are assembled in Excel. Regulators expect
consistent, explainable, evidenced decisions, and auditors expect a trail.

**Raqib** ("observer" in Arabic) is a copilot that takes a team from **signal → evidence → documented finding**. It
answers natural-language questions with governed numbers, cites the policy clause behind every decision, and drafts
audit-ready STRs and regulatory reports. A guardrail layer prevents hallucinated figures, tipping-off and unauthorised filing.

## 2. Personas and top questions
| Persona | Top questions / jobs |
|---|---|
| **FCC analyst** | Which alerts first? Why did this fire? What does the evidence show compared with the KYC profile? Close or escalate? |
| **MLRO** | Which cases need my decision? Is this STR complete, accurate and compliant? File it. What are the monthly MI and the backlog? |
| **Treasury / risk** | Are we above the LCR trigger? What drove the dip? Which sectors breach the NPL appetite? Which borrowers are also under AML review? |
| **Audit / model risk** | Who asked what, which tools acted, and on what evidence? Do the rules still detect known typologies? |

## 3. Data model (synthetic, referentially consistent)
`CUSTOMERS (2,150)` → `ACCOUNTS (2,789)` → `TRANSACTIONS (~215k, 180 days)` → `COUNTERPARTIES (~12.6k)`, plus `DIGITAL_EVENTS (~67k)`,
`LOANS (~1k)`, `LIQUIDITY_DAILY (180)`, `COUNTRY_RISK`, `WATCHLIST`, and `PLANTED_CASES` (42 ground-truth scenarios).

## 4. Ontology (semantic views)
```
Customer ──< Account ──< Transaction >── Counterparty ── Country(risk tier)
   │                          │
   ├──< Alert (Rule) ──< CaseAlert >── Case ──< Report (STR)
   ├──< Loan (IFRS 9 stage, ECL)
   └── RiskScore (explainable components)
Bank ──< LCR day (HQLA, outflows, inflows)
Policy ──< Chunk  (cited by Alert.rule, Report)
```
- **AML_SV:** customers, transactions, alerts, cases. Synonyms, governed metrics (alert_count, open_alert_count,
  high_risk_jurisdiction_value_aed, ...) and verified queries.
- **RISK_SV:** LCR and loans. lcr_percent, early_warning_days, npl_ratio_pct, coverage_pct, and so on.
- The same metric therefore resolves identically in the agent, Snowsight, CoCo and the app.

## 5. Workflow
1. **Signal.** Dynamic tables enrich transactions. Eight rules (TM-01..07, FR-01) produce consolidated alerts, and an
   explainable 0–100 customer risk score ranks the queue.
2. **Evidence.** For an alert, the agent or app pulls the triggering transactions, KYC profile, counterparties, money-flow
   graph, credit exposure, and the governing policy passage (Cortex Search over parsed PDFs).
3. **Decision.** The analyst closes the alert with a mandatory rationale, or opens a case. All the customer's alerts are linked and a
   notification is queued.
4. **Documented finding.** `DRAFT_STR` composes evidence and policy passages and has the LLM draft the narrative. Code then
   validates it: amounts reconciled, citations real, no tipping-off. It is stored as `DRAFT` or `DRAFT_NEEDS_REVIEW`.
5. **Approval.** Only the MLRO can file (caller's-rights procedure, role check), and a goAML reference is recorded.
6. **Oversight.** Everything goes to `AUDIT_LOG` and `COPILOT_AUDIT`. The golden eval and recall tests run in CI and in CoCo.

## 6. Detection rules (summary)
| Rule | Typology | Logic |
|---|---|---|
| TM-01 | Structuring | ≥3 cash deposits of AED 45,000–54,999 within 7 days |
| TM-02 | Layering | ≥2 episodes: credit ≥ AED 200k (≥50% of declared turnover) forwarded 90–110% within 48h to ≥2 counterparties, incl. cross-border |
| TM-03 | Money mule | ≥10 distinct senders within 7 days (individuals) |
| TM-04 | Geographic | any PROHIBITED-tier wire, or ≥ AED 100k/month to HIGH-tier |
| TM-05 | Dormant | first activity after ≥180 days, ≥ AED 100k credited within 30 days |
| TM-06 | Sanctions | normalised name Jaro-Winkler ≥90, or identical first and last tokens |
| TM-07 | Profile | 30-day third-party and cash credits ≥5× declared turnover and ≥ AED 50k |
| FR-01 | Account takeover | beneficiary added from a device first seen <24h earlier with a foreign IP or a reset, then ≥ AED 20k out within 2h |

Calibrated on the synthetic ground truth: **100% recall** on all planted typologies, **≤12 alerts per rule** on
non-planted customers, and the multi-typology hero case ranked CRITICAL in the top 5.

## 7. Guardrails and graceful failure
| Risk | Control |
|---|---|
| Hallucinated numbers | Amount reconciliation against evidence; a failed draft cannot be filed |
| Fake citations | Cited chunk IDs must be among the retrieved passages |
| Tipping-off | Pattern filter removes text and flags the draft; agent instructions prohibit it |
| Unauthorised filing | The agent has no filing tool; `APPROVE_REPORT` requires `RAQIB_MLRO` (caller's rights) |
| Weak closures | A closure rationale of at least 25 characters is required |
| Model outage | Primary model → fallback model → deterministic template |
| PII exposure | Tag-based masking; analysts see masked IDs |
| Unknown entities | Explicit "not found"; never a guess (eval case Q10) |

## 8. Why Snowflake-native
One governed copy of the data. No movement out of the platform for AI (Cortex runs in place). RBAC and masking apply
to the agent automatically, and dynamic tables give near-real-time detection without orchestration code.
