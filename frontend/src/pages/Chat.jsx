import { useEffect, useRef, useState } from "react";
import { Send, CheckCircle2, XCircle, Wrench } from "lucide-react";
import { api, errMsg } from "../api";
import { Badge, Button, Card, ErrorBox, Spinner } from "../components/ui.jsx";

export default function Chat() {
  const [orders, setOrders] = useState([]);
  const [messages, setMessages] = useState([]);
  const [caseId, setCaseId] = useState(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [last, setLast] = useState(null); // last agent result: steps + evidence
  const end = useRef(null);

  useEffect(() => { api.get("/orders").then((r) => setOrders(r.data)).catch(() => {}); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);

  // After a human decides, the backend adds the REAL outcome to the case. Poll for it.
  useEffect(() => {
    if (!caseId) return;
    const t = setInterval(() => {
      api.get(`/cases/${caseId}`).then((r) => setMessages(r.data.messages)).catch(() => {});
    }, 5000);
    return () => clearInterval(t);
  }, [caseId]);

  const send = async (e) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput(""); setError(""); setBusy(true);
    setMessages((m) => [...m, { role: "user", text }]);
    try {
      const { data } = await api.post("/chat", { message: text, case_id: caseId });
      setCaseId(data.case_id);
      setLast(data);
      setMessages((m) => [...m, { role: "assistant", text: data.answer, meta: { decision: data.decision } }]);
    } catch (err) { setError(errMsg(err)); } finally { setBusy(false); }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <Card title={caseId ? `Conversation (${caseId})` : "New conversation"} className="flex h-[calc(100vh-3rem)] flex-col">
        <div className="mb-3 flex flex-wrap gap-2">
          {orders.slice(0, 6).map((o) => (
            <button key={o.order_id} onClick={() => setInput((v) => `${v} ${o.order_id}`.trim())}
              className="rounded-full border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50">
              {o.order_id} <span className="text-slate-400">{o.status}</span>
            </button>
          ))}
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto pr-1">
          {messages.length === 0 && (
            <p className="text-sm text-slate-400">Try: "My order ORD-1042 has not arrived. It was supposed to be delivered last week. Can I get a refund?"</p>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${
              m.role === "user" ? "ml-auto bg-indigo-600 text-white" : "bg-slate-100"}`}>
              {m.text}
              {m.meta?.decision && m.role !== "user" && <div className="mt-1"><Badge text={m.meta.decision} /></div>}
            </div>
          ))}
          {busy && <Spinner label="Investigating your order..." />}
          <div ref={end} />
        </div>
        <ErrorBox text={error} />
        <form onSubmit={send} className="mt-3 flex gap-2">
          <input value={input} onChange={(e) => setInput(e.target.value)} maxLength={1000}
            placeholder="Ask about an order, refund, delivery or policy..."
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          <Button disabled={busy}><Send className="h-4 w-4" /></Button>
        </form>
      </Card>

      <div className="space-y-4">
        <Card title="Investigation progress">
          {!last ? <p className="text-sm text-slate-400">Steps the assistant takes will appear here.</p> : (
            <ul className="space-y-2 text-sm">
              {last.steps.map((s, i) => (
                <li key={i} className="flex items-start gap-2">
                  {s.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" /> : <XCircle className="mt-0.5 h-4 w-4 text-red-500" />}
                  <span><Wrench className="mr-1 inline h-3 w-3 text-slate-400" />{s.tool}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Evidence (verified from our systems)">
          {!last?.evidence?.verified?.length ? <p className="text-sm text-slate-400">No evidence yet.</p> : (
            <ul className="list-disc space-y-1 pl-4 text-sm">{last.evidence.verified.map((v, i) => <li key={i}>{v}</li>)}</ul>
          )}
          {last?.proposed_action && (
            <p className="mt-3 rounded-lg bg-amber-50 p-2 text-xs text-amber-800">
              Request {last.proposed_action.approval_id} is waiting for a human agent. Nothing has been changed yet.
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}
