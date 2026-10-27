"""Business rules. Plain Python, no LLM. The agent can read these results but never changes them."""
import json
import os
import re
from datetime import datetime

from db import utcnow

DEFAULTS = {"refund_window_days": 30, "delay_grace_days": 3, "return_window_days": 30,
            "max_retry_attempts": 3}

# An action in one of these states "blocks" a second action of the same type on the same order.
BLOCKING = ("PENDING_APPROVAL", "APPROVED", "EXECUTING", "COMPLETED")
PRODUCT_ISSUES = ("damaged", "missing_item", "wrong_item")


def load_rules() -> dict:
    path = os.getenv("BUSINESS_RULES_FILE", os.path.join(os.path.dirname(__file__), "business_rules.json"))
    rules = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path) as f:
            rules.update(json.load(f))
    return rules


def _result(eligible, reason, rule, next_step, **facts):
    return {"eligible": eligible, "reason": reason, "rule": rule, "next_step": next_step, "facts": facts}


def _days(a: datetime, b: datetime) -> int:
    return int((a - b).total_seconds() // 86400)


def check_refund(order, shipment, existing_refund, issue="none", now=None):
    """Is this order eligible for a refund?

    next_step tells the agent what to do: create_refund_request | offer_return | wait | escalate | none
    """
    rules = load_rules()
    now = now or utcnow()
    status = order["status"]

    if existing_refund:
        done = existing_refund.get("status") == "COMPLETED"
        return _result(False,
                       "A refund was already issued for this order." if done
                       else "A refund request for this order is already in progress.",
                       "duplicate_refund", "none", existing_status=existing_refund.get("status"))
    if status == "REFUNDED":
        return _result(False, "This order was already refunded.", "already_refunded", "none")
    if status == "CANCELLED":
        return _result(False, "This order was cancelled, so there is nothing to refund here.",
                       "order_cancelled", "none")
    if status == "RETURNED":
        return _result(False, "This order was returned. Refunds for returns go through the returns process.",
                       "order_returned", "escalate")
    if status == "PLACED":
        return _result(False, "The order has not shipped yet. It can be cancelled instead.",
                       "not_shipped", "none")

    # From here on we need real delivery data. Missing data is NOT proof that the package is lost.
    if not shipment:
        return _result(False, "No delivery data found, so a lost package cannot be confirmed.",
                       "missing_delivery_data", "escalate")
    if status != "DELIVERED" and not shipment.get("expected_date"):
        return _result(False, "Expected delivery date is missing, so lateness cannot be confirmed.",
                       "missing_delivery_data", "escalate")
    if status == "DELIVERED" and not shipment.get("delivered_at"):
        return _result(False, "Order is marked delivered but has no delivery date.",
                       "missing_delivery_data", "escalate")

    window = rules["refund_window_days"]
    start = shipment["delivered_at"] if status == "DELIVERED" else order["created_at"]
    age_days = _days(now, start)
    if age_days > window:
        return _result(False, f"The {window}-day refund window has passed ({age_days} days).",
                       "outside_refund_window", "escalate", age_days=age_days, window_days=window)

    if status == "DELIVERED":
        if issue in PRODUCT_ISSUES:
            return _result(True, f"Item reported as {issue.replace('_', ' ')} within the refund window.",
                           "product_issue", "create_refund_request", age_days=age_days)
        return _result(False, "The order was delivered. A refund needs a damaged, missing or wrong item.",
                       "delivered_no_issue", "offer_return", age_days=age_days)

    # SHIPPED or DELAYED: check whether delivery is overdue
    overdue = _days(now, shipment["expected_date"])
    grace = rules["delay_grace_days"]
    if overdue >= grace:
        return _result(True, f"Delivery is {overdue} days overdue (policy allows a refund after {grace} days).",
                       "delivery_overdue", "create_refund_request", days_overdue=overdue)
    return _result(False, f"Delivery is not overdue enough yet (policy: {grace} days after the expected date).",
                   "not_overdue_yet", "wait", days_overdue=max(overdue, 0))


def can_cancel(order, existing_cancel=None):
    if existing_cancel:
        return _result(False, "A cancellation request for this order is already in progress.",
                       "duplicate_cancel", "none")
    if order["status"] == "CANCELLED":
        return _result(False, "This order is already cancelled.", "already_cancelled", "none")
    if order["status"] == "PLACED":
        return _result(True, "Order has not shipped yet, so it can be cancelled.", "cancellable", "cancel_order")
    if order["status"] == "DELIVERED":
        return _result(False, "The order was already delivered. A return may be possible instead.",
                       "already_delivered", "offer_return")
    return _result(False, f"The order is {order['status']} and cannot be cancelled any more.",
                   "already_shipped", "none")


def can_return(order, existing_return=None, now=None):
    rules = load_rules()
    now = now or utcnow()
    if existing_return:
        return _result(False, "A return request for this order already exists.", "duplicate_return", "none")
    if order["status"] == "RETURNED":
        return _result(False, "This order was already returned.", "already_returned", "none")
    if order["status"] != "DELIVERED":
        return _result(False, "Only delivered orders can be returned.", "not_delivered", "none")
    delivered_at = order.get("delivered_at")
    if not delivered_at:
        return _result(False, "No delivery date on record.", "missing_delivery_data", "escalate")
    age = _days(now, delivered_at)
    if age > rules["return_window_days"]:
        return _result(False, f"The {rules['return_window_days']}-day return window has passed.",
                       "outside_return_window", "escalate", age_days=age)
    return _result(True, "Delivered within the return window.", "returnable", "create_return_request", age_days=age)


def can_update_address(order, existing=None):
    if existing:
        return _result(False, "An address change for this order is already in progress.", "duplicate_update", "none")
    if order["status"] != "PLACED":
        return _result(False, "The address can only be changed before the order ships.",
                       "already_shipped", "none")
    return _result(True, "Order has not shipped yet.", "address_changeable", "update_order")


# Policy conflict check: if two passages state different refund windows, a human must decide.
WINDOW_RE = re.compile(r"refund window(?: is| of|:)?\s*(\d+)\s*(?:calendar\s*)?days", re.I)


def detect_policy_conflict(passages) -> bool:
    values = set()
    for p in passages:
        for m in WINDOW_RE.finditer(p.get("text", "")):
            values.add(int(m.group(1)))
    return len(values) > 1
