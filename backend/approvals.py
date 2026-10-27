"""Human approval + safe execution of sensitive actions.

State machine:  PROPOSED -> PENDING_APPROVAL -> APPROVED | REJECTED -> EXECUTING -> COMPLETED | FAILED

The AI can only call propose(). Only decide() (a logged-in support agent) can approve, and only
execute() changes orders or moves (fake) money.
"""
import hashlib
import json
import logging
import re

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

import audit
import cases
import rules
import services
from db import db, new_id, utcnow

log = logging.getLogger("supportpilot")

ALLOWED = {
    "PROPOSED": ["PENDING_APPROVAL"],
    "PENDING_APPROVAL": ["APPROVED", "REJECTED"],
    "APPROVED": ["EXECUTING"],
    "EXECUTING": ["COMPLETED", "FAILED"],
    "FAILED": ["APPROVED"],  # only through retry() for transient errors
}


class PermissionDenied(Exception):
    pass


class InvalidTransition(Exception):
    pass


class NotFound(Exception):
    pass


class ExecutionError(Exception):
    def __init__(self, message, kind="permanent"):
        super().__init__(message)
        self.kind = kind  # "transient" can be retried, "permanent" cannot


# ------------------------------------------------------------------ helpers
def compute_hash(a: dict) -> str:
    """Fingerprint of the exact action. Approval is only valid for this fingerprint."""
    payload = {k: a.get(k) for k in ("type", "order_id", "customer_id", "amount", "reason", "params")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def get(approval_id: str):
    a = db.approvals.find_one({"approval_id": approval_id}, {"_id": 0})
    if not a:
        raise NotFound("Approval not found")
    return a


def public(a: dict) -> dict:
    keep = ("approval_id", "type", "order_id", "amount", "reason", "status", "decision_reason", "created_at")
    return {k: a.get(k) for k in keep}


def _sync_child(a: dict):
    """Keep the RefundRequest / ReturnRequest records in step with the approval."""
    coll = {"REFUND": db.refunds, "RETURN": db.returns}.get(a["type"])
    if coll is not None:
        fields = {"status": a["status"], "updated_at": utcnow()}
        res = a.get("execution_result") or {}
        if res.get("txn_id"):
            fields["txn_id"] = res["txn_id"]
        if res.get("rma"):
            fields["rma"] = res["rma"]
        coll.update_one({"request_id": a["approval_id"]}, {"$set": fields})


def _transition(approval_id, expected, new, by, note="", extra=None):
    """Atomic state change. Fails if the approval is not in the expected state."""
    if new not in ALLOWED.get(expected, []):
        raise InvalidTransition(f"{expected} -> {new} is not allowed")
    now = utcnow()
    res = db.approvals.find_one_and_update(
        {"approval_id": approval_id, "status": expected},
        {"$set": {"status": new, "updated_at": now, **(extra or {})},
         "$push": {"history": {"status": new, "ts": now, "by": by, "note": note}}},
        return_document=ReturnDocument.AFTER)
    if not res:
        raise InvalidTransition(f"Approval is not in state {expected}")
    res.pop("_id", None)  # (no projection: mongomock returns None when one is used)
    _sync_child(res)
    return res


def make_doc(kind, order, case_id, params, reason, amount, evidence, policy_excerpts, key, status):
    now = utcnow()
    doc = {"approval_id": new_id("APR"), "type": kind, "order_id": order["order_id"],
           "customer_id": order["customer_id"], "case_id": case_id, "params": params, "reason": reason,
           "amount": amount, "evidence": evidence, "policy_excerpts": policy_excerpts,
           "idempotency_key": key, "status": status, "attempts": 0, "created_at": now, "updated_at": now,
           "history": [{"status": "PROPOSED", "ts": now, "by": "ai-agent", "note": ""}]}
    if status != "PROPOSED":
        doc["history"].append({"status": status, "ts": now, "by": "ai-agent", "note": ""})
    doc["proposal_hash"] = compute_hash(doc)
    return doc


# ------------------------------------------------------------------ 1. propose (the AI can do this)
def propose(kind, order, case_id, params, reason, amount, evidence, policy_excerpts):
    """Create a pending request. Nothing is executed here. Duplicates return the existing request."""
    existing = db.approvals.find_one({"order_id": order["order_id"], "type": kind,
                                      "status": {"$in": list(rules.BLOCKING)}}, {"_id": 0})
    if existing:
        return {"created": False, "approval": existing}

    n = db.approvals.count_documents({"order_id": order["order_id"], "type": kind})
    key = f"{kind}:{order['order_id']}:{n}"
    doc = make_doc(kind, order, case_id, params, reason, amount, evidence, policy_excerpts, key,
                   "PENDING_APPROVAL")
    try:
        db.approvals.insert_one(dict(doc))
    except DuplicateKeyError:  # two requests at the same moment: the unique key lets only one in
        return {"created": False, "approval": db.approvals.find_one({"idempotency_key": key}, {"_id": 0})}

    if kind == "REFUND":
        db.refunds.insert_one({"request_id": doc["approval_id"], "order_id": doc["order_id"],
                               "customer_id": doc["customer_id"], "amount": amount, "reason": reason,
                               "status": "PENDING_APPROVAL", "created_at": utcnow(), "updated_at": utcnow()})
    elif kind == "RETURN":
        db.returns.insert_one({"request_id": doc["approval_id"], "order_id": doc["order_id"],
                               "customer_id": doc["customer_id"], "reason": reason,
                               "status": "PENDING_APPROVAL", "created_at": utcnow(), "updated_at": utcnow()})
    audit.log(case_id, "approvals.propose", f"propose_{kind.lower()}", {"order_id": doc["order_id"], "amount": amount},
              {"approval_id": doc["approval_id"]}, approval_status="PENDING_APPROVAL")
    return {"created": True, "approval": doc}


# ------------------------------------------------------------------ 2. decide (humans only)
def _require_agent(user):
    if not user or user.get("role") not in ("support_agent", "admin"):
        raise PermissionDenied("Only support agents can do this")


def decide(approval_id: str, user: dict, approve: bool, reason: str):
    _require_agent(user)
    if not reason or len(reason.strip()) < 3:
        raise ValueError("A reason is required")
    a = get(approval_id)
    if a["status"] != "PENDING_APPROVAL":
        raise InvalidTransition(f"Approval is {a['status']}, not PENDING_APPROVAL")
    if compute_hash(a) != a["proposal_hash"]:
        raise ValueError("The proposal data does not match its fingerprint. Refusing to approve.")

    by = user["email"]
    if not approve:
        a = _transition(approval_id, "PENDING_APPROVAL", "REJECTED", by, reason,
                        {"decided_by": by, "decision_reason": reason.strip(), "decided_at": utcnow()})
        audit.log(a["case_id"], "approvals.decide", "reject", {"approval_id": approval_id, "reason": reason},
                  actor=by, approval_status="REJECTED")
        _assign(a, by)
        cases.notify_outcome(a)
        return a

    a = _transition(approval_id, "PENDING_APPROVAL", "APPROVED", by, reason,
                    {"decided_by": by, "decision_reason": reason.strip(), "decided_at": utcnow(),
                     "approved_hash": a["proposal_hash"]})
    audit.log(a["case_id"], "approvals.decide", "approve", {"approval_id": approval_id, "reason": reason},
              actor=by, approval_status="APPROVED")
    _assign(a, by)
    return execute(approval_id, by)


def _assign(a, by):
    if a.get("case_id"):
        db.cases.update_one({"case_id": a["case_id"], "assigned_agent": None}, {"$set": {"assigned_agent": by}})


# ------------------------------------------------------------------ 3. execute
def _blocking_other(a, kind):
    return db.approvals.find_one({"order_id": a["order_id"], "type": kind,
                                  "approval_id": {"$ne": a["approval_id"]},
                                  "status": {"$in": list(rules.BLOCKING)}})


def _do_refund(a):
    order = db.orders.find_one({"order_id": a["order_id"]})
    check = rules.check_refund(order, services.get_shipment(a["order_id"]), _blocking_other(a, "REFUND"),
                               (a["params"] or {}).get("issue", "none"))
    if not check["eligible"]:
        raise ExecutionError("No longer eligible: " + check["reason"], "permanent")
    if not (0 < a["amount"] <= order["total"]):
        raise ExecutionError("Refund amount is invalid", "permanent")

    payment = services.process_refund(a["amount"], a["idempotency_key"], a["order_id"])
    db.orders.update_one({"order_id": a["order_id"]}, {"$set": {"status": "REFUNDED", "updated_at": utcnow()}})

    # verify the REAL result instead of trusting the call
    pay = services.get_payment(a["idempotency_key"])
    now_order = db.orders.find_one({"order_id": a["order_id"]})
    if not (pay and pay["status"] == "SUCCEEDED" and abs(pay["amount"] - a["amount"]) < 0.01
            and now_order["status"] == "REFUNDED"):
        raise ExecutionError("Refund could not be verified. Needs reconciliation.", "permanent")
    return {"txn_id": payment["txn_id"], "amount": a["amount"], "verified": True}


def _do_cancel(a):
    order = db.orders.find_one({"order_id": a["order_id"]})
    check = rules.can_cancel(order, _blocking_other(a, "CANCEL_ORDER"))
    if not check["eligible"]:
        raise ExecutionError("No longer cancellable: " + check["reason"], "permanent")
    db.orders.update_one({"order_id": a["order_id"]}, {"$set": {"status": "CANCELLED", "updated_at": utcnow()}})
    if db.orders.find_one({"order_id": a["order_id"]})["status"] != "CANCELLED":
        raise ExecutionError("Cancellation could not be verified.", "permanent")
    return {"verified": True}


def _do_update(a):
    order = db.orders.find_one({"order_id": a["order_id"]})
    check = rules.can_update_address(order, _blocking_other(a, "UPDATE_ORDER"))
    if not check["eligible"]:
        raise ExecutionError("Address can no longer be changed: " + check["reason"], "permanent")
    new_addr = a["params"]["new_shipping_address"]
    db.orders.update_one({"order_id": a["order_id"]},
                         {"$set": {"shipping_address": new_addr, "updated_at": utcnow()}})
    if db.orders.find_one({"order_id": a["order_id"]})["shipping_address"] != new_addr:
        raise ExecutionError("Address change could not be verified.", "permanent")
    return {"verified": True}


def _do_return(a):
    order = db.orders.find_one({"order_id": a["order_id"]})
    check = rules.can_return(order, _blocking_other(a, "RETURN"))
    if not check["eligible"]:
        raise ExecutionError("No longer returnable: " + check["reason"], "permanent")
    return {"rma": "RMA-" + a["approval_id"][-6:], "verified": True}


HANDLERS = {"REFUND": _do_refund, "CANCEL_ORDER": _do_cancel, "UPDATE_ORDER": _do_update, "RETURN": _do_return}


def execute(approval_id: str, by: str):
    a = get(approval_id)
    attempts = a.get("attempts", 0) + 1
    a = _transition(approval_id, "APPROVED", "EXECUTING", by, f"attempt {attempts}", {"attempts": attempts})
    try:
        # the approval only counts for the exact action that was approved
        if compute_hash(a) != a.get("approved_hash"):
            raise ExecutionError("The proposal was changed after approval. Approval is no longer valid.")
        result = HANDLERS[a["type"]](a)
        final = _transition(approval_id, "EXECUTING", "COMPLETED", by, "verified",
                            {"execution_result": result, "failure_reason": None, "failure_kind": None})
        audit.log(a["case_id"], "approvals.execute", f"execute_{a['type'].lower()}",
                  {"approval_id": approval_id}, result, actor="backend", approval_status="APPROVED",
                  execution_status="COMPLETED")
    except Exception as e:
        kind, msg = _classify_error(e)
        final = _transition(approval_id, "EXECUTING", "FAILED", by, msg,
                            {"failure_reason": msg, "failure_kind": kind})
        audit.log(a["case_id"], "approvals.execute", f"execute_{a['type'].lower()}", {"approval_id": approval_id},
                  None, actor="backend", approval_status="APPROVED", execution_status="FAILED", error=msg)
    cases.notify_outcome(final)
    return final


def _classify_error(e):
    if isinstance(e, ExecutionError):
        return e.kind, str(e)
    if isinstance(e, services.PaymentError):
        return ("transient" if e.transient else "permanent"), "Payment service error"
    if isinstance(e, (TimeoutError, ConnectionError)):
        return "transient", "A backend service was unavailable"
    log.exception("Unexpected execution error")
    return "permanent", "Unexpected error while executing"


# ------------------------------------------------------------------ 4. retry, modify, reconcile
def retry(approval_id: str, user: dict):
    _require_agent(user)
    a = get(approval_id)
    max_attempts = rules.load_rules()["max_retry_attempts"]
    if a["status"] != "FAILED" or a.get("failure_kind") != "transient":
        raise InvalidTransition("Only transient failures can be retried")
    if a.get("attempts", 0) >= max_attempts:
        raise InvalidTransition(f"Maximum of {max_attempts} attempts reached")
    _transition(approval_id, "FAILED", "APPROVED", user["email"], "retry")
    return execute(approval_id, user["email"])


def modify(approval_id: str, user: dict, changes: dict):
    """Change a proposal. This cancels any earlier approval: a human must approve again."""
    _require_agent(user)
    a = get(approval_id)
    if a["status"] not in ("PENDING_APPROVAL", "APPROVED"):
        raise InvalidTransition("Only pending proposals can be changed")
    order = db.orders.find_one({"order_id": a["order_id"]})
    params = dict(a.get("params") or {})
    amount, reason = a.get("amount"), a["reason"]
    if changes.get("amount") is not None:
        if a["type"] != "REFUND" or not (0 < changes["amount"] <= order["total"]):
            raise ValueError("Refund amount must be more than 0 and not more than the order total")
        amount = round(float(changes["amount"]), 2)
    if changes.get("reason"):
        reason = changes["reason"][:300]
    if changes.get("new_shipping_address") and a["type"] == "UPDATE_ORDER":
        params["new_shipping_address"] = changes["new_shipping_address"][:300]
    now = utcnow()
    updated = {**a, "amount": amount, "reason": reason, "params": params}
    db.approvals.update_one({"approval_id": approval_id}, {
        "$set": {"amount": amount, "reason": reason, "params": params, "status": "PENDING_APPROVAL",
                 "proposal_hash": compute_hash(updated), "approved_hash": None, "decided_by": None,
                 "decision_reason": None, "updated_at": now},
        "$push": {"history": {"status": "PENDING_APPROVAL", "ts": now, "by": user["email"],
                              "note": "Proposal modified. Earlier approval is no longer valid."}}})
    audit.log(a["case_id"], "approvals.modify", "modify_proposal", {"approval_id": approval_id, **changes},
              actor=user["email"], approval_status="PENDING_APPROVAL")
    fresh = get(approval_id)
    _sync_child(fresh)
    return fresh


def reconcile():
    """Compare approvals, orders and payments and report anything that does not line up."""
    issues = []
    for a in db.approvals.find({"type": "REFUND", "status": "COMPLETED"}):
        pay = services.get_payment(a["idempotency_key"])
        order = db.orders.find_one({"order_id": a["order_id"]})
        if not pay:
            issues.append({"approval_id": a["approval_id"], "problem": "Completed refund has no payment record"})
        elif order["status"] != "REFUNDED":
            issues.append({"approval_id": a["approval_id"], "problem": "Payment exists but order is not REFUNDED"})
    keys = {a["idempotency_key"] for a in db.approvals.find({"type": "REFUND", "status": "COMPLETED"})}
    for p in db.payments.find({}):
        if p["idempotency_key"] not in keys:
            issues.append({"payment": p["txn_id"], "problem": "Payment has no completed approval"})
    for a in db.approvals.find({"status": "EXECUTING"}):
        issues.append({"approval_id": a["approval_id"], "problem": "Stuck in EXECUTING"})
    return {"ok": not issues, "issues": issues, "checked_at": utcnow()}


# ------------------------------------------------------------------ queries
def list_approvals(status="", kind="", page=1, page_size=20):
    query = {}
    if status:
        query["status"] = status
    if kind:
        query["type"] = kind
    page, page_size = max(page, 1), min(max(page_size, 1), 50)
    total = db.approvals.count_documents(query)
    items = list(db.approvals.find(query, {"_id": 0}).sort("created_at", -1).skip((page - 1) * page_size)
                 .limit(page_size))
    names = {c["customer_id"]: c for c in db.customers.find({})}
    for i in items:
        c = names.get(i["customer_id"], {})
        i["customer_name"], i["customer_email"] = c.get("name"), c.get("email")
    return {"items": items, "total": total, "page": page}
