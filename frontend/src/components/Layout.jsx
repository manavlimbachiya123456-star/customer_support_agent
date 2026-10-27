import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { MessageSquare, LayoutDashboard, CheckSquare, BookOpen, ScrollText, LogOut, Bot } from "lucide-react";
import { getUser, isStaff } from "../api";

export default function Layout() {
  const user = getUser();
  const nav = useNavigate();
  const items = isStaff(user)
    ? [["/dashboard", "Dashboard", LayoutDashboard], ["/approvals", "Approval Center", CheckSquare],
       ["/knowledge", "Knowledge Base", BookOpen], ["/audit", "Audit Logs", ScrollText]]
    : [["/chat", "Support Chat", MessageSquare]];
  const link = ({ isActive }) =>
    `flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${isActive ? "bg-indigo-50 font-medium text-indigo-700" : "text-slate-600 hover:bg-slate-100"}`;
  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white p-4">
        <div className="mb-6 flex items-center gap-2 font-bold text-indigo-700"><Bot className="h-5 w-5" />SupportPilot AI</div>
        <nav className="flex flex-1 flex-col gap-1">
          {items.map(([to, label, Icon]) => (
            <NavLink key={to} to={to} className={link}><Icon className="h-4 w-4" />{label}</NavLink>
          ))}
        </nav>
        <div className="border-t pt-3 text-xs text-slate-500">
          <div className="font-medium text-slate-700">{user?.name}</div>
          <div className="mb-2">{user?.role.replace("_", " ")}</div>
          <button className="flex items-center gap-1 text-slate-600 hover:text-red-600"
            onClick={() => { localStorage.clear(); nav("/login"); }}><LogOut className="h-3 w-3" />Log out</button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 p-6"><Outlet /></main>
    </div>
  );
}
