"""FastAPI app: login, chat, cases, approvals, knowledge base, audit logs.

Run:  uvicorn main:app --port 8000
"""
import hashlib
import hmac
import logging
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Optional

import jwt
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import agent
import approvals
import audit
import cases
import config
import rag
import services
from db import db, ensure_indexes, utcnow

log = logging.getLogger("supportpilot")
logging.basicConfig(level=logging.INFO)

JWT_SECRET = config.get("JWT_SECRET", "dev-secret-change-me")
JWT_HOURS = 8


@asynccontextmanager
async def lifespan(app):
    ensure_indexes()
    if config.flag("SEED_IF_EMPTY", "false") and db.customers.count_documents({}) == 0:
        import seed  # demo data (in mock mode the database starts empty on every start)
        seed.run()
        log.info("Seeded demo data")
    try:
        rag.sync_index()
    except Exception:
        log.exception("Could not sync the knowledge base index")
    if JWT_SECRET == "dev-secret-change-me":
        log.warning("JWT_SECRET is not set. Using an insecure development secret.")
    yield


app = FastAPI(title="SupportPilot AI", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.get("CORS_ORIGINS", "http://localhost:5173").split(","),
                   allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ rate limiting (simple, in memory)
_hits = defaultdict(deque)
LIMITS = {"/auth/login": 10, "/chat": 20, "default": 120}  # requests per minute per client


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if config.flag("RATE_LIMIT_ENABLED", "true"):
        group = request.url.path if request.url.path in LIMITS else "default"
        key = (request.client.host if request.client else "?", group)
        now, window = time.time(), _hits[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= LIMITS[group]:
            return JSONResponse({"detail": "Too many requests. Please slow down."}, status_code=429)
        window.append(now)
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error")  # details stay in the server log
    return JSONResponse({"detail": "Something went wrong. Please try again."}, status_code=500)


# ------------------------------------------------------------------ auth
def verify_password(password: str, stored: str) -> bool:
    iters, salt, h = stored.split("$")
    test = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters)).hex()
    return hmac.compare_digest(test, h)


