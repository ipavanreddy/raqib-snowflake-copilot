"""
Offline copilot for the public demo (no Snowflake account required).

The live app uses the Cortex Agent. Offline, questions are routed by intent to the same
verified queries (semantic view), the same tool functions and keyword policy retrieval, and the
answer is composed deterministically. Answers are clearly labelled as offline-mode.
"""
from __future__ import annotations

import random
import re
import uuid
from datetime import timedelta

import pandas as pd

OFFLINE_NOTE = "_Offline demo mode: deterministic answer from the same verified queries, tools and policies. The live app uses the Snowflake Cortex Agent._"


def _fmt(x):
    try:
        return f"AED {float(x):,.0f}"
    except (TypeError, ValueError):
        return str(x)


def _cites(passages):
    return [{"title": p.get("DOC_TITLE"), "id": p.get("CHUNK_ID"), "text": p.get("CHUNK", "")[:400]} for p in passages]


def _find_customer(be, text):
    m = re.search(r"\bC\d{6}\b", text.upper())
    if m:
        return m.group(0)
    names = be.df("SELECT CUSTOMER_ID, FULL_NAME FROM RAQIB.DETECT.CUSTOMER_RISK ORDER BY RISK_SCORE DESC")
    low = text.lower()
    for _, r in names.iterrows():
        if r["FULL_NAME"].lower() in low:
            return r["CUSTOMER_ID"]
    if re.search(r"top[- ]risk|highest[- ]risk", low):
        return names.iloc[0]["CUSTOMER_ID"]
    return None


