import pytest

import approvals
import services
from conftest import AGENT, CUSTOMER
from db import db
from tools import make_tools


def propose_refund(order_id="ORD-1042", customer="CUST-001"):
    t = {f.__name__: f for f in make_tools(customer, "CASE-T")}
    return t["create_refund_request"](order_id, "Order is late", "none")


def test_proposal_is_pending_and_nothing_executes():
    r = propose_refund()
    assert r["status"] == "PENDING_APPROVAL"
    assert db.orders.find_one({"order_id": "ORD-1042"})["status"] == "DELAYED"  # unchanged
    assert db.payments.count_documents({"order_id": "ORD-1042"}) == 0


def test_full_flow_approve_executes_once_and_verifies():
    r = propose_refund()
    a = approvals.decide(r["approval_id"], AGENT, True, "Verified with carrier")
    assert a["status"] == "COMPLETED" and a["execution_result"]["verified"] is True
    assert db.orders.find_one({"order_id": "ORD-1042"})["status"] == "REFUNDED"
    assert db.payments.count_documents({"order_id": "ORD-1042"}) == 1
    assert [h["status"] for h in a["history"]] == ["PROPOSED", "PENDING_APPROVAL", "APPROVED", "EXECUTING", "COMPLETED"]
    assert db.refunds.find_one({"request_id": a["approval_id"]})["status"] == "COMPLETED"


def test_customer_cannot_approve():
    r = propose_refund()
    with pytest.raises(approvals.PermissionDenied):
        approvals.decide(r["approval_id"], CUSTOMER, True, "please")
    assert approvals.get(r["approval_id"])["status"] == "PENDING_APPROVAL"


def test_reason_is_required():
    r = propose_refund()
    with pytest.raises(ValueError):
        approvals.decide(r["approval_id"], AGENT, True, " ")


def test_reject_does_not_execute():
    r = propose_refund()
    a = approvals.decide(r["approval_id"], AGENT, False, "Not enough proof")
    assert a["status"] == "REJECTED" and db.payments.count_documents({}) == 2  # only the 2 seeded payments


def test_cannot_decide_twice():
    r = propose_refund()
    approvals.decide(r["approval_id"], AGENT, True, "ok ok")
    with pytest.raises(approvals.InvalidTransition):
        approvals.decide(r["approval_id"], AGENT, True, "ok again")
    assert db.payments.count_documents({"order_id": "ORD-1042"}) == 1


def test_duplicate_proposal_creates_one_request():
    first = propose_refund()
    second = propose_refund()
    assert second["status"] == "ALREADY_EXISTS" and second["approval_id"] == first["approval_id"]
    assert db.approvals.count_documents({"order_id": "ORD-1042", "type": "REFUND"}) == 1


def test_already_refunded_order_cannot_be_refunded_again():
    r = propose_refund("ORD-1023", "CUST-004")
    assert r["status"] == "NOT_ELIGIBLE"


def test_payment_service_is_idempotent():
    p1 = services.process_refund(50, "KEY-1", "ORD-1")
    p2 = services.process_refund(50, "KEY-1", "ORD-1")
    assert p1["txn_id"] == p2["txn_id"] and db.payments.count_documents({"idempotency_key": "KEY-1"}) == 1


def test_failed_payment_then_retry_succeeds_without_double_refund(monkeypatch):
    r = propose_refund()
    monkeypatch.setenv("SIMULATE_PAYMENT_FAILURE", "true")
    a = approvals.decide(r["approval_id"], AGENT, True, "go ahead")
    assert a["status"] == "FAILED" and a["failure_kind"] == "transient"
    assert db.orders.find_one({"order_id": "ORD-1042"})["status"] == "DELAYED"  # nothing changed
    monkeypatch.setenv("SIMULATE_PAYMENT_FAILURE", "false")
    a = approvals.retry(r["approval_id"], AGENT)
    assert a["status"] == "COMPLETED" and a["attempts"] == 2
    assert db.payments.count_documents({"order_id": "ORD-1042"}) == 1


def test_retry_is_limited(monkeypatch):
    r = propose_refund()
    monkeypatch.setenv("SIMULATE_PAYMENT_FAILURE", "true")
    approvals.decide(r["approval_id"], AGENT, True, "go ahead")
    approvals.retry(r["approval_id"], AGENT)
    approvals.retry(r["approval_id"], AGENT)  # 3rd attempt
    with pytest.raises(approvals.InvalidTransition):
        approvals.retry(r["approval_id"], AGENT)


