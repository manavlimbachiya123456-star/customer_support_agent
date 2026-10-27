import { Loader2 } from "lucide-react";

const COLORS = {
  OPEN: "bg-blue-100 text-blue-700", PENDING_APPROVAL: "bg-amber-100 text-amber-800",
  ESCALATED: "bg-red-100 text-red-700", RESOLVED: "bg-emerald-100 text-emerald-700",
  APPROVED: "bg-sky-100 text-sky-700", REJECTED: "bg-slate-200 text-slate-700",
  EXECUTING: "bg-indigo-100 text-indigo-700", COMPLETED: "bg-emerald-100 text-emerald-700",
  FAILED: "bg-red-100 text-red-700", HIGH: "bg-red-100 text-red-700", MEDIUM: "bg-amber-100 text-amber-800",
  LOW: "bg-slate-100 text-slate-600", INDEXED: "bg-emerald-100 text-emerald-700", INDEXING: "bg-amber-100 text-amber-800",
};

export const Badge = ({ text }) => (
  <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${COLORS[text] || "bg-slate-100 text-slate-700"}`}>
    {String(text ?? "-").replaceAll("_", " ")}
  </span>
);

export const Card = ({ title, children, className = "", right }) => (
  <section className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${className}`}>
    {title && (
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
        {right}
      </div>
    )}
    {children}
  </section>
);

export const Spinner = ({ label = "Loading..." }) => (
  <div className="flex items-center gap-2 p-6 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />{label}</div>
);

export const Empty = ({ text }) => <div className="p-6 text-center text-sm text-slate-400">{text}</div>;

export const ErrorBox = ({ text }) => text ? <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{text}</div> : null;

export const Button = ({ children, variant = "primary", className = "", ...p }) => {
  const v = { primary: "bg-indigo-600 text-white hover:bg-indigo-700", ghost: "border border-slate-300 hover:bg-slate-50",
    danger: "bg-red-600 text-white hover:bg-red-700", ok: "bg-emerald-600 text-white hover:bg-emerald-700" }[variant];
  return <button {...p} className={`rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-50 ${v} ${className}`}>{children}</button>;
};

export const Pager = ({ page, pages, onChange }) => (
  <div className="flex items-center justify-between pt-3 text-sm text-slate-500">
    <span>Page {page} of {pages}</span>
    <div className="flex gap-2">
      <Button variant="ghost" disabled={page <= 1} onClick={() => onChange(page - 1)}>Previous</Button>
      <Button variant="ghost" disabled={page >= pages} onClick={() => onChange(page + 1)}>Next</Button>
    </div>
  </div>
);