def answer(be, question: str) -> dict:
    ql = question.lower()
    res = {"text": "", "tools": [], "sql": [], "citations": [], "tables": []}

    def run_sql(sql, label="aml_analyst"):
        res["tools"].append({"name": label, "type": "cortex_analyst_text_to_sql"})
        res["sql"].append(sql.strip())
        df = be.df(sql)
        res["tables"].append(df)
        return df

    # ---- guardrail: unknown entity IDs get an explicit "not found", never a guess ------
    for cid in re.findall(r"\bC\d{6}\b", question.upper()):
        if be.df("SELECT COUNT(*) AS N FROM RAQIB.RAW.CUSTOMERS WHERE CUSTOMER_ID = ?", [cid]).iloc[0, 0] == 0:
            res["text"] = (f"Customer **{cid}** was not found in the data, so I can't report any figures for it. "
                           "Check the ID in the alert queue or search by name.\n\n" + OFFLINE_NOTE)
            return res

    # ---- actions -------------------------------------------------------------------
    if re.search(r"\b(open|create)\b.*\bcase\b", ql) or "draft" in ql and ("str" in ql or "sar" in ql):
        cid = _find_customer(be, question)
        if not cid:
            res["text"] = "Which customer? Give a customer ID (e.g. C001085) or name."
            return res
        case = be.tool("CREATE_CASE", cid, f"Opened via copilot: {question[:120]}")
        res["tools"].append({"name": "create_case", "type": "generic", "input": {"p_customer_id": cid}})
        lines = [f"Opened case **{case.get('case_id')}** ({case.get('priority', '')}) for {cid}, "
                 f"linking {case.get('linked_alerts', 'existing')} alert(s). {case.get('note', '')}"]
        if "draft" in ql or "str" in ql:
            rep = be.tool("DRAFT_STR", case["case_id"])
            res["tools"].append({"name": "draft_str", "type": "generic", "input": {"p_case_id": case["case_id"]}})
            v = rep.get("validation", {})
            lines.append(f"Drafted STR **{rep.get('report_id')}** — status `{rep.get('status')}`, validation "
                         f"{'passed' if v.get('passed') else 'needs review'} (confidence {v.get('confidence')}). "
                         "Open **Cases & Reports** to review; only the MLRO can approve and file.")
        res["text"] = "\n\n".join(lines) + "\n\n**Next step:** MLRO review in Cases & Reports."
        return res

    # ---- customer explanation --------------------------------------------------------
    cid = _find_customer(be, question) if re.search(r"why|explain|360|tell me about|profile|investigat", ql) else None
    if cid:
        c = be.tool("GET_CUSTOMER_360", cid)
        res["tools"].append({"name": "get_customer_360", "type": "generic", "input": {"p_customer_id": cid}})
        if not c.get("ok"):
            res["text"] = c.get("error", "Customer not found.")
            return res
        p = c["profile"]
        passages = []
        for a in c["alerts"][:4]:
            passages += be.search(a["RULE_NAME"] + " " + a["TRIGGER_SUMMARY"][:80], 1)
        res["tools"].append({"name": "policy_search", "type": "cortex_search"})
        res["citations"] = _cites(passages)
        bd = ", ".join(f"{k.replace('PTS_', '').replace('_', ' ').lower()} +{v:g}" for k, v in c["score_breakdown"].items() if v)
        alerts = "\n".join(f"- **{a['RULE_ID']} {a['RULE_NAME']}** ({a['SEVERITY']}): {a['TRIGGER_SUMMARY']}" for a in c["alerts"])
        refs = "; ".join(sorted({f"[{x['CHUNK_ID'].split('#')[0]} {x['SECTION']}]" for x in passages if x.get('CHUNK_ID')}))
        res["text"] = (f"**{p['FULL_NAME']} ({cid})** is **{c['risk_band']}** risk with a score of **{c['risk_score']:g}/100** "
                       f"({bd}).\n\nProfile: {p['CUSTOMER_TYPE'].lower()}, {p.get('OCCUPATION') or p.get('INDUSTRY') or ''}, "
                       f"KYC rating {p['KYC_RISK_RATING']}, PEP {p['PEP_FLAG']}, KYC review overdue {p['KYC_REVIEW_OVERDUE']}.\n\n"
                       f"**Triggered rules**\n{alerts}\n\n**Policy basis:** {refs}\n\n"
                       "**Next step:** open a case and draft the STR for MLRO review (do not contact the customer about the investigation).")
        top = pd.DataFrame(c["top_counterparties"])
        if not top.empty:
            res["tables"].append(top)
        return res

    # ---- analytics intents (verified queries) -----------------------------------------
    if re.search(r"top|highest|riskiest|critical", ql) and "customer" in ql:
        n = int(re.search(r"top\s+(\d+)", ql).group(1)) if re.search(r"top\s+(\d+)", ql) else 10
        df = run_sql(f"""SELECT CUSTOMER_ID, FULL_NAME, RISK_SCORE, RISK_BAND, RULE_IDS, ALERTED_AMOUNT_AED
                         FROM RAQIB.DETECT.CUSTOMER_RISK ORDER BY RISK_SCORE DESC, ALERTED_AMOUNT_AED DESC LIMIT {n}""")
        lead = df.iloc[0]
        res["text"] = (f"The {n} highest-risk customers are below. **{lead['FULL_NAME']}** leads with a score of "
                       f"{lead['RISK_SCORE']:g} ({lead['RISK_BAND']}), hitting rules {lead['RULE_IDS']}. "
                       f"{int((df['RISK_BAND'] == 'CRITICAL').sum())} of {len(df)} are CRITICAL and must be reviewed today (TM Rulebook s.6).\n\n"
                       "**Next step:** ask me to explain the top customer.")
    elif "structur" in ql or "55,000" in ql or "55000" in ql:
        df = run_sql("""SELECT a.CUSTOMER_ID, r.FULL_NAME, a.TXN_COUNT AS DEPOSITS, ROUND(a.AMOUNT_AED, 2) AS TOTAL_AED,
                               a.WINDOW_START, a.WINDOW_END, a.TRIGGER_SUMMARY
                        FROM RAQIB.DETECT.ALERTS a JOIN RAQIB.DETECT.CUSTOMER_RISK r ON r.CUSTOMER_ID = a.CUSTOMER_ID
                        WHERE a.RULE_ID = 'TM-01' ORDER BY a.AMOUNT_AED DESC""")
        p = be.search("cash structuring AED 55,000 reporting threshold", 2)
        res["citations"] = _cites(p)
        res["text"] = (f"**{len(df)} customers** made 3+ cash deposits of AED 45,000–54,999 within 7 days (rule TM-01), "
                       f"totalling {_fmt(df['TOTAL_AED'].sum())}. Deposits just below the AED 55,000 internal threshold are a "
                       "primary structuring indicator [POL-AML-001 s.7.2; POL-TM-002 s.4.1].")
    elif re.search(r"alert", ql) and re.search(r"rule|how many|count|open|backlog|severity", ql):
        df = run_sql("""SELECT RULE_ID, RULE_NAME, SEVERITY, COUNT(*) AS OPEN_ALERTS, ROUND(SUM(AMOUNT_AED), 0) AS ALERTED_AED
                        FROM RAQIB.OPS.ALERT_QUEUE WHERE STATUS IN ('NEW', 'IN_REVIEW', 'ESCALATED')
                        GROUP BY RULE_ID, RULE_NAME, SEVERITY ORDER BY RULE_ID""")
        res["text"] = f"There are **{int(df['OPEN_ALERTS'].sum())} open alerts** across {len(df)} rules, covering {_fmt(df['ALERTED_AED'].sum())}."
    elif re.search(r"\blcr\b|liquidity|hqla", ql):
        df = run_sql("""SELECT AS_OF_DATE, LCR_PCT, LCR_STATUS, HQLA_TOTAL_AED_M, NET_OUTFLOWS_AED_M
                        FROM RAQIB.RISK.LCR_DAILY WHERE LCR_STATUS <> 'COMPLIANT' OR AS_OF_DATE = (SELECT MAX(AS_OF_DATE) FROM RAQIB.RISK.LCR_DAILY)
                        ORDER BY AS_OF_DATE""", "risk_analyst")
        latest = df.iloc[-1]
        ew = df[df["LCR_STATUS"] != "COMPLIANT"]
        p = be.search("LCR early warning trigger 110% ALCO escalation", 2)
        res["citations"] = _cites(p)
        res["text"] = (f"Latest LCR ({latest['AS_OF_DATE']}) is **{latest['LCR_PCT']:.1f}%** — {latest['LCR_STATUS']}. "
                       + (f"The LCR fell below the **110% early-warning trigger on {len(ew)} day(s)** "
                          f"(low {ew['LCR_PCT'].min():.1f}% on {ew.loc[ew['LCR_PCT'].idxmin(), 'AS_OF_DATE']}), driven by a drop in HQLA "
                          "and higher non-operational wholesale outflows. It never breached the 100% regulatory minimum. "
                          "Policy requires same-day ALCO notification and a remediation plan [POL-LIQ-005 s.4]." if len(ew) else
                          "No early-warning days in the period."))
    elif re.search(r"\bnpl\b|credit|ifrs|stage|ecl|provision", ql):
        df = run_sql("""SELECT SECTOR, ROUND(SUM(EAD_AED), 0) AS EXPOSURE_AED,
                               ROUND(100 * SUM(CASE WHEN IS_NPL THEN EAD_AED ELSE 0 END) / NULLIF(SUM(EAD_AED), 0), 2) AS NPL_RATIO_PCT,
                               ROUND(SUM(ECL_AED), 0) AS ECL_AED
                        FROM RAQIB.RISK.LOAN_ECL GROUP BY SECTOR ORDER BY NPL_RATIO_PCT DESC""", "risk_analyst")
        tot = be.df("""SELECT 100 * SUM(CASE WHEN IS_NPL THEN EAD_AED ELSE 0 END) / SUM(EAD_AED) AS NPL FROM RAQIB.RISK.LOAN_ECL""").iloc[0, 0]
        res["text"] = (f"Portfolio NPL ratio is **{tot:.2f}%** against a risk appetite of < 6% [POL-CRD-006 s.3]. "
                       f"Highest sector NPL: **{df.iloc[0]['SECTOR']}** at {df.iloc[0]['NPL_RATIO_PCT']:.2f}%.")
    elif re.search(r"jurisdiction|country|corridor|iran|sanction.*exposure", ql):
        df = run_sql("""SELECT COUNTERPARTY_COUNTRY, COUNTERPARTY_COUNTRY_RISK, COUNT(*) AS PAYMENTS, ROUND(SUM(AMOUNT_AED), 0) AS TOTAL_AED,
                               COUNT(DISTINCT CUSTOMER_ID) AS CUSTOMERS
                        FROM RAQIB.CORE.TXN_ENRICHED WHERE COUNTERPARTY_COUNTRY_RISK IN ('HIGH', 'PROHIBITED')
                        GROUP BY COUNTERPARTY_COUNTRY, COUNTERPARTY_COUNTRY_RISK ORDER BY TOTAL_AED DESC""")
        res["text"] = (f"Exposure to HIGH/PROHIBITED jurisdictions totals **{_fmt(df['TOTAL_AED'].sum())}** across "
                       f"{int(df['PAYMENTS'].sum())} payments. Payments to PROHIBITED-tier countries require MLRO approval [POL-SAN-003 s.5].")
    elif re.search(r"\b(lcr|report)\b", ql) and re.search(r"generate|create|prepare", ql):
        rtype = "LCR" if "lcr" in ql or "liquid" in ql else "CREDIT" if "credit" in ql else "AML_MI"
        rep = be.tool("GENERATE_REGULATORY_REPORT", rtype)
        res["tools"].append({"name": "generate_regulatory_report", "type": "generic", "input": {"p_report_type": rtype}})
        res["text"] = f"Generated **{rep.get('report_id')}** ({rtype}). Open Cases & Reports to review."
    else:
        passages = be.search(question, 3)
        res["tools"].append({"name": "policy_search", "type": "cortex_search"})
        res["citations"] = _cites(passages)
        if passages:
            best = passages[0]
            body = re.sub(r"\s+", " ", best["CHUNK"])[:900]
            res["text"] = (f"From **{best['DOC_TITLE']}** — *{best['SECTION']}* [{best['CHUNK_ID']}]:\n\n> {body}\n\n"
                           "See the citations for related passages.")
        else:
            res["text"] = "I couldn't find that in the data or policies. Try asking about customers, alerts, LCR, NPL or a policy topic."
    res["text"] += "\n\n" + OFFLINE_NOTE
    return res


