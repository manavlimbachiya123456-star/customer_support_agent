"""Seed demo data: 15 customers, 30 orders, shipments, 10 cases, users and policy documents.

    python seed.py             # wipe and re-create everything
    python seed.py --if-empty  # only seed when the database is empty (used by Docker)

Dates are relative to "now", so the demo always looks fresh.
"""
import hashlib
import os
import sys
from datetime import timedelta

import approvals
import cases
import rag
from db import COLLECTIONS, db, ensure_indexes, utcnow
from models import Customer, Order, Shipment, SupportCase

POLICY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "policies")
PBKDF2_ITERS = int(os.getenv("PBKDF2_ITERS", "120000"))

CUSTOMERS = [
    ("Aarav Mehta", "Vadodara"), ("Diya Patel", "Ahmedabad"), ("Rohan Shah", "Surat"),
    ("Ananya Iyer", "Chennai"), ("Kabir Singh", "Delhi"), ("Meera Nair", "Kochi"),
    ("Vihaan Gupta", "Lucknow"), ("Isha Kapoor", "Mumbai"), ("Arjun Reddy", "Hyderabad"),
    ("Sneha Joshi", "Pune"), ("Aditya Verma", "Jaipur"), ("Pooja Desai", "Rajkot"),
    ("Karan Malhotra", "Chandigarh"), ("Riya Sharma", "Bhopal"), ("Neel Trivedi", "Gandhinagar"),
]

PRODUCTS = [("SKU-101", "Wireless Earbuds", 1499), ("SKU-102", "Phone Case", 399), ("SKU-103", "Running Shoes", 2499),
            ("SKU-104", "Cotton T-Shirt", 599), ("SKU-105", "Steel Water Bottle", 799), ("SKU-106", "Laptop Backpack", 1899),
            ("SKU-107", "Desk Lamp", 1199), ("SKU-108", "Yoga Mat", 899), ("SKU-109", "Bluetooth Speaker", 2799),
            ("SKU-110", "Smart Watch Strap", 499), ("SKU-111", "Notebook Set", 349), ("SKU-112", "Power Bank", 1699)]

# (order_id, customer number, status, created days ago, delivered days ago, expected date (days from now), notes)
ORDERS = [
    ("ORD-1020", 1, "DELIVERED", 20, 15, -16), ("ORD-1021", 2, "DELIVERED", 45, 40, -41),
    ("ORD-1022", 3, "CANCELLED", 10, None, None), ("ORD-1023", 4, "REFUNDED", 25, 20, -21),
    ("ORD-1024", 5, "RETURNED", 30, 25, -26), ("ORD-1025", 6, "SHIPPED", 3, None, 2),
    ("ORD-1026", 7, "PLACED", 1, None, None), ("ORD-1027", 8, "DELAYED", 14, None, -7),
    ("ORD-1028", 9, "DELAYED", 10, None, -4), ("ORD-1029", 10, "DELIVERED", 6, 2, -3),
    ("ORD-1030", 11, "DELIVERED", 9, 5, -6), ("ORD-1031", 12, "SHIPPED", 5, None, -1),
    ("ORD-1032", 13, "DELAYED", 21, None, -12), ("ORD-1033", 14, "DELIVERED", 50, 46, -47),
    ("ORD-1034", 15, "CANCELLED", 8, None, None), ("ORD-1035", 1, "DELIVERED", 4, 1, -2),
    ("ORD-1036", 2, "PLACED", 0, None, None), ("ORD-1037", 3, "SHIPPED", 4, None, 3),
    ("ORD-1038", 4, "DELIVERED", 12, 9, -10), ("ORD-1039", 5, "DELAYED", 16, None, -9),
    ("ORD-1040", 6, "DELIVERED", 18, 14, -15), ("ORD-1041", 7, "REFUNDED", 33, 28, -29),
    ("ORD-1042", 1, "DELAYED", 14, None, -7),  # <- the demo order
    ("ORD-1043", 8, "DELIVERED", 7, 3, -4), ("ORD-1044", 9, "CANCELLED", 15, None, None),
    ("ORD-1045", 10, "SHIPPED", 6, None, -2), ("ORD-1046", 11, "DELAYED", 28, None, -20),
    ("ORD-1047", 12, "SHIPPED", 7, None, "missing"),  # shipment exists but has no expected date
    ("ORD-1048", 13, "PLACED", 2, None, None), ("ORD-1049", 14, "DELAYED", 35, None, -25),
]