def test_permanent_failure_cannot_be_retried():
    r = propose_refund()
    # the order is cancelled behind our back before approval -> no longer eligible at execution time
    db.orders.update_one({"order_id": "ORD-1042"}, {"$set": {"status": "CANCELLED"}})
    a = approvals.decide(r["approval_id"], AGENT, True, "go ahead")
    assert a["status"] == "FAILED" and a["failure_kind"] == "permanent"
    with pytest.raises(approvals.InvalidTransition):
        approvals.retry(r["approval_id"], AGENT)


def test_eligibility_is_rechecked_before_executing():
    r = propose_refund()
    db.approvals.update_one({"approval_id": r["approval_id"]}, {"$set": {"status": "PENDING_APPROVAL"}})
    db.shipments.update_one({"order_id": "ORD-1042"}, {"$set": {"expected_date": None}})
    a = approvals.decide(r["approval_id"], AGENT, True, "go ahead")
    assert a["status"] == "FAILED" and db.payments.count_documents({"order_id": "ORD-1042"}) == 0


def test_tampering_after_approval_blocks_execution():
    r = propose_refund()
    a = approvals.get(r["approval_id"])
    # approve manually, then change the amount before execution starts
    approvals._transition(a["approval_id"], "PENDING_APPROVAL", "APPROVED", "x", "",
                          {"approved_hash": a["proposal_hash"]})
    db.approvals.update_one({"approval_id": a["approval_id"]}, {"$set": {"amount": 1.0}})
    final = approvals.execute(a["approval_id"], "x")
    assert final["status"] == "FAILED" and "changed after approval" in final["failure_reason"]
    assert db.payments.count_documents({"order_id": "ORD-1042"}) == 0


def test_modifying_a_proposal_invalidates_approval():
    r = propose_refund()
    a = approvals.get(r["approval_id"])
    approvals._transition(a["approval_id"], "PENDING_APPROVAL", "APPROVED", "x", "",
                          {"approved_hash": a["proposal_hash"], "decided_by": "x"})
    b = approvals.modify(r["approval_id"], AGENT, {"amount": 10})
    assert b["status"] == "PENDING_APPROVAL" and b["approved_hash"] is None and b["amount"] == 10.0
    final = approvals.decide(r["approval_id"], AGENT, True, "approve the new amount")
    assert final["status"] == "COMPLETED" and final["execution_result"]["amount"] == 10.0


def test_invalid_state_transitions_rejected():
    r = propose_refund()
    with pytest.raises(approvals.InvalidTransition):
        approvals._transition(r["approval_id"], "PENDING_APPROVAL", "COMPLETED", "x")
    with pytest.raises(approvals.InvalidTransition):
        approvals.execute(r["approval_id"], "x")  # not APPROVED yet


def test_cancel_flow_and_no_second_cancellation():
    t = {f.__name__: f for f in make_tools("CUST-002", "CASE-T")}
    r = t["cancel_order"]("ORD-1036", "changed my mind")  # PLACED
    assert r["status"] == "PENDING_APPROVAL"
    a = approvals.decide(r["approval_id"], AGENT, True, "ok ok")
    assert a["status"] == "COMPLETED" and db.orders.find_one({"order_id": "ORD-1036"})["status"] == "CANCELLED"
    assert t["cancel_order"]("ORD-1036", "again")["status"] == "NOT_ELIGIBLE"


def test_address_change_and_return_flows():
    t = {f.__name__: f for f in make_tools("CUST-002", "CASE-T")}
    r = t["update_order"]("ORD-1036", "55, New Street, Ahmedabad 380001")
    assert approvals.decide(r["approval_id"], AGENT, True, "address ok")["status"] == "COMPLETED"
    assert db.orders.find_one({"order_id": "ORD-1036"})["shipping_address"].startswith("55, New Street")
    t2 = {f.__name__: f for f in make_tools("CUST-006", "CASE-T")}
    r = t2["create_return_request"]("ORD-1040", "does not fit")
    assert approvals.decide(r["approval_id"], AGENT, True, "return ok")["execution_result"]["rma"].startswith("RMA-")


def test_reconcile_finds_missing_payment():
    assert approvals.reconcile()["ok"]
    r = propose_refund()
    approvals.decide(r["approval_id"], AGENT, True, "ok ok")
    assert approvals.reconcile()["ok"]
    db.payments.delete_many({"order_id": "ORD-1042"})
    assert not approvals.reconcile()["ok"]


def test_audit_trail_is_complete_for_a_refund():
    r = propose_refund()
    approvals.decide(r["approval_id"], AGENT, True, "ok ok")
    actions = [e["action"] for e in db.audit_logs.find({"case_id": "CASE-T"})]
    assert {"propose_refund", "approve", "execute_refund"} <= set(actions)
    done = db.audit_logs.find_one({"action": "execute_refund"})
    assert done["execution_status"] == "COMPLETED" and done["actor"] == "backend"