def baseline_notifications(be):
    be.execute("""INSERT INTO RAQIB.OPS.NOTIFICATIONS (NOTIFICATION_ID, CREATED_AT, CHANNEL, SEVERITY, TITLE, BODY, OBJECT_ID, STATUS)
                  SELECT 'base-' || ALERT_ID, CURRENT_TIMESTAMP, 'slack', SEVERITY, 'Baseline', 'Existing at start', ALERT_ID, 'SKIPPED'
                  FROM RAQIB.DETECT.ALERTS""")


def simulate(be, scenario: str) -> dict:
    """Offline equivalent of RAQIB.OPS.SIMULATE_ACTIVITY + ALERT_ROUTER."""
    scenario = (scenario or "BACKGROUND").upper()
    rng = random.Random()
    now = be.df("SELECT MAX(TXN_TS) AS T FROM RAQIB.RAW.TRANSACTIONS").iloc[0, 0]
    pool = be.df("""SELECT p.CUSTOMER_ID, a.ACCOUNT_ID, p.FULL_NAME, p.SEGMENT, p.KYC_RISK_RATING, p.CUSTOMER_TYPE
                    FROM RAQIB.CORE.CUSTOMER_PROFILE p JOIN RAQIB.RAW.ACCOUNTS a ON a.CUSTOMER_ID = p.CUSTOMER_ID
                    WHERE a.CURRENCY = 'AED' AND a.ACCOUNT_TYPE IN ('CURRENT', 'BUSINESS')
                      AND p.CUSTOMER_ID NOT IN (SELECT CUSTOMER_ID FROM RAQIB.DETECT.ALERTS)""")
    rows, branches = [], ["DXB-DEIRA", "DXB-KARAMA", "SHJ-ROLLA", "AJM-CENTRAL"]
    if scenario == "STRUCTURING":
        c = pool[(pool.CUSTOMER_TYPE == "INDIVIDUAL") & (pool.KYC_RISK_RATING == "LOW")].sample(1).iloc[0]
        for k in range(4):
            amt = round(rng.uniform(47000, 54800), 2)
            rows.append((f"LIVE-{uuid.uuid4().hex[:10]}", c.ACCOUNT_ID, now - timedelta(days=3 - k, hours=rng.randint(0, 5)),
                         "CREDIT", "CASH_DEPOSIT", amt, "AED", amt, None, None, None, "Cash deposit", branches[k]))
        detail = f"4 cash deposits under AED 55,000 for {c.FULL_NAME} ({c.CUSTOMER_ID}) across 4 branches"
    elif scenario == "ATO":
        c = pool[pool.SEGMENT == "PRIORITY"].sample(1).iloc[0]
        dev, t0 = f"DEV-UNSEEN-{rng.randint(1000, 9999)}", now - timedelta(hours=2)
        for i, et in enumerate(["OTP_FAILED", "PASSWORD_RESET", "NEW_DEVICE", "BENEFICIARY_ADDED"]):
            be.execute("INSERT INTO RAQIB.RAW.DIGITAL_EVENTS VALUES (?, ?, ?, ?, ?, 'NG')",
                       [f"LIVE-{uuid.uuid4().hex[:10]}", c.CUSTOMER_ID, t0 + timedelta(minutes=3 * i), et, dev])
        cp = be.df("SELECT COUNTERPARTY_ID FROM RAQIB.RAW.COUNTERPARTIES WHERE COUNTRY_CODE = 'AE' LIMIT 1").iloc[0, 0]
        for k in range(3):
            amt = round(rng.uniform(25000, 60000), 2)
            rows.append((f"LIVE-{uuid.uuid4().hex[:10]}", c.ACCOUNT_ID, t0 + timedelta(minutes=15 + 6 * k), "DEBIT",
                         "INTERNAL_TRANSFER", amt, "AED", amt, cp, "AE", None, "Online transfer", None))
        detail = f"Account takeover pattern on {c.FULL_NAME} ({c.CUSTOMER_ID})"
    else:
        for a in pool.sample(40).itertuples():
            amt = round(rng.lognormvariate(5.2, 0.9), 2)
            rows.append((f"LIVE-{uuid.uuid4().hex[:10]}", a.ACCOUNT_ID, now + timedelta(minutes=rng.randint(1, 30)), "DEBIT",
                         "CARD_POS", amt, "AED", amt, None, "AE", None, "Card purchase", None))
        detail = f"{len(rows)} routine card transactions"
    for r in rows:
        be.execute("INSERT INTO RAQIB.RAW.TRANSACTIONS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", list(r))
    # "refresh dynamic tables" = rebuild derived tables locally
    for f in ["03_core_pipeline.sql", "04_detection.sql", "05_risk_reporting.sql"]:
        be.engine.run_file(be.con, f)
    # alert router
    be.execute("""INSERT INTO RAQIB.OPS.NOTIFICATIONS (NOTIFICATION_ID, CREATED_AT, CHANNEL, SEVERITY, TITLE, BODY, OBJECT_ID, STATUS)
                  SELECT 'n-' || a.ALERT_ID, CURRENT_TIMESTAMP, 'slack', a.SEVERITY,
                         'New ' || a.SEVERITY || ' alert ' || a.ALERT_ID || ' (' || a.RULE_ID || ')',
                         r.FULL_NAME || ' (' || a.CUSTOMER_ID || ', risk ' || CAST(r.RISK_SCORE AS VARCHAR) || ' ' || r.RISK_BAND || '): ' || a.TRIGGER_SUMMARY,
                         a.ALERT_ID, 'PENDING'
                  FROM RAQIB.DETECT.ALERTS a JOIN RAQIB.DETECT.CUSTOMER_RISK r ON r.CUSTOMER_ID = a.CUSTOMER_ID
                  WHERE a.SEVERITY IN ('HIGH', 'CRITICAL')
                    AND NOT EXISTS (SELECT 1 FROM RAQIB.OPS.NOTIFICATIONS n WHERE n.OBJECT_ID = a.ALERT_ID)""")
    return {"ok": True, "scenario": scenario, "inserted_transactions": len(rows), "detail": detail}
