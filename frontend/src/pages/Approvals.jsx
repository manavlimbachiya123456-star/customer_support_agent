import { useCallback, useEffect, useState } from "react";
import { api, date, errMsg } from "../api";
import { Badge, Button, Card, Empty, ErrorBox, Spinner } from "../components/ui.jsx";

function Item({ a, onDone }) {
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState(a.amount ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const call = async (fn) => {
    setBusy(true); setError("");
    try { await fn(); onDone(); } catch (e) { setError(errMsg(e)); } finally { setBusy(false); }
  };
  const decide = (approve) => call(() => api.post(`/approvals/${a.approval_id}/decide`, { approve, reason }));
  const modify = () => call(() => api.post(`/approvals/${a.approval_id}/modify`, { amount: Number(amount) }));

  return (
    <Card>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <b>{a.type.replace("_", " ")}</b><Badge text={a.status} /><span className="text-sm text-slate-500">{a.approval_id} · {a.case_id} · {date(a.created_at)}</span>
        {a.amount != null && <span className="ml-auto text-lg font-semibold">Rs {a.amount}</span>}
      </div>
      <div className="grid gap-3 text-sm md:grid-cols-2">
        <div>
          <p><span className="text-slate-500">Customer:</span> {a.customer_name} · <span className="text-slate-500">Order:</span> {a.order_id}</p>
          <p className="mt-1"><span className="text-slate-500">Reason:</span> {a.reason}</p>
          {a.params?.new_shipping_address && <p className="mt-1"><span className="text-slate-500">New address:</span> {a.params.new_shipping_address}</p>}
          <p className="mt-2 text-xs font-semibold uppercase text-slate-500">Supporting evidence</p>
          <ul className="list-disc pl-4">{Object.entries(a.evidence || {}).map(([k, v]) => <li key={k}>{k.replaceAll("_", " ")}: {String(v)}</li>)}</ul>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">Policy rules</p>
          {(a.policy_excerpts || []).map((p, i) => <blockquote key={i} className="mb-1 border-l-4 border-indigo-200 pl-2 text-xs">{p.text}<div className="text-slate-400">{p.source} · chunk {p.chunk_id}</div></blockquote>)}
          {!a.policy_excerpts?.length && <p className="text-xs text-slate-400">No excerpts attached.</p>}
        </div>
      </div>
      {a.failure_reason && <p className="mt-2 rounded bg-red-50 p-2 text-sm text-red-700">Failed: {a.failure_reason} (attempt {a.attempts})</p>}
      {a.decision_reason && <p className="mt-2 text-sm text-slate-600">Decision by {a.decided_by}: {a.decision_reason}</p>}
      {a.execution_result && <p className="mt-1 text-sm text-emerald-700">Result: {JSON.stringify(a.execution_result)}</p>}
      <ErrorBox text={error} />
      {a.status === "PENDING_APPROVAL" && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {a.type === "REFUND" && <>
            <input type="number" className="w-28 rounded-lg border px-2 py-1.5 text-sm" value={amount} onChange={(e) => setAmount(e.target.value)} />
            <Button variant="ghost" disabled={busy} onClick={modify}>Change amount</Button></>}
          <input className="min-w-[200px] flex-1 rounded-lg border px-3 py-1.5 text-sm" placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <Button variant="ok" disabled={busy || reason.trim().length < 3} onClick={() => decide(true)}>Approve</Button>
          <Button variant="danger" disabled={busy || reason.trim().length < 3} onClick={() => decide(false)}>Reject</Button>
        </div>)}
      {a.status === "FAILED" && <Button className="mt-3" disabled={busy} onClick={() => call(() => api.post(`/approvals/${a.approval_id}/retry`))}>Retry execution</Button>}
    </Card>
  );
}

export default function Approvals() {
  const [status, setStatus] = useState("PENDING_APPROVAL");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    api.get("/approvals", { params: { status } }).then((r) => setData(r.data)).catch((e) => setError(errMsg(e)));
  }, [status]);
  useEffect(() => { setData(null); load(); }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Approval Center</h1>
        <select className="rounded-lg border px-2 py-1.5 text-sm" value={status} onChange={(e) => setStatus(e.target.value)}>
          {["PENDING_APPROVAL", "COMPLETED", "REJECTED", "FAILED", ""].map((s) => <option key={s} value={s}>{s || "ALL"}</option>)}
        </select>
      </div>
      <ErrorBox text={error} />
      {!data ? <Spinner /> : data.items.length === 0 ? <Empty text="Nothing here. All caught up." /> :
        data.items.map((a) => <Item key={a.approval_id} a={a} onDone={load} />)}
    </div>
  );
}
