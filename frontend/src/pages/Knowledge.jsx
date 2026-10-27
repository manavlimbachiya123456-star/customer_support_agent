import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Trash2, Upload } from "lucide-react";
import { api, date, errMsg } from "../api";
import { Badge, Button, Card, Empty, ErrorBox, Spinner } from "../components/ui.jsx";

export default function Knowledge() {
  const [docs, setDocs] = useState(null);
  const [error, setError] = useState("");
  const [file, setFile] = useState(null);
  const [docType, setDocType] = useState("");
  const [replace, setReplace] = useState(false);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => api.get("/kb/documents").then((r) => setDocs(r.data)).catch((e) => setError(errMsg(e))), []);
  useEffect(() => { load(); }, [load]);

  const act = async (fn) => { setBusy(true); setError(""); try { await fn(); await load(); } catch (e) { setError(errMsg(e)); } finally { setBusy(false); } };
  const upload = () => {
    const fd = new FormData();
    fd.append("file", file); fd.append("doc_type", docType); fd.append("replace", replace);
    act(() => api.post("/kb/upload", fd)).then(() => setFile(null));
  };
  const search = async (e) => {
    e.preventDefault(); setError("");
    try { setHits((await api.get("/kb/search", { params: { q } })).data); } catch (err) { setError(errMsg(err)); }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Policy and knowledge base</h1>
      <ErrorBox text={error} />
      <Card title="Upload a document (PDF, Markdown or TXT, max 5 MB)">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <input type="file" accept=".pdf,.md,.txt" onChange={(e) => setFile(e.target.files[0])} />
          <select className="rounded-lg border px-2 py-1.5" value={docType} onChange={(e) => setDocType(e.target.value)}>
            <option value="">Auto-detect type</option>{["refund", "shipping", "cancellation", "return", "faq"].map((t) => <option key={t}>{t}</option>)}
          </select>
          <label className="flex items-center gap-1"><input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />Replace if same name</label>
          <Button disabled={!file || busy} onClick={upload}><Upload className="mr-1 inline h-4 w-4" />Upload and index</Button>
        </div>
        <p className="mt-2 text-xs text-slate-500">Uploaded text is treated as reference data. It can never change the assistant's rules or approvals.</p>
      </Card>
      <Card title="Indexed documents">
        {!docs ? <Spinner /> : docs.length === 0 ? <Empty text="No documents yet." /> : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500"><tr><th className="py-1">File</th><th>Type</th><th>Status</th><th>Chunks</th><th>Uploaded</th><th /></tr></thead>
            <tbody>{docs.map((d) => (
              <tr key={d.doc_id} className="border-t">
                <td className="py-2">{d.filename}{d.suspicious && <span className="ml-2 text-xs text-red-600">⚠ contains instruction-like text</span>}</td>
                <td>{d.doc_type}</td><td><Badge text={d.status} />{d.error && <span className="ml-1 text-xs text-red-600">{d.error}</span>}</td>
                <td>{d.chunks}</td><td>{date(d.uploaded_at)}</td>
                <td className="space-x-2 text-right">
                  <button title="Re-index" disabled={busy} onClick={() => act(() => api.post(`/kb/documents/${d.doc_id}/reindex`))}><RefreshCw className="inline h-4 w-4 text-slate-500" /></button>
                  <button title="Delete" disabled={busy} onClick={() => confirm(`Delete ${d.filename}?`) && act(() => api.delete(`/kb/documents/${d.doc_id}`))}><Trash2 className="inline h-4 w-4 text-red-500" /></button>
                </td></tr>))}</tbody>
          </table>)}
      </Card>
      <Card title="Search indexed content">
        <form onSubmit={search} className="flex gap-2">
          <input className="flex-1 rounded-lg border px-3 py-1.5 text-sm" placeholder="e.g. How long do I have to ask for a refund?" value={q} onChange={(e) => setQ(e.target.value)} />
          <Button>Search</Button>
        </form>
        {hits && (hits.length === 0 ? <Empty text="No relevant passages found." /> : hits.map((h, i) => (
          <blockquote key={i} className="mt-3 border-l-4 border-indigo-200 pl-3 text-sm">{h.text}
            <div className="text-xs text-slate-400">{h.source} · chunk {h.chunk_id} · page {h.page ?? "-"} · score {h.score}</div></blockquote>)))}
      </Card>
    </div>
  );
}