# case_id, customer, order, category, status, created days ago, resolved after (hours), agent, request
CASES = [
    ("CASE-1001", 2, "ORD-1021", "REFUND", "RESOLVED", 6, 5, "agent@supportpilot.com", "I want a refund for ORD-1021, it is not what I expected."),
    ("CASE-1002", 3, "ORD-1022", "CANCELLATION", "RESOLVED", 9, 2, "agent@supportpilot.com", "Please cancel ORD-1022."),
    ("CASE-1003", 4, "ORD-1023", "REFUND", "RESOLVED", 21, 26, "agent2@supportpilot.com", "ORD-1023 arrived damaged. I need a refund."),
    ("CASE-1004", 5, "ORD-1024", "RETURN", "RESOLVED", 26, 30, "agent2@supportpilot.com", "I would like to return ORD-1024."),
    ("CASE-1005", 5, "ORD-1039", "REFUND", "PENDING_APPROVAL", 1, None, None, "ORD-1039 is very late. Can I get a refund?"),
    ("CASE-1006", 8, "ORD-1027", "DELIVERY", "OPEN", 2, None, None, "Where is my order ORD-1027?"),
    ("CASE-1007", 12, "ORD-1047", "DELIVERY", "ESCALATED", 3, None, "agent@supportpilot.com", "ORD-1047 has no tracking updates."),
    ("CASE-1008", 1, "ORD-1035", "DAMAGED_OR_MISSING", "OPEN", 1, None, None, "ORD-1035 arrived with a broken strap."),
    ("CASE-1009", 13, "ORD-1032", "REFUND", "OPEN", 2, None, None, "ORD-1032 is 12 days late. I want my money back."),
    ("CASE-1010", 14, "ORD-1049", "REFUND", "ESCALATED", 4, None, "agent2@supportpilot.com", "ORD-1049 never came. I want a refund."),
]


def hash_password(password: str) -> str:
    salt = os.urandom(8).hex()
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERS).hex()
    return f"{PBKDF2_ITERS}${salt}${h}"


def cid(n):
    return f"CUST-{n:03d}"


def build_items(i):
    """Pick 1 to 3 products deterministically for order number i."""
    out = []
    for k in range(1 + i % 3):
        sku, name, price = PRODUCTS[(i * 3 + k * 5) % len(PRODUCTS)]
        out.append({"sku": sku, "name": name, "qty": 1 + (k == 0 and i % 4 == 0), "price": float(price)})
    return out


def seed_users_and_customers(now):
    cache = {}
    users = []
    for n, (name, city) in enumerate(CUSTOMERS, start=1):
        Customer(customer_id=cid(n), name=name, email=f"{name.split()[0].lower()}@example.com", city=city,
                 tier="GOLD" if n % 4 == 0 else "STANDARD", created_at=now - timedelta(days=400 - n * 7))
        db.customers.insert_one({"customer_id": cid(n), "name": name, "email": f"{name.split()[0].lower()}@example.com",
                                 "city": city, "tier": "GOLD" if n % 4 == 0 else "STANDARD",
                                 "created_at": now - timedelta(days=400 - n * 7)})
        cache.setdefault("customer123", hash_password("customer123"))
        users.append({"email": f"{name.split()[0].lower()}@example.com", "name": name, "role": "customer",
                      "customer_id": cid(n), "password_hash": cache["customer123"]})
    for email, name, role, pw in (("agent@supportpilot.com", "Support Agent One", "support_agent", "agent123"),
                                  ("agent2@supportpilot.com", "Support Agent Two", "support_agent", "agent123"),
                                  ("admin@supportpilot.com", "Admin", "admin", "admin123")):
        users.append({"email": email, "name": name, "role": role, "customer_id": None,
                      "password_hash": hash_password(pw)})
    db.users.insert_many(users)


def seed_orders(now):
    for i, (oid, cnum, status, created, delivered, expected) in enumerate(ORDERS):
        items = build_items(i)
        total = sum(it["qty"] * it["price"] for it in items)
        created_at = now - timedelta(days=created)
        delivered_at = now - timedelta(days=delivered) if delivered is not None else None
        city = CUSTOMERS[cnum - 1][1]
        order = {"order_id": oid, "customer_id": cid(cnum), "status": status, "items": items, "total": total,
                 "shipping_address": f"{10 + i}, MG Road, {city}", "created_at": created_at,
                 "updated_at": created_at, "delivered_at": delivered_at}
        Order(**{k: v for k, v in order.items() if k != "delivered_at"})  # validate
        db.orders.insert_one(order)

        if status in ("PLACED", "CANCELLED"):
            continue  # nothing shipped
        exp = None if expected == "missing" else (now + timedelta(days=expected) if expected is not None else None)
        events = [{"ts": created_at + timedelta(hours=2), "status": "ORDER_PLACED", "location": "Online"},
                  {"ts": created_at + timedelta(days=1), "status": "PACKED", "location": "Warehouse"},
                  {"ts": created_at + timedelta(days=2), "status": "SHIPPED", "location": "Warehouse"}]
        if status != "SHIPPED" or created > 3:
            events.append({"ts": created_at + timedelta(days=3), "status": "IN_TRANSIT", "location": "Regional hub"})
        if status == "DELAYED":
            events.append({"ts": exp + timedelta(days=1) if exp else created_at + timedelta(days=5),
                           "status": "DELAY_REPORTED", "location": "Carrier hub"})
        if delivered_at:
            events.append({"ts": delivered_at, "status": "DELIVERED", "location": city})
        ship_status = {"DELIVERED": "DELIVERED", "RETURNED": "DELIVERED", "REFUNDED": "DELIVERED",
                       "DELAYED": "DELAYED", "SHIPPED": "IN_TRANSIT"}[status]
        ship = {"order_id": oid, "carrier": ["BlueDart", "Delhivery", "DTDC"][i % 3],
                "tracking_number": f"TRK{880000 + i * 37}", "status": ship_status, "expected_date": exp,
                "delivered_at": delivered_at, "events": events}
        Shipment(**ship)  # validate
        db.shipments.insert_one(ship)


