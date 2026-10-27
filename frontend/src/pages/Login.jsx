import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot } from "lucide-react";
import { api, errMsg } from "../api";
import { Button, ErrorBox } from "../components/ui.jsx";

const DEMO = [
  ["Customer (Aarav)", "aarav@example.com", "customer123"],
  ["Support agent", "agent@supportpilot.com", "agent123"],
  ["Admin", "admin@supportpilot.com", "admin123"],
];

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const { data } = await api.post("/auth/login", { email, password });
      localStorage.setItem("token", data.token);
      localStorage.setItem("user", JSON.stringify(data.user));
      nav(data.user.role === "customer" ? "/chat" : "/dashboard");
    } catch (err) { setError(errMsg(err)); } finally { setBusy(false); }
  };

  const input = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm";
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-3 rounded-xl border bg-white p-6 shadow-sm">
        <div className="flex items-center gap-2 text-lg font-bold text-indigo-700"><Bot />SupportPilot AI</div>
        <input className={input} placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className={input} type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <ErrorBox text={error} />
        <Button className="w-full" disabled={busy}>{busy ? "Signing in..." : "Sign in"}</Button>
        <div className="border-t pt-3 text-xs text-slate-500">
          Demo accounts (local only):
          {DEMO.map(([label, e, p]) => (
            <button type="button" key={e} className="mt-1 block text-indigo-600 hover:underline"
              onClick={() => { setEmail(e); setPassword(p); }}>{label}: {e}</button>
          ))}
        </div>
      </form>
    </div>
  );
}
