---
doc_id: POL-SAN-003
title: Sanctions Screening Procedure
owner: Head of Sanctions Compliance
version: 2.4
effective_date: 2026-02-01
classification: Internal
---

# Gulf Horizon Bank — Sanctions Screening Procedure

> Synthetic document created for the Raqib hackathon demo. Gulf Horizon Bank is fictional and the watchlist used in the demo contains invented names only.

## 1. Purpose
To ensure the Bank does not deal with, or make funds available to, designated persons and entities, and to meet its obligations under UAE targeted financial sanctions (TFS) and applicable international sanctions regimes.

## 2. Lists screened
2.1 The UAE Local Terrorist List and the UN Consolidated List (mandatory).
2.2 Other regimes adopted by Board policy where the Bank has exposure (for example, transactions in USD).
2.3 Internal blacklist: customers and counterparties exited by the Bank for financial-crime reasons.
2.4 PEP lists, used for risk rating rather than prohibition.

## 3. When screening happens
3.1 At onboarding, for customers, beneficial owners and authorised signatories.
3.2 Daily re-screening of the full customer base against list updates.
3.3 Real-time screening of every cross-border payment and of counterparties of domestic payments.

## 4. Name matching
4.1 Names are normalised before comparison: upper-case, punctuation replaced by spaces, repeated whitespace collapsed, and transliteration variants considered.
4.2 A potential match is raised when the Jaro-Winkler similarity is 90 or more, or when the first and last name tokens are identical (covering abbreviated or omitted middle names such as "Viktor A. Morozkin").
4.3 **Disambiguation:** analysts compare secondary identifiers (date of birth, nationality, registration number, address). A match is "true", "false", or "inconclusive". Inconclusive matches are escalated to the MLRO.
4.4 **True match to a TFS list:** freeze funds and stop the transaction without delay and without prior notice to the customer; report to the competent authority (for example, the UAE Executive Office for Control and Non-Proliferation) and the Central Bank as required; do not tip off.
4.5 **Internal blacklist match:** reject the payment and escalate to Compliance.

## 5. Jurisdiction restrictions
5.1 **PROHIBITED tier** (jurisdictions subject to a FATF call for action in the Bank's illustrative risk table, for example Iran, North Korea and Myanmar): no payments without written MLRO approval; any attempted payment raises TM-04 and is reviewed for sanctions evasion.
5.2 **HIGH tier** (jurisdictions under increased monitoring or with elevated sanctions or terrorism risk): EDD on the relationship; cumulative monthly flows of AED 100,000 or more raise TM-04.
5.3 Remittances for family support to restricted corridors must go through licensed exchange houses that hold the relevant permissions.

## 6. Evidence and records
All screening decisions, with the evidence and the analyst's rationale, are recorded in the case management system and kept for at least five years.
