import { Navigate, Route, Routes } from "react-router-dom";
import { getUser, isStaff } from "./api";
import Layout from "./components/Layout.jsx";
import Login from "./pages/Login.jsx";
import Chat from "./pages/Chat.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import CaseDetail from "./pages/CaseDetail.jsx";
import Approvals from "./pages/Approvals.jsx";
import Knowledge from "./pages/Knowledge.jsx";
import Audit from "./pages/Audit.jsx";

function Guard({ staff, children }) {
  const u = getUser();
  if (!u) return <Navigate to="/login" replace />;
  if (staff && !isStaff(u)) return <Navigate to="/chat" replace />;
  if (staff === false && isStaff(u)) return <Navigate to="/dashboard" replace />;
  return children;
}

export default function App() {
  const u = getUser();
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Layout />}>
        <Route path="/chat" element={<Guard staff={false}><Chat /></Guard>} />
        <Route path="/dashboard" element={<Guard staff><Dashboard /></Guard>} />
        <Route path="/cases/:id" element={<Guard staff><CaseDetail /></Guard>} />
        <Route path="/approvals" element={<Guard staff><Approvals /></Guard>} />
        <Route path="/knowledge" element={<Guard staff><Knowledge /></Guard>} />
        <Route path="/audit" element={<Guard staff><Audit /></Guard>} />
      </Route>
      <Route path="*" element={<Navigate to={u ? (isStaff(u) ? "/dashboard" : "/chat") : "/login"} replace />} />
    </Routes>
  );
}
