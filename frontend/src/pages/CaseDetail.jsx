import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api, date, errMsg } from "../api";
import { Badge, Card, ErrorBox, Spinner } from "../components/ui.jsx";

const Tag = ({ color, children }) => <span className={`mr-2 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${color}`}>{children}</span>;

export default function CaseDetail() {
  const { id } = useParams();
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { api.get(`/cases/${id}`).then((r) => setD(r.data)).catch((e) => setError(errMsg(e))); }, [id]);
  if (error) return <ErrorBox text={error} />;
  if (!d) return <Spinner />;

  const { case: c, order, shipment, customer, approvals, messages } = d;
  const inv = c.investigation;
  const done = approvals.filter((a) => a.status === "COMPLETED");

  return (
    <div className="space-y-4">
      <Link to="/dashboard" className="flex items-center gap-1 text-sm text-indigo-600"><ArrowLeft className="h-4 w-4" />Back</Link>
      <div className="flex items-center gap-3"><h1 className="text-xl font-semibold">{c.case_id}</h1><Badge text={c.status} /><Badge text={c.priority} /><span className="text-sm text-slate-500">{c.category}</span></div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Customer request"><p className="text-sm">{c.request}</p>
          <p className="mt-2 text-xs text-slate-500">Created {date(c.created_at)} · Agent: {c.assigned_agent || "Unassigned"}</p></Card>
        <Card title="Customer and order">
          <dl className="grid grid-cols-2 gap-1 text-sm">
            <dt className="text-slate-500">Customer</dt><dd>{customer?.name} ({customer?.tier})</dd>
            <dt className="text-slate-500">Order</dt><dd>{order ? `${order.order_id} · ${order.status}` : "-"}</dd>
            <dt className="text-slate-500">Total</dt><dd>{order ? `Rs ${order.total}` : "-"}</dd>
            <dt className="text-slate-500">Items</dt><dd>{order?.items?.map((i) => `${i.qty}× ${i.name}`).join(", ") || "-"}</dd>
          </dl>
        </Card>
        <Card title="Delivery timeline">
          {!shipment ? <p className="text-sm text-slate-400">No shipment record. This is NOT proof that the package is lost.</p> : (
            <ol className="space-y-1 border-l-2 border-slate-200 pl-3 text-sm">
              {(shipment.events || []).map((e, i) => <li key={i}><span className="text-slate-500">{String(e.date || e.ts).slice(0, 10)}</span> · {e.status} <span className="text-slate-400">{e.location}</span></li>)}
              <li className="text-slate-500">Carrier {shipment.carrier} · expected {String(shipment.expected_date || "-").slice(0, 10)}</li>
            </ol>
          )}
        </Card>
        <Card title="Decision">
          {!inv ? <p className="text-sm text-slate-400">No AI investigation yet.</p> : (
            <div className="space-y-2 text-sm">
              <div><Badge text={inv.decision} /> <span className="ml-2 text-xs text-slate-500">Confidence: <b>{inv.confidence}</b></span></div>
              <p>{inv.answer}</p>
              {inv.uncertainties?.length > 0 && <ul className="list-disc pl-4 text-amber-700">{inv.uncertainties.map((u, i) => <li key={i}>{u}</li>)}</ul>}
              <p className="text-xs text-slate-400">Model: {inv.model || "mock (rule-based)"}</p>
            </div>
          )}
        </Card>
      </div>

      <Card title="Evidence: what is verified vs. what is guessed">
        <ul className="space-y-1 text-sm">
          {inv?.evidence?.verified?.map((v, i) => <li key={"v" + i}><Tag color="bg-emerald-100 text-emerald-700">Verified</Tag>{v}</li>)}
          {inv?.evidence?.hypotheses?.map((v, i) => <li key={"h" + i}><Tag color="bg-violet-100 text-violet-700">AI hypothesis</Tag>{v}</li>)}
          {approvals.map((a) => <li key={a.approval_id}><Tag color="bg-amber-100 text-amber-800">Proposed</Tag>{a.type} {a.amount ? `Rs ${a.amount}` : ""} → <Badge text={a.status} /></li>)}
          {done.map((a) => <li key={"d" + a.approval_id}><Tag color="bg-sky-100 text-sky-700">Completed</Tag>{a.type} verified: {a.execution_result?.verified ? "yes" : "no"} {a.execution_result?.txn_id || a.execution_result?.rma || ""}</li>)}
        </ul>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Policy excerpts">
          {!inv?.policy_excerpts?.length ? <p className="text-sm text-slate-400">None retrieved.</p> :
            inv.policy_excerpts.map((p, i) => (
              <blockquote key={i} className="mb-2 border-l-4 border-indigo-200 pl-3 text-sm">{p.text}
                <div className="text-xs text-slate-400">{p.source} · chunk {p.chunk_id} · page {p.page ?? "-"} · score {p.score}</div></blockquote>))}
        </Card>
        <Card title="Tools called by the AI">
          {!inv?.steps?.length ? <p className="text-sm text-slate-400">None.</p> : (
            <ol className="space-y-1 text-sm">{inv.steps.map((s, i) => (
              <li key={i}><code className="rounded bg-slate-100 px-1">{s.tool}</code> {s.ok ? "✓" : "✗"} <span className="text-xs text-slate-400">{s.duration_ms} ms</span>
                <div className="truncate text-xs text-slate-500">{JSON.stringify(s.args)}</div></li>))}</ol>)}
        </Card>
      </div>

      <Card title="Conversation">
        <div className="space-y-2 text-sm">{messages.map((m) => (
          <div key={m.message_id}><b>{m.role === "user" ? "Customer" : "Assistant"}:</b> {m.text}</div>))}</div>
      </Card>
      {approvals.some((a) => a.status === "PENDING_APPROVAL") && <Link className="text-sm text-indigo-600 underline" to="/approvals">Open the Approval Center</Link>}
    </div>
  );
}