def seed_actions(now):
    """Existing refund / return history (so duplicate checks have something to find)."""
    o = db.orders.find_one({"order_id": "ORD-1023"})
    doc = approvals.make_doc("REFUND", o, "CASE-1003", {"issue": "damaged"}, "Item arrived damaged", o["total"],
                             {"seeded": True}, [], "REFUND:ORD-1023:0", "COMPLETED")
    doc.update({"decided_by": "agent2@supportpilot.com", "decision_reason": "Photo evidence checked", "approved_hash": doc["proposal_hash"],
                "execution_result": {"txn_id": "TXN-SEED0001", "amount": o["total"], "verified": True}})
    db.approvals.insert_one(doc)
    db.refunds.insert_one({"request_id": doc["approval_id"], "order_id": "ORD-1023", "customer_id": o["customer_id"],
                           "amount": o["total"], "reason": doc["reason"], "status": "COMPLETED", "txn_id": "TXN-SEED0001",
                           "created_at": now - timedelta(days=21), "updated_at": now - timedelta(days=20)})
    db.payments.insert_one({"txn_id": "TXN-SEED0001", "idempotency_key": "REFUND:ORD-1023:0", "order_id": "ORD-1023",
                            "amount": o["total"], "status": "SUCCEEDED", "created_at": now - timedelta(days=20)})

    o = db.orders.find_one({"order_id": "ORD-1041"})
    doc = approvals.make_doc("REFUND", o, None, {"issue": "none"}, "Delivery was late", o["total"], {"seeded": True},
                             [], "REFUND:ORD-1041:0", "COMPLETED")
    doc["execution_result"] = {"txn_id": "TXN-SEED0002", "amount": o["total"], "verified": True}
    db.approvals.insert_one(doc)
    db.payments.insert_one({"txn_id": "TXN-SEED0002", "idempotency_key": "REFUND:ORD-1041:0", "order_id": "ORD-1041",
                            "amount": o["total"], "status": "SUCCEEDED", "created_at": now - timedelta(days=5)})

    o = db.orders.find_one({"order_id": "ORD-1024"})
    doc = approvals.make_doc("RETURN", o, "CASE-1004", {}, "Did not fit", None, {"seeded": True}, [], "RETURN:ORD-1024:0",
                             "COMPLETED")
    doc["execution_result"] = {"rma": "RMA-SEED01", "verified": True}
    db.approvals.insert_one(doc)

    # a refund waiting for a human: shows up in the Approval Center right away
    o = db.orders.find_one({"order_id": "ORD-1039"})
    db.refunds.delete_many({"order_id": "ORD-1039"})
    approvals.propose("REFUND", o, "CASE-1005", {"issue": "none"}, "Delivery is 9 days overdue", o["total"],
                      {"order_status": "DELAYED", "rule": "delivery_overdue", "eligibility": "Delivery is 9 days overdue"},
                      [])


def seed_cases(now):
    for case_id, cnum, oid, category, status, created, resolved_h, agent, request in CASES:
        created_at = now - timedelta(days=created)
        resolved_at = created_at + timedelta(hours=resolved_h) if resolved_h else None
        c = {"case_id": case_id, "customer_id": cid(cnum), "customer_name": CUSTOMERS[cnum - 1][0], "order_id": oid,
             "category": category, "priority": cases.priority_for(category), "status": status, "request": request,
             "assigned_agent": agent, "created_at": created_at, "updated_at": resolved_at or created_at,
             "resolved_at": resolved_at}
        SupportCase(**c)  # validate
        db.cases.insert_one({**c, "investigation": None, "runs": 0})
        cases.add_message(case_id, "user", request)
        if status == "RESOLVED":
            cases.add_message(case_id, "assistant", "Your request was reviewed and is now closed. Thank you.")


def seed_policies():
    rag.reset_collection()
    if not os.path.isdir(POLICY_DIR):
        return
    for name in sorted(os.listdir(POLICY_DIR)):
        if name.endswith((".md", ".txt", ".pdf")):
            with open(os.path.join(POLICY_DIR, name), "rb") as f:
                rag.ingest(name, f.read(), uploaded_by="seed")


def run(reset=True, with_policies=True):
    now = utcnow()
    if reset:
        for name in COLLECTIONS:
            db[name].drop()
    ensure_indexes()
    seed_users_and_customers(now)
    seed_orders(now)
    seed_cases(now)
    seed_actions(now)
    if with_policies:
        seed_policies()


if __name__ == "__main__":
    if "--if-empty" in sys.argv and db.customers.count_documents({}) > 0:
        print("Database already has data, skipping seed.")
        rag.sync_index()
    else:
        run()
        print(f"Seeded: {db.customers.count_documents({})} customers, {db.orders.count_documents({})} orders, "
              f"{db.cases.count_documents({})} cases, {db.documents.count_documents({})} policy documents.")
