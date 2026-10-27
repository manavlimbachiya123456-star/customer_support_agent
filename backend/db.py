"""MongoDB connection. MONGO_URI=mock uses an in-memory fake database (for tests / quick demo)."""
import os
import uuid
from datetime import datetime, timezone

import config  # noqa: F401  (loads .env)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB", "supportpilot")

if MONGO_URI == "mock":
    import mongomock

    _client = mongomock.MongoClient()
else:
    from pymongo import MongoClient

    _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

db = _client[DB_NAME]

COLLECTIONS = ["customers", "users", "orders", "shipments", "cases", "messages", "refunds",
               "returns", "approvals", "documents", "audit_logs", "payments"]


def utcnow() -> datetime:
    """Naive UTC datetime (this is what MongoDB returns, so everything stays comparable)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def ensure_indexes() -> None:
    db.customers.create_index("customer_id", unique=True)
    db.users.create_index("email", unique=True)
    db.orders.create_index("order_id", unique=True)
    db.orders.create_index("customer_id")
    db.shipments.create_index("order_id")
    db.cases.create_index("case_id", unique=True)
    db.cases.create_index([("created_at", -1)])
    db.messages.create_index("case_id")
    db.refunds.create_index("request_id", unique=True)
    db.returns.create_index("request_id", unique=True)
    db.approvals.create_index("approval_id", unique=True)
    db.approvals.create_index("idempotency_key", unique=True)  # blocks duplicate actions
    db.approvals.create_index([("order_id", 1), ("type", 1)])
    db.payments.create_index("idempotency_key", unique=True)  # blocks double refunds
    db.documents.create_index("doc_id", unique=True)
    db.audit_logs.create_index([("ts", -1)])
    db.audit_logs.create_index("case_id")
