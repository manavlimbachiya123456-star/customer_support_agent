"""Support cases, chat messages, dashboard stats."""
import re

from db import db, new_id, utcnow

OPEN_STATUSES = ["OPEN", "PENDING_APPROVAL", "ESCALATED"]
SORT_FIELDS = {"created_at", "case_id", "priority", "status", "customer_name", "order_id", "category"}


# ------------------------------------------------------------ understanding the message
def detect_order_id(text: str):
    m = re.search(r"\bORD-\d{3,}\b", text or "", re.I)
    return m.group(0).upper() if m else None


def detect_issue(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"damag|broken|defect|cracked|torn", t):
        return "damaged"
    if re.search(r"missing|not all|incomplete|empty box", t):
        return "missing_item"
    if re.search(r"wrong (item|product|size|colour|color)|different item", t):
        return "wrong_item"
    return "none"


def classify(text: str) -> str:
    t = (text or "").lower()
    if not detect_order_id(text or "") and re.search(r"how (many|long)|what is (your|the)|policy|policies|do you (offer|accept)", t):
        return "POLICY"  # a general question about the rules, not about one order
    if re.search(r"refund|money back|reimburse", t):
        return "REFUND"
    if "cancel" in t:
        return "CANCELLATION"
    if re.search(r"address|change.*(delivery|shipping)", t):
        return "ADDRESS_CHANGE"
    if re.search(r"\breturn|exchange|send (it )?back", t):
        return "RETURN"
    if detect_issue(t) != "none":
        return "DAMAGED_OR_MISSING"
    if re.search(r"where|status|arriv|track|deliver|late|delay", t):
        return "DELIVERY"
    if re.search(r"policy|policies|how long|window|allowed|can i", t):
        return "POLICY"
    return "OTHER"


def priority_for(category: str) -> str:
    return {"REFUND": "HIGH", "DAMAGED_OR_MISSING": "HIGH", "CANCELLATION": "MEDIUM",
            "ADDRESS_CHANGE": "MEDIUM", "RETURN": "MEDIUM", "DELIVERY": "MEDIUM"}.get(category, "LOW")


# ------------------------------------------------------------ cases
def next_case_id() -> str:
    last = db.cases.find_one(sort=[("case_id", -1)])
    n = int(last["case_id"].split("-")[1]) + 1 if last else 1001
    return f"CASE-{n}"


def create_case(user: dict, message: str) -> dict:
    customer = db.customers.find_one({"customer_id": user["customer_id"]}) or {}
    category = classify(message)
    now = utcnow()
    case = {"case_id": next_case_id(), "customer_id": user["customer_id"],
            "customer_name": customer.get("name", user.get("name", "")),
            "order_id": detect_order_id(message), "category": category, "priority": priority_for(category),
            "status": "OPEN", "request": message[:1000], "assigned_agent": None, "created_at": now,
            "updated_at": now, "resolved_at": None, "investigation": None, "runs": 0}
    db.cases.insert_one(dict(case))
    return case


def get_case(case_id: str):
    return db.cases.find_one({"case_id": case_id}, {"_id": 0})


def set_status(case_id, status, **extra):
    fields = {"status": status, "updated_at": utcnow(), **extra}
    if status == "RESOLVED":
        fields.setdefault("resolved_at", utcnow())
    db.cases.update_one({"case_id": case_id}, {"$set": fields})


def add_message(case_id, role, text, meta=None):
    msg = {"message_id": new_id("MSG"), "case_id": case_id, "role": role, "text": text,
           "meta": meta or {}, "created_at": utcnow()}
    db.messages.insert_one(dict(msg))
    return msg


def messages(case_id):
    return list(db.messages.find({"case_id": case_id}, {"_id": 0}).sort("created_at", 1))


def history(case_id, limit=10):
    return [{"role": m["role"], "text": m["text"]} for m in messages(case_id)][-limit:]


STATUS_FOR_DECISION = {"PENDING_APPROVAL": "PENDING_APPROVAL", "ESCALATED": "ESCALATED",
                       "NEEDS_INFO": "OPEN", "ANSWERED": "RESOLVED", "INELIGIBLE": "RESOLVED"}


