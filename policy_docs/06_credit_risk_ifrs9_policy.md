---
doc_id: POL-CRD-006
title: Credit Risk and IFRS 9 Impairment Policy
owner: Chief Risk Officer
version: 3.3
effective_date: 2026-01-01
classification: Internal
---

# Gulf Horizon Bank — Credit Risk & IFRS 9 Policy

> Synthetic document created for the Raqib hackathon demo. Parameters are simplified and illustrative.

## 1. Staging
| Stage | Criteria | ECL horizon |
|---|---|---|
| Stage 1 | Performing, no significant increase in credit risk (SICR), 0–30 days past due (DPD) | 12-month ECL |
| Stage 2 | SICR: more than 30 DPD, or a qualitative trigger (watch-list, forbearance, sector stress) | Lifetime ECL |
| Stage 3 | Credit-impaired: more than 90 DPD, or unlikely to pay | Lifetime ECL (PD = 100%) |

## 2. Expected credit loss
ECL = PD × LGD × EAD, where:
- **Stage 1:** PD is the 12-month PD.
- **Stage 2:** lifetime PD ≈ 1 − (1 − PD₁₂)^remaining years.
- **Stage 3:** PD = 1.
- **LGD** reflects collateral after haircuts. Unsecured retail LGD floors are 45–75%.

## 3. Non-performing loans
The **NPL ratio** is Stage 3 exposure ÷ total gross exposure. The Board risk appetite is an NPL ratio below **6%** and coverage (ECL ÷ exposure) of at least **3%**. Sectors with NPL ratios above 10% are placed on the sector watch-list.

## 4. Concentration limits
- Real estate and construction combined: ≤ 25% of the loan book.
- Single obligor group: ≤ 7% of capital.

## 5. Interaction with financial crime risk
Borrowers who are subject to an open AML investigation or STR are flagged to Credit Risk. New credit to them is suspended pending the outcome, and existing facilities are reviewed for early-warning signs. Raqib's AML–credit overlap view supports this control.
