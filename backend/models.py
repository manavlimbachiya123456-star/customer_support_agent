"""Data models (Pydantic). Used to validate seed data and document the MongoDB schemas.

MongoDB collections: customers, users, orders (OrderItem is embedded in an order), shipments,
cases, messages, refunds, returns, approvals, documents, audit_logs, payments.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    SHIPPED = "SHIPPED"
    DELAYED = "DELAYED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"
    REFUNDED = "REFUNDED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class ApprovalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ActionType(str, Enum):
    REFUND = "REFUND"
    CANCEL_ORDER = "CANCEL_ORDER"
    UPDATE_ORDER = "UPDATE_ORDER"
    RETURN = "RETURN"


class Role(str, Enum):
    CUSTOMER = "customer"
    SUPPORT_AGENT = "support_agent"
    ADMIN = "admin"


class Customer(BaseModel):
    customer_id: str = Field(pattern=r"^CUST-\d+$")
    name: str
    email: str
    city: str
    tier: str = "STANDARD"
    created_at: datetime


class OrderItem(BaseModel):
    sku: str
    name: str
    qty: int = Field(ge=1)
    price: float = Field(ge=0)


class Order(BaseModel):
    order_id: str = Field(pattern=r"^ORD-\d+$")
    customer_id: str
    status: OrderStatus
    items: List[OrderItem] = Field(min_length=1)
    total: float = Field(ge=0)
    shipping_address: str
    created_at: datetime
    updated_at: datetime


class ShipmentEvent(BaseModel):
    ts: datetime
    status: str
    location: str = ""


class Shipment(BaseModel):
    order_id: str
    carrier: str
    tracking_number: str
    status: str
    expected_date: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    events: List[ShipmentEvent] = []


class SupportCase(BaseModel):
    case_id: str = Field(pattern=r"^CASE-\d+$")
    customer_id: str
    customer_name: str
    order_id: Optional[str] = None
    category: str
    priority: str
    status: CaseStatus
    request: str
    assigned_agent: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