def apply_result(case_id, result: dict):
    """Save the agent's run on the case and move the case to the right status."""
    case = get_case(case_id)
    steps = result.get("steps", [])
    order_id = case.get("order_id")
    for s in steps:
        if not order_id and s["tool"] in ("get_order", "check_refund_eligibility") and s["args"].get("order_id"):
            order_id = str(s["args"]["order_id"]).upper()
    investigation = {k: result.get(k) for k in (
        "answer", "decision", "confidence", "uncertainties", "steps", "evidence", "policy_excerpts",
        "proposed_action")}
    investigation["model"] = result.get("model")
    investigation["ran_at"] = utcnow()
    status = STATUS_FOR_DECISION.get(result["decision"], "OPEN")
    set_status(case_id, status, order_id=order_id, investigation=investigation, runs=case.get("runs", 0) + 1,
               **({"resolved_at": None} if status != "RESOLVED" else {}))
    add_message(case_id, "assistant", result["answer"], {"decision": result["decision"]})


def notify_outcome(approval: dict):
    """After a human decision / execution, tell the customer the REAL result (never before)."""
    case_id = approval.get("case_id")
    if not case_id or not get_case(case_id):
        return
    status, kind, order = approval["status"], approval["type"], approval["order_id"]
    label = {"REFUND": "refund", "CANCEL_ORDER": "cancellation", "UPDATE_ORDER": "address change",
             "RETURN": "return"}[kind]
    if status == "COMPLETED":
        res = approval.get("execution_result") or {}
        extra = {"REFUND": lambda: f" of Rs {approval['amount']:.2f} (reference {res.get('txn_id')}). "
                                   "It usually reaches your account in 5-7 business days.",
                 "CANCEL_ORDER": lambda: ". Your order is now cancelled.",
                 "UPDATE_ORDER": lambda: ". Your delivery address has been updated.",
                 "RETURN": lambda: f". Return reference: {res.get('rma')}. A pickup will be arranged."}[kind]()
        text = f"Update on {order}: your {label} was approved and completed{extra}"
        set_status(case_id, "RESOLVED")
    elif status == "REJECTED":
        text = (f"Update on {order}: our team reviewed your {label} request and could not approve it. "
                f"Reason: {approval.get('decision_reason')}.")
        set_status(case_id, "RESOLVED")
    elif status == "FAILED":
        text = (f"Update on {order}: your {label} was approved but we hit a problem completing it. "
                "Nothing has been changed on your account. Our team is looking into it.")
        set_status(case_id, "ESCALATED")
    else:
        return
    add_message(case_id, "assistant", text, {"decision": status, "source": "system"})


# ------------------------------------------------------------ lists + stats
def list_cases(customer_id=None, q="", status="", priority="", category="", sort="created_at",
               order="desc", page=1, page_size=10):
    query = {}
    if customer_id:
        query["customer_id"] = customer_id
    if status:
        query["status"] = status
    if priority:
        query["priority"] = priority
    if category:
        query["category"] = category
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"case_id": rx}, {"customer_name": rx}, {"order_id": rx}, {"request": rx}]
    sort = sort if sort in SORT_FIELDS else "created_at"
    page, page_size = max(page, 1), min(max(page_size, 1), 50)
    total = db.cases.count_documents(query)
    cur = db.cases.find(query, {"_id": 0, "investigation": 0}).sort(sort, 1 if order == "asc" else -1)
    items = list(cur.skip((page - 1) * page_size).limit(page_size))
    return {"items": items, "total": total, "page": page, "pages": max(1, -(-total // page_size))}


def stats():
    total = db.cases.count_documents({})
    resolved = list(db.cases.find({"status": "RESOLVED", "resolved_at": {"$ne": None}}))
    hours = [(c["resolved_at"] - c["created_at"]).total_seconds() / 3600 for c in resolved]
    by_category, by_status = {}, {}
    for c in db.cases.find({}, {"category": 1, "status": 1}):
        by_category[c["category"]] = by_category.get(c["category"], 0) + 1
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
    return {
        "total_cases": total,
        "open_cases": db.cases.count_documents({"status": {"$in": OPEN_STATUSES}}),
        "pending_approvals": db.approvals.count_documents({"status": "PENDING_APPROVAL"}),
        "completed_cases": len(resolved),
        "refund_requests": db.approvals.count_documents({"type": "REFUND"}),
        "avg_resolution_hours": round(sum(hours) / len(hours), 1) if hours else 0,
        "by_category": [{"name": k, "value": v} for k, v in sorted(by_category.items())],
        "by_status": [{"name": k, "value": v} for k, v in sorted(by_status.items())],
    }
