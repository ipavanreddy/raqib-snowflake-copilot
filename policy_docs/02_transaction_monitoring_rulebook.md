---
doc_id: POL-TM-002
title: Transaction Monitoring Rulebook
owner: Head of Financial Crime Compliance
version: 3.0
effective_date: 2026-03-01
classification: Internal
---

# Gulf Horizon Bank — Transaction Monitoring Rulebook

> Synthetic document created for the Raqib hackathon demo. Gulf Horizon Bank is fictional; thresholds are illustrative.

## 1. Scope
This rulebook defines the detection scenarios run over all customer accounts, the meaning of each alert, and how alerts are handled. Rule IDs in this document are the identifiers shown in the Raqib alert queue.

## 2. Alert lifecycle
2.1 **NEW**: generated automatically by the monitoring platform.
2.2 **IN_REVIEW**: assigned to an analyst, who gathers evidence (transactions, KYC profile, counterparties, policy references).
2.3 **ESCALATED**: the analyst believes the activity may be suspicious and opens a case for the MLRO.
2.4 **CLOSED_FALSE_POSITIVE** or **CLOSED_NO_ACTION**: the analyst documents the rationale. A closure rationale is mandatory and must reference the evidence reviewed.
2.5 **STR_FILED**: the MLRO decided to file a Suspicious Transaction Report.

## 3. Consolidation
Alerts are consolidated to one alert per customer per rule within the review period (for TM-06, per matched counterparty), to avoid duplicate work and to present the full pattern in one place.

## 4. AML scenarios

### 4.1 TM-01 Cash structuring below reporting threshold
**Logic:** three or more cash deposits by the same customer, each between AED 45,000 and AED 54,999, within any rolling 7-day period.
**Rationale:** deposits just below the AED 55,000 internal reporting threshold (AML/CFT Policy s.7.2) are a classic structuring pattern. The use of multiple branches increases the concern.
**Severity:** HIGH. **Base score:** 30.
**Analyst checks:** source of cash; whether the customer's business is cash-intensive; onward movement of funds; branch CCTV and teller notes where relevant.

### 4.2 TM-02 Rapid pass-through of funds
**Logic:** at least two episodes in the review period where a credit of AED 200,000 or more (and at least 50% of the customer's declared monthly turnover) is followed within 48 hours by debits totalling 90%–110% of that credit, to at least two counterparties including at least one cross-border beneficiary.
**Rationale:** amount-matched forwarding with little retained balance indicates the account is a conduit in a layering chain (AML/CFT Policy s.7.3).
**Severity:** HIGH. **Base score:** 30.
**Analyst checks:** underlying trade documents (invoices, bills of lading); relationship between remitters and beneficiaries; whether goods actually move.

### 4.3 TM-03 Fan-in from many unrelated senders
**Logic:** an individual's account receives transfers from 10 or more distinct senders within 7 days.
**Rationale:** typical of money-mule recruitment, where students or newly arrived residents lend their accounts (Fraud Typologies Circular s.3).
**Severity:** HIGH. **Base score:** 25.
**Analyst checks:** account tenure, age, occupation; whether funds are forwarded to a common collector; links between mule accounts.

### 4.4 TM-04 High-risk jurisdiction exposure
**Logic:** any wire to or from a PROHIBITED jurisdiction (FATF call for action), or AED 100,000 or more in a calendar month with HIGH-risk jurisdictions.
**Rationale:** geographic risk (AML/CFT Policy s.7.5; Sanctions Screening Procedure s.5).
**Severity:** HIGH. **Base score:** 25.
**Analyst checks:** purpose of payment; end-user and goods (dual-use concerns); whether a licensed exchange-house corridor should have been used.

### 4.5 TM-05 Dormant account reactivation
**Logic:** first activity after 180 or more days of dormancy, with AED 100,000 or more credited within 30 days of reactivation.
**Rationale:** dormant accounts may be taken over or sold for misuse.
**Severity:** MEDIUM. **Base score:** 20.
**Analyst checks:** who initiated reactivation; updated KYC; source of the new credits; cash withdrawals.

### 4.6 TM-06 Watchlist name match on counterparty
**Logic:** the normalised counterparty name has Jaro-Winkler similarity of 90 or more to a sanctions, PEP, or internal blacklist entry, or identical first and last name tokens (to catch abbreviated middle names).
**Rationale:** potential sanctions exposure (Sanctions Screening Procedure s.4).
**Severity:** CRITICAL. **Base score:** 40.
**Analyst checks:** disambiguate using date of birth, nationality, address, registration number; if a true match to a targeted financial sanctions list, freeze and report without delay.

### 4.7 TM-07 Activity inconsistent with customer profile
**Logic:** third-party and cash credits over any 30-day period of at least 5 times the declared expected monthly turnover, and at least AED 50,000.
**Rationale:** CDD Standard s.6 requires activity to be consistent with the expected-activity profile captured at onboarding.
**Severity:** MEDIUM. **Base score:** 15.
**Analyst checks:** request explanation and documents through the relationship manager (without tipping off); update the profile if legitimate.

## 5. Fraud scenarios

### 5.1 FR-01 Account takeover pattern
**Logic:** a beneficiary is added from a device first seen in the previous 24 hours, where either the session originates outside the UAE or a password reset or OTP failure occurred in the prior hour, followed by AED 20,000 or more debited within 2 hours.
**Rationale:** classic social-engineering or SIM-swap account takeover (Fraud Typologies Circular s.2).
**Severity:** CRITICAL. **Base score:** 35.
**Immediate action:** block digital channel, call customer on registered number, attempt recall of funds from beneficiary bank.

## 6. Customer risk score
Raqib computes an explainable 0–100 score per customer:
- **Rule points:** sum of base scores of distinct rules hit, capped at 70.
- **Multi-typology:** +5 when three or more different rules hit.
- **KYC rating:** HIGH +12, MEDIUM +4.
- **PEP:** +10.
- **Nationality in a HIGH or PROHIBITED tier:** +5.
- **KYC review overdue:** +5.
- **Alerted value:** at least AED 1,000,000 gives +8; at least AED 250,000 gives +4.

Bands: CRITICAL ≥ 70, HIGH ≥ 45, MEDIUM ≥ 20, LOW < 20. CRITICAL customers must be reviewed the same business day.

## 7. Tuning and validation
Each scenario is back-tested at least annually against confirmed cases and below-the-line samples. Changes to thresholds require Model Risk and MLRO approval and are version-controlled.
