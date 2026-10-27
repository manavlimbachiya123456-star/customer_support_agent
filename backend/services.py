"""Fake external services: shipping API and payment gateway. No real money ever moves."""
import uuid

import config
from db import db, utcnow


class PaymentError(Exception):
    def __init__(self, message, transient=True):
        super().__init__(message)
        self.transient = transient


def get_shipment(order_id: str):
    """Pretend shipping API. Set SIMULATE_SHIPPING_DOWN=true to test failures."""
    if config.flag("SIMULATE_SHIPPING_DOWN"):
        raise TimeoutError("Shipping API unavailable")
    return db.shipments.find_one({"order_id": order_id}, {"_id": 0})


def get_payment(idempotency_key: str):
    return db.payments.find_one({"idempotency_key": idempotency_key}, {"_id": 0})


def process_refund(amount: float, idempotency_key: str, order_id: str) -> dict:
    """Simulated refund. Calling it twice with the same key never pays twice."""
    existing = get_payment(idempotency_key)
    if existing:
        return existing
    if config.flag("SIMULATE_PAYMENT_FAILURE"):
        raise PaymentError("Simulated payment gateway error", transient=True)
    payment = {
        "txn_id": "TXN-" + uuid.uuid4().hex[:10].upper(),
        "idempotency_key": idempotency_key,
        "order_id": order_id,
        "amount": float(amount),
        "status": "SUCCEEDED",
        "created_at": utcnow(),
    }
    db.payments.insert_one(dict(payment))
    return payment
