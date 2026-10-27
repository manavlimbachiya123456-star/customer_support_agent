# SupportPilot AI: Customer Support Action Agent

An agentic customer-support app for an e-commerce store. A single AI agent investigates a request with real data
(orders, shipments, policies via RAG), then **proposes** actions. Only a **human support agent** can approve and execute them.
All money movement is simulated.

```
React (Vite, Tailwind)  ->  FastAPI  ->  MongoDB (orders, cases, approvals, audit)
                                 |-->  Qdrant (policy vectors, RAG)
                                 |-->  Gemini 2.5 Flash (tool calling)   [or the built-in mock agent]
```

## What it does
* **Customer chat**: ask about orders, delivery, refunds, cancellations, returns, address changes, policies. Shows the investigation steps and verified evidence.
* **Agent dashboard**: KPIs, charts, searchable / filterable / sortable / paginated case table.
* **Case page**: request, order and delivery timeline, policy excerpts, tools called, decision + confidence, and a clear split between *verified*, *AI hypothesis*, *proposed* and *completed*.
* **Approval center**: approve / reject with a reason, change a refund amount (which invalidates the old fingerprint), retry failed executions.
* **Knowledge base**: upload PDF / MD / TXT, replace, delete, re-index, search with citations.
* **Audit logs**: every tool call and every decision, searchable. Secrets and personal fields are redacted.

## Quick start (no keys, no database server)
```bash
cp .env.example backend/.env
cd backend
pip install -r requirements-dev.txt
uvicorn main:app --port 8000          # demo data is seeded automatically (MONGO_URI=mock)

# second terminal
cd frontend
npm install
npm run dev                            # http://localhost:5173
```
With `MOCK_LLM=true` a deterministic rule-based agent runs the same tools and the same business rules. 
**To use Gemini 2.5 Flash:** set `MOCK_LLM=false` and `GEMINI_API_KEY=...` in `backend/.env`, then restart.

### Docker
```bash
cp .env.example .env      # set MOCK_LLM / GEMINI_API_KEY / JWT_SECRET
docker compose up --build  # frontend: http://localhost:5173  API: http://localhost:8000/docs
```

## Demo accounts (local only)
| Role | Email | Password |
|---|---|---|
| Customer (Aarav) | aarav@example.com | customer123 |
| Support agent | agent@supportpilot.com | agent123 |
| Admin | admin@supportpilot.com | admin123 |

All 15 customers use `<firstname>@example.com` / `customer123`.

**Try the spec's example:** log in as Aarav and send *"My order ORD-1042 has not arrived. It was supposed to be delivered last week. Can I get a refund?"*.
The agent checks the order and shipment, retrieves refund/shipping policy, runs the rules, and creates a pending refund. Log in as the support agent, open **Approval Center**, approve it, and the customer chat shows the real outcome.

Useful orders: `ORD-1042` delayed (eligible) · `ORD-1020` delivered (return only) · `ORD-1021` outside window · `ORD-1023` already refunded · `ORD-1026` cancellable · `ORD-1031` shipped (not cancellable) · `ORD-1047` no tracking data (escalates).

## How the safety design works
1. **The model never decides business outcomes.** `rules.py` (deterministic, limits in `business_rules.json`) decides eligibility. The final decision is derived from what the tools returned, not from model text.
2. **The model can only propose.** Action tools create a `PENDING_APPROVAL` record. Only `approvals.decide()` (support-agent JWT required) can approve and execute.
3. **State machine:** `PROPOSED -> PENDING_APPROVAL -> APPROVED | REJECTED -> EXECUTING -> COMPLETED | FAILED`. Transitions are atomic.
4. **Approval is bound to the exact proposal** through a SHA-256 fingerprint. Editing a proposal changes the fingerprint and voids earlier approval.
5. **Re-check before executing**, idempotency keys (unique index on payments), simulated gateway, then **verification** of the real result. Failed runs can be retried (max 3), permanent failures cannot.
6. **Customer isolation:** tools are bound to the logged-in customer by the server, so the model cannot pick another customer. Other people's orders look like "not found".
7. **Prompt-injection resistance:** policy text is passed as quoted reference data, instruction-like text is flagged, and answers claiming an action is done are corrected by a guard.
8. **Other:** JWT + roles, rate limiting, upload validation (type, size, empty, duplicate), safe error messages, bounded tool loop with timeouts and retries for read-only tools, full audit trail.

## Tests and evaluation
```bash
pytest tests -q                 # 50 tests: rules, tools, RAG, approvals, security, audit
python eval/run_eval.py         # 18 scenarios + retrieval check; prints metrics
```
`eval/run_eval.py` reports: policy retrieval hit@3, correct decisions, unsupported claims, data leaks on unauthorized attempts, task completion, and executed actions verified. It runs on the mock agent by default; set `MOCK_LLM=false` to score Gemini on the same scenarios.

## Project layout
```
backend/   main.py (API) agent.py (loop + mock) tools.py rules.py approvals.py rag.py cases.py
           services.py (fake shipping + payment) audit.py db.py models.py seed.py
frontend/  src/pages: Login Chat Dashboard CaseDetail Approvals Knowledge Audit
policies/  sample refund, shipping, cancellation, return and FAQ documents
tests/  eval/
```

## API (interactive docs at `/docs`)
`POST /auth/login` · `GET /auth/me` · `POST /chat` · `GET /orders` · `GET /cases` · `GET /cases/{id}` · `GET /stats` ·
`GET /approvals` · `POST /approvals/{id}/decide|retry|modify` · `GET /reconcile` ·
`GET /kb/documents` · `POST /kb/upload` · `DELETE /kb/documents/{id}` · `POST /kb/documents/{id}/reindex` · `GET /kb/search` · `GET /audit`

## Notes and limits
* This is a portfolio project: the rate limiter is in-memory and the payment gateway is simulated.
* Customer chat uses FastAPI directly (no separate Express service).
* Set a strong `JWT_SECRET` before exposing it anywhere.
