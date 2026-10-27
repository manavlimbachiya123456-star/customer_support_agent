import { useEffect, useState } from "react";
import { api, date, errMsg } from "../api";
import { Badge, Card, Empty, ErrorBox, Pager, Spinner } from "../components/ui.jsx";

export default function Audit() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const t = setTimeout(() => {
      api.get("/audit", { params: { q, page, page_size: 15 } }).then((r) => setData(r.data)).catch((e) => setError(errMsg(e)));
    }, 250);
    return () => clearTimeout(t);
  }, [q, page]);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Audit logs</h1>
      <ErrorBox text={error} />
      <Card right={<input className="rounded-lg border px-3 py-1.5 text-sm" placeholder="Search tool, case, actor, error..." value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />}>
        {!data ? <Spinner /> : data.items.length === 0 ? <Empty text="No log entries." /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-left uppercase text-slate-500"><tr>
                {["Time", "Case", "Actor", "Tool", "Action", "Input", "Output", "Approval", "Execution", "Error"].map((h) => <th key={h} className="px-2 py-2">{h}</th>)}</tr></thead>
              <tbody>{data.items.map((l) => (
                <tr key={l.audit_id} className="border-t align-top">
                  <td className="whitespace-nowrap px-2 py-1">{date(l.ts)}</td><td className="px-2">{l.case_id || "-"}</td><td className="px-2">{l.actor}</td>
                  <td className="px-2">{l.tool}</td><td className="px-2">{l.action}</td>
                  <td className="max-w-[180px] break-words px-2 text-slate-500">{l.input_summary}</td><td className="max-w-[220px] break-words px-2 text-slate-500">{l.output_summary}</td>
                  <td className="px-2">{l.approval_status && <Badge text={l.approval_status} />}</td><td className="px-2">{l.execution_status && <Badge text={l.execution_status} />}</td>
                  <td className="px-2 text-red-600">{l.error}</td></tr>))}</tbody>
            </table>
            <Pager page={data.page} pages={data.pages} onChange={setPage} />
          </div>)}
      </Card>
    </div>
  );
}
