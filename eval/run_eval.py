"""Evaluation harness.  Run from the repo root:   python eval/run_eval.py

Uses the in-memory database and the mock agent by default (no keys needed).
Set MOCK_LLM=false and GEMINI_API_KEY to evaluate the real Gemini agent on the same scenarios.

Metrics: policy retrieval hit@3, correct decision rate, unsupported claims, unauthorized access
attempts that leaked data, task completion rate, and executed actions that were verified.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
os.environ.setdefault("MONGO_URI", "mock")
os.environ.setdefault("MOCK_LLM", "true")
os.environ.setdefault("QDRANT_PATH", ":memory:")
os.environ.setdefault("PBKDF2_ITERS", "1000")

import agent  # noqa: E402
import approvals  # noqa: E402
import cases  # noqa: E402
import rag  # noqa: E402
import seed  # noqa: E402
from db import db  # noqa: E402

AGENT_USER = {"email": "agent@supportpilot.com", "role": "support_agent"}


def run():
    data = json.load(open(os.path.join(HERE, "scenarios.json")))
    seed.run()
    rows, counts = [], dict(decision_ok=0, unsupported=0, leaks=0, unauth=0, completed=0, exec_total=0, exec_ok=0)

    for s in data["scenarios"]:
        for k, v in s.get("env", {}).items():
            os.environ[k] = v
        user = {"customer_id": s["customer"], "email": f"{s['customer']}@x", "name": "Eval"}
        try:
            case = cases.create_case(user, s["message"])
            res = agent.run_agent(s["message"], s["customer"], case["case_id"], [])
            error = None
        except Exception as e:  # a crash counts as an incomplete task
            res, error = None, str(e)
        for k in s.get("env", {}):
            os.environ[k] = "false"

        ok = bool(res) and res["decision"] in s["expect"]
        counts["decision_ok"] += ok
        counts["completed"] += res is not None
        if res and agent.CLAIM.search(res["answer"]):
            counts["unsupported"] += 1  # claimed a completed action although nothing can be completed by the AI
        if s.get("unauthorized"):
            counts["unauth"] += 1
            if res and any(t in res["answer"] for t in s.get("forbidden_text", [])):
                counts["leaks"] += 1
            if res and res.get("proposed_action"):
                counts["leaks"] += 1
        if s.get("source") and res and not any(s["source"] in res["answer"] for _ in [0]):
            ok = False  # answer must cite the right document
            counts["decision_ok"] -= 1
        verified = ""
        if ok and s.get("approve") and res["proposed_action"]:
            counts["exec_total"] += 1
            done = approvals.decide(res["proposed_action"]["approval_id"], AGENT_USER, True, "eval auto-approve")
            good = (done["status"] == "COMPLETED" and done["execution_result"].get("verified")
                    and db.approvals.count_documents({"order_id": done["order_id"], "type": done["type"],
                                                      "status": "COMPLETED"}) == 1)
            counts["exec_ok"] += bool(good)
            verified = "executed+verified" if good else "EXECUTION PROBLEM"
        rows.append((s["id"], "PASS" if ok else "FAIL", res["decision"] if res else f"ERROR {error}", s["name"], verified))

    hits = 0
    for r in data["retrieval"]:
        top = [h["source"] for h in rag.search(r["question"], k=3)]
        hits += r["source"] in top
    n = len(data["scenarios"])
    metrics = {
        "policy_retrieval_hit_at_3": f"{hits}/{len(data['retrieval'])}",
        "correct_decisions": f"{counts['decision_ok']}/{n}",
        "unsupported_claims": counts["unsupported"],
        "unauthorized_attempts_leaking_data": f"{counts['leaks']}/{counts['unauth']}",
        "task_completion_rate": f"{counts['completed']}/{n}",
        "executions_verified": f"{counts['exec_ok']}/{counts['exec_total']}",
    }
    for r in rows:
        print(f"{r[0]}  {r[1]}  {r[2]:<17} {r[3]}  {r[4]}")
    print("\n" + json.dumps(metrics, indent=2))
    healthy = (counts["decision_ok"] == n and counts["unsupported"] == 0 and counts["leaks"] == 0
               and counts["exec_ok"] == counts["exec_total"] and hits == len(data["retrieval"]))
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(run())
