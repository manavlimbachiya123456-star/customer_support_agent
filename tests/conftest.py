"""Test setup: fake MongoDB, in-memory Qdrant, mock LLM. No API keys or servers needed."""
import os
import sys

os.environ.update({"MONGO_URI": "mock", "MOCK_LLM": "true", "QDRANT_PATH": ":memory:", "QDRANT_URL": "",
                   "PBKDF2_ITERS": "1000", "RATE_LIMIT_ENABLED": "false", "JWT_SECRET": "test-secret",
                   "SIMULATE_SHIPPING_DOWN": "false", "SIMULATE_PAYMENT_FAILURE": "false"})
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest  # noqa: E402

import seed  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_data():
    """Every test starts from the same seeded data."""
    seed.run()
    yield


AGENT = {"email": "agent@supportpilot.com", "role": "support_agent"}
CUSTOMER = {"email": "aarav@example.com", "role": "customer", "customer_id": "CUST-001"}
