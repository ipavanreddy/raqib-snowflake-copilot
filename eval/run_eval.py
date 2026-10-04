"""
Raqib copilot evaluation.

  python eval/run_eval.py --connection raqib   # live Cortex Agent via SNOWFLAKE.CORTEX.DATA_AGENT_RUN
  python eval/run_eval.py --offline            # offline copilot (DuckDB replica)

Writes eval/results_<mode>.json and prints a scorecard. In Snowflake mode results are also
stored in RAQIB.OPS.EVAL_RESULTS so judges can see test evidence inside the platform.
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((ROOT / "eval" / "golden_questions.yaml").read_text())


def check(answer: str, case: dict) -> list[str]:
    fails = []
    low = answer.lower()
    for alt in case.get("must_contain", []):
        if not any(a.lower() in low for a in alt.split("|")):
            fails.append(f"missing: {alt}")
    for bad in case.get("must_not_contain", []):
        if bad.lower() in low:
            fails.append(f"forbidden: {bad}")
    return fails


def ask_live(session, q: str) -> str:
    body = json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": q}]}]})
    raw = session.sql("SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN('RAQIB.AI.RAQIB_COPILOT', ?) AS R", params=[body]).collect()[0]["R"]
    data = json.loads(raw)
    content = data.get("content") or data.get("message", {}).get("content", [])
    parts = []
    for c in content:
        if c.get("type") == "text":
            parts.append(c.get("text", ""))
        elif c.get("type") == "tool_result":  # include tool output so facts in tables count
            parts.append(json.dumps(c.get("tool_result", c), default=str)[:4000])
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--connection", default=None)
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    mode = "offline" if a.offline or not a.connection else "live"
    if mode == "live":
        from snowflake.snowpark import Session
        session = Session.builder.config("connection_name", a.connection).create()
        ask = lambda q: ask_live(session, q)  # noqa: E731
    else:
        os.environ["RAQIB_OFFLINE"] = "1"
        sys.path.insert(0, str(ROOT / "app"))
        from lib.backend import OfflineBackend
        from lib.offline_copilot import answer
        be = OfflineBackend()

        def ask(q):
            r = answer(be, q)
            tables = "\n".join(t.to_csv(index=False) for t in r.get("tables", []))
            cites = "\n".join(c.get("text", "") for c in r.get("citations", []))
            return r["text"] + "\n" + tables + "\n" + cites

    results = []
    for case in CASES:
        t = time.time()
        try:
            ans = ask(case["question"])
            fails = check(ans, case)
        except Exception as e:  # noqa: BLE001
            ans, fails = "", [f"error: {e}"]
        results.append({"id": case["id"], "question": case["question"], "passed": not fails, "failures": fails,
                        "latency_s": round(time.time() - t, 1), "answer_excerpt": re.sub(r"\s+", " ", ans)[:500]})
        print(f"{'PASS' if not fails else 'FAIL'}  {case['id']}  {case['question'][:70]}  {'; '.join(fails)}")
    score = sum(r["passed"] for r in results) / len(results)
    print(f"\nScore: {score:.0%} ({sum(r['passed'] for r in results)}/{len(results)}) — mode={mode}")
    out = ROOT / "eval" / f"results_{mode}.json"
    out.write_text(json.dumps({"run_at": datetime.utcnow().isoformat(), "mode": mode, "score": score, "results": results}, indent=2))
    if mode == "live":
        session.sql("""CREATE TABLE IF NOT EXISTS RAQIB.OPS.EVAL_RESULTS (RUN_AT TIMESTAMP_NTZ, CASE_ID VARCHAR, QUESTION VARCHAR,
                       PASSED BOOLEAN, FAILURES VARIANT, LATENCY_S FLOAT, ANSWER_EXCERPT VARCHAR)""").collect()
        for r in results:
            session.sql("""INSERT INTO RAQIB.OPS.EVAL_RESULTS SELECT CURRENT_TIMESTAMP(), ?, ?, ?, PARSE_JSON(?), ?, ?""",
                        params=[r["id"], r["question"], r["passed"], json.dumps(r["failures"]), r["latency_s"], r["answer_excerpt"]]).collect()
    sys.exit(0 if score >= 0.8 else 1)


if __name__ == "__main__":
    main()