def current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Please log in.")
    try:
        data = jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Your session is invalid or expired.")
    user = db.users.find_one({"email": data["sub"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(401, "Unknown user.")
    return user


def agent_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] not in ("support_agent", "admin"):
        raise HTTPException(403, "Support agents only.")
    return user


class LoginBody(BaseModel):
    email: str = Field(max_length=100)
    password: str = Field(max_length=100)


@app.post("/auth/login")
def login(body: LoginBody):
    user = db.users.find_one({"email": body.email.strip().lower()})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Wrong email or password.")
    token = jwt.encode({"sub": user["email"], "exp": utcnow() + timedelta(hours=JWT_HOURS)}, JWT_SECRET, "HS256")
    return {"token": token, "user": {k: user[k] for k in ("email", "name", "role", "customer_id")}}


@app.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return user


@app.get("/health")
def health():
    return {"ok": True, "mock_llm": config.mock_llm(), "model": config.GEMINI_MODEL}


# ------------------------------------------------------------------ chat
class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    case_id: Optional[str] = None


def _check_case_access(case: Optional[dict], user: dict):
    if not case or (user["role"] == "customer" and case["customer_id"] != user["customer_id"]):
        raise HTTPException(404, "Case not found.")  # same answer for "missing" and "not yours"


@app.post("/chat")
def chat(body: ChatBody, user: dict = Depends(current_user)):
    if user["role"] != "customer":
        raise HTTPException(403, "The chat is for customer accounts.")
    if body.case_id:
        case = cases.get_case(body.case_id)
        _check_case_access(case, user)
        cases.set_status(case["case_id"], "OPEN", resolved_at=None)
    else:
        case = cases.create_case(user, body.message)
    case_id = case["case_id"]

    history = cases.history(case_id)
    cases.add_message(case_id, "user", body.message)
    audit.log(case_id, "chat", "customer_message", {"length": len(body.message)}, actor=user["email"])
    try:
        result = agent.run_agent(body.message, user["customer_id"], case_id, history)
    except Exception:
        log.exception("Agent failed")
        result = {"answer": "I am having trouble right now, so I have passed your request to a human support "
                            "agent.", "decision": "ESCALATED", "confidence": "LOW", "uncertainties": ["Agent error"],
                  "steps": [], "evidence": {"verified": [], "hypotheses": []}, "policy_excerpts": [],
                  "proposed_action": None, "model": None}
        cases.set_status(case_id, "ESCALATED")
    cases.apply_result(case_id, result)
    return {"case_id": case_id, "answer": result["answer"], "decision": result["decision"],
            "confidence": result["confidence"], "steps": result["steps"], "evidence": result["evidence"],
            "proposed_action": result["proposed_action"]}


# ------------------------------------------------------------------ cases
@app.get("/cases")
def list_cases(q: str = "", status: str = "", priority: str = "", category: str = "", sort: str = "created_at",
               order: str = "desc", page: int = 1, page_size: int = 10, user: dict = Depends(current_user)):
    customer_id = user["customer_id"] if user["role"] == "customer" else None
    return cases.list_cases(customer_id, q, status, priority, category, sort, order, page, page_size)


@app.get("/cases/{case_id}")
def case_detail(case_id: str, user: dict = Depends(current_user)):
    case = cases.get_case(case_id)
    _check_case_access(case, user)
    is_agent = user["role"] != "customer"
    out = {"case": case, "messages": cases.messages(case_id)}
    approvals_list = list(db.approvals.find({"case_id": case_id}, {"_id": 0}))
    if not is_agent:  # customers get a trimmed view: no internal investigation details
        case.pop("investigation", None)
        out["approvals"] = [approvals.public(a) for a in approvals_list]
        return out
    out["approvals"] = approvals_list
    out["customer"] = db.customers.find_one({"customer_id": case["customer_id"]}, {"_id": 0})
    if case.get("order_id"):
        out["order"] = db.orders.find_one({"order_id": case["order_id"]}, {"_id": 0})
        out["shipment"] = db.shipments.find_one({"order_id": case["order_id"]}, {"_id": 0})
    return out


@app.get("/stats")
def stats(user: dict = Depends(agent_user)):
    return cases.stats()


@app.get("/orders")
def my_orders(user: dict = Depends(current_user)):
    query = {"customer_id": user["customer_id"]} if user["role"] == "customer" else {}
    return list(db.orders.find(query, {"_id": 0}).sort("created_at", -1).limit(50))


# ------------------------------------------------------------------ approvals
class DecideBody(BaseModel):
    approve: bool
    reason: str = Field(min_length=3, max_length=500)


class ModifyBody(BaseModel):
    amount: Optional[float] = None
    reason: Optional[str] = Field(default=None, max_length=300)
    new_shipping_address: Optional[str] = Field(default=None, max_length=300)


def _approval_call(fn, *args):
    try:
        return fn(*args)
    except approvals.NotFound as e:
        raise HTTPException(404, str(e))
    except approvals.PermissionDenied as e:
        raise HTTPException(403, str(e))
    except (approvals.InvalidTransition, ValueError) as e:
        raise HTTPException(409 if isinstance(e, approvals.InvalidTransition) else 400, str(e))


@app.get("/approvals")
def get_approvals(status: str = "", type: str = "", page: int = 1, user: dict = Depends(agent_user)):
    return approvals.list_approvals(status, type, page)


@app.get("/approvals/{approval_id}")
def get_approval(approval_id: str, user: dict = Depends(agent_user)):
    return _approval_call(approvals.get, approval_id)


@app.post("/approvals/{approval_id}/decide")
def decide(approval_id: str, body: DecideBody, user: dict = Depends(agent_user)):
    return _approval_call(approvals.decide, approval_id, user, body.approve, body.reason)


@app.post("/approvals/{approval_id}/retry")
def retry(approval_id: str, user: dict = Depends(agent_user)):
    return _approval_call(approvals.retry, approval_id, user)


@app.post("/approvals/{approval_id}/modify")
def modify(approval_id: str, body: ModifyBody, user: dict = Depends(agent_user)):
    return _approval_call(approvals.modify, approval_id, user, body.model_dump(exclude_none=True))


@app.get("/reconcile")
def reconcile(user: dict = Depends(agent_user)):
    return approvals.reconcile()


# ------------------------------------------------------------------ knowledge base
def _kb_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except rag.KBError as e:
        raise HTTPException(e.status, str(e))


@app.get("/kb/documents")
def kb_list(user: dict = Depends(agent_user)):
    return rag.list_documents()


@app.post("/kb/upload")
def kb_upload(file: UploadFile = File(...), doc_type: str = Form(""), replace: bool = Form(False),
              user: dict = Depends(agent_user)):
    data = file.file.read(rag.MAX_BYTES + 1)  # never read more than the limit
    doc = _kb_call(rag.ingest, file.filename, data, doc_type, replace, user["email"])
    audit.log(None, "kb.upload", "upload_document", {"filename": doc["filename"]}, {"chunks": doc["chunks"]},
              actor=user["email"])
    return doc


@app.delete("/kb/documents/{doc_id}")
def kb_delete(doc_id: str, user: dict = Depends(agent_user)):
    _kb_call(rag.delete_document, doc_id)
    audit.log(None, "kb.delete", "delete_document", {"doc_id": doc_id}, actor=user["email"])
    return {"deleted": doc_id}


@app.post("/kb/documents/{doc_id}/reindex")
def kb_reindex(doc_id: str, user: dict = Depends(agent_user)):
    return _kb_call(rag.reindex, doc_id)


@app.get("/kb/search")
def kb_search(q: str, doc_type: str = "", user: dict = Depends(agent_user)):
    if not q.strip() or len(q) > 300:
        raise HTTPException(400, "Enter a search question (max 300 characters).")
    return rag.search(q, doc_type or None, k=5)


# ------------------------------------------------------------------ audit logs
@app.get("/audit")
def audit_logs(q: str = "", case_id: str = "", page: int = 1, page_size: int = 25,
               user: dict = Depends(agent_user)):
    query = {}
    if case_id:
        query["case_id"] = case_id
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"tool": rx}, {"action": rx}, {"actor": rx}, {"error": rx}, {"case_id": rx},
                        {"input_summary": rx}, {"output_summary": rx}]
    page, page_size = max(page, 1), min(max(page_size, 1), 100)
    total = db.audit_logs.count_documents(query)
    items = list(db.audit_logs.find(query, {"_id": 0}).sort("ts", -1).skip((page - 1) * page_size).limit(page_size))
    return {"items": items, "total": total, "page": page, "pages": max(1, -(-total // page_size))}
