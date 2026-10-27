from datetime import timedelta

import rules
from db import utcnow

NOW = utcnow()


def order(status="DELAYED", created=14):
    return {"order_id": "ORD-1", "status": status, "total": 100.0, "created_at": NOW - timedelta(days=created)}


def ship(expected=-7, delivered=None):
    return {"expected_date": NOW + timedelta(days=expected) if expected is not None else None,
            "delivered_at": NOW - timedelta(days=delivered) if delivered is not None else None}


def test_overdue_delivery_is_eligible():
    r = rules.check_refund(order(), ship(-7), None, now=NOW)
    assert r["eligible"] and r["rule"] == "delivery_overdue"


def test_not_overdue_enough_must_wait():
    r = rules.check_refund(order("SHIPPED"), ship(-1), None, now=NOW)
    assert not r["eligible"] and r["next_step"] == "wait"


def test_duplicate_refund_blocked():
    r = rules.check_refund(order(), ship(-7), {"status": "PENDING_APPROVAL"}, now=NOW)
    assert not r["eligible"] and r["rule"] == "duplicate_refund"


def test_already_refunded_blocked():
    assert not rules.check_refund(order("REFUNDED"), ship(-7), None, now=NOW)["eligible"]


def test_cancelled_order_has_nothing_to_refund():
    assert rules.check_refund(order("CANCELLED"), None, None, now=NOW)["rule"] == "order_cancelled"


def test_missing_shipment_is_not_treated_as_lost():
    r = rules.check_refund(order(), None, None, now=NOW)
    assert not r["eligible"] and r["next_step"] == "escalate" and r["rule"] == "missing_delivery_data"


def test_missing_expected_date_escalates():
    r = rules.check_refund(order("SHIPPED"), ship(None), None, now=NOW)
    assert not r["eligible"] and r["next_step"] == "escalate"


def test_outside_refund_window_escalates():
    r = rules.check_refund(order("DELAYED", created=40), ship(-30), None, now=NOW)
    assert not r["eligible"] and r["rule"] == "outside_refund_window" and r["next_step"] == "escalate"


def test_delivered_without_issue_offers_return():
    r = rules.check_refund(order("DELIVERED", 10), ship(-6, delivered=5), None, now=NOW)
    assert not r["eligible"] and r["next_step"] == "offer_return"


def test_delivered_damaged_is_eligible():
    r = rules.check_refund(order("DELIVERED", 10), ship(-6, delivered=5), None, issue="damaged", now=NOW)
    assert r["eligible"]


def test_cancel_rules():
    assert rules.can_cancel(order("PLACED"))["eligible"]
    assert rules.can_cancel(order("CANCELLED"))["rule"] == "already_cancelled"  # no second cancellation
    assert not rules.can_cancel(order("SHIPPED"))["eligible"]


def test_policy_conflict_detection():
    same = [{"text": "The refund window is 30 days."}, {"text": "Refund window: 30 days from delivery"}]
    diff = [{"text": "The refund window is 30 days."}, {"text": "The refund window is 14 days."}]
    assert not rules.detect_policy_conflict(same)
    assert rules.detect_policy_conflict(diff)
