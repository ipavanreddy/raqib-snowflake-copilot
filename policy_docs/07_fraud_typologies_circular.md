---
doc_id: POL-FRD-007
title: Fraud Typologies Circular — Digital Banking
owner: Head of Fraud Risk
version: 1.6
effective_date: 2026-05-10
classification: Internal
---

# Gulf Horizon Bank — Fraud Typologies Circular

> Synthetic document created for the Raqib hackathon demo. Gulf Horizon Bank is fictional.

## 1. Purpose
To brief fraud, operations and compliance teams on current digital-banking fraud typologies and the controls that detect them.

## 2. Account takeover (ATO)
**Modus operandi:** criminals phish credentials or perform a SIM swap, trigger OTP failures and a password reset, enrol a new device (often from an IP address outside the UAE, at night), add a new beneficiary, and drain the account through several transfers within minutes.
**Indicators:** a device first seen less than 24 hours before the beneficiary is added; a foreign IP address; a password reset or OTP failure in the prior hour; several high-value transfers soon after the beneficiary is added.
**Detection:** rule FR-01.
**Response:** block digital access; contact the customer through the registered phone number; send a funds recall request to the beneficiary bank within 1 hour; report the mule beneficiary account for TM-03 review.

## 3. Money mules
**Modus operandi:** students, newly arrived workers, or people looking for "easy jobs" are recruited on social media to receive and forward funds, often the proceeds of scams. Mule accounts are typically less than 90 days old, receive many small transfers from unrelated individuals, and forward funds to a collector account or withdraw cash.
**Indicators:** 10 or more distinct senders within 7 days; payment descriptions such as "gift", "rent share" or "loan"; onward transfer of 80% or more within 3 days; several mule accounts paying the same collector.
**Detection:** rule TM-03, plus network analysis of shared beneficiaries.
**Response:** restrict the account, interview the customer, file an STR, and trace the collector.

## 4. Authorised push payment (APP) scams
Victims are persuaded to send money themselves (fake investments, impersonation of government or bank staff). Look for first-time beneficiaries, unusual amounts, and customer distress noted by the branch. The receiving accounts often show mule patterns.

## 5. Customer communication
Fraud victims must be supported. Mule-account holders under investigation must **not** be told about any AML suspicion or STR (tipping-off prohibition, AML/CFT Policy s.8.3).
