import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Search } from "lucide-react";
import { api, date, errMsg } from "../api";
import { Badge, Card, Empty, ErrorBox, Pager, Spinner } from "../components/ui.jsx";

const Stat = ({ label, value }) => (
  <Card><div className="text-xs text-slate-500">{label}</div><div className="text-2xl font-semibold">{value}</div></Card>
);

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [f, setF] = useState({ q: "", status: "", priority: "", sort: "created_at", order: "desc", page: 1 });

  useEffect(() => { api.get("/stats").then((r) => setStats(r.data)).catch((e) => setError(errMsg(e))); }, []);
  useEffect(() => {
    const t = setTimeout(() => {
      api.get("/cases", { params: { ...f, page_size: 8 } }).then((r) => setData(r.data)).catch((e) => setError(errMsg(e)));
    }, 250);
    return () => clearTimeout(t);
  }, [f]);

  const set = (k, v) => setF((s) => ({ ...s, [k]: v, page: k === "page" ? v : 1 }));
  const th = (key, label) => (
    <th className="cursor-pointer px-3 py-2 text-left" onClick={() => setF((s) => ({ ...s, sort: key, order: s.sort === key && s.order === "desc" ? "asc" : "desc" }))}>
      {label}{f.sort === key ? (f.order === "desc" ? " ↓" : " ↑") : ""}
    </th>
  );
  const sel = "rounded-lg border border-slate-300 px-2 py-1.5 text-sm";

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Support dashboard</h1>
      <ErrorBox text={error} />
      {!stats ? <Spinner /> : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Stat label="Total cases" value={stats.total_cases} />
            <Stat label="Open cases" value={stats.open_cases} />
            <Stat label="Pending approvals" value={stats.pending_approvals} />
            <Stat label="Completed cases" value={stats.completed_cases} />
            <Stat label="Refund requests" value={stats.refund_requests} />
            <Stat label="Avg resolution (h)" value={stats.avg_resolution_hours} />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {[["Cases by category", stats.by_category], ["Cases by status", stats.by_status]].map(([title, rows]) => (
              <Card key={title} title={title}>
                <div className="h-48">
                  <ResponsiveContainer>
                    <BarChart data={rows}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="name" tick={{ fontSize: 10 }} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                      <Tooltip /><Bar dataKey="value" fill="#4f46e5" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
      <Card title="Cases" right={
        <div className="flex flex-wrap gap-2">
          <div className="relative"><Search className="absolute left-2 top-2 h-4 w-4 text-slate-400" />
            <input className={`${sel} pl-8`} placeholder="Search..." value={f.q} onChange={(e) => set("q", e.target.value)} /></div>
          <select className={sel} value={f.status} onChange={(e) => set("status", e.target.value)}>
            <option value="">All statuses</option>
            {["OPEN", "PENDING_APPROVAL", "ESCALATED", "RESOLVED"].map((s) => <option key={s}>{s}</option>)}
          </select>
          <select className={sel} value={f.priority} onChange={(e) => set("priority", e.target.value)}>
            <option value="">All priorities</option>{["HIGH", "MEDIUM", "LOW"].map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>}>
        {!data ? <Spinner /> : data.items.length === 0 ? <Empty text="No cases match your filters." /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr>{th("case_id", "Case")}{th("customer_name", "Customer")}{th("order_id", "Order")}{th("category", "Category")}
                  {th("priority", "Priority")}{th("status", "Status")}{th("created_at", "Created")}{th("assigned_agent", "Agent")}</tr>
              </thead>
              <tbody>
                {data.items.map((c) => (
                  <tr key={c.case_id} className="border-t hover:bg-slate-50">
                    <td className="px-3 py-2"><Link className="text-indigo-600 hover:underline" to={`/cases/${c.case_id}`}>{c.case_id}</Link></td>
                    <td className="px-3 py-2">{c.customer_name}</td><td className="px-3 py-2">{c.order_id || "-"}</td>
                    <td className="px-3 py-2">{c.category}</td><td className="px-3 py-2"><Badge text={c.priority} /></td>
                    <td className="px-3 py-2"><Badge text={c.status} /></td><td className="px-3 py-2">{date(c.created_at)}</td>
                    <td className="px-3 py-2">{c.assigned_agent || "Unassigned"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager page={data.page} pages={data.pages} onChange={(p) => set("page", p)} />
          </div>
        )}
      </Card>
    </div>
  );
}
