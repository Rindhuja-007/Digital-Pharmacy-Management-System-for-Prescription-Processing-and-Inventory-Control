import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./components/Layout";
import Alerts from "./pages/Alerts";
import Dashboard from "./pages/Dashboard";
import Inventory from "./pages/Inventory";
import Login from "./pages/Login";
import Medicines from "./pages/Medicines";
import PrescriptionDesk from "./pages/PrescriptionDesk";
import Prescriptions from "./pages/Prescriptions";
import Staff from "./pages/Staff";
import Transactions from "./pages/Transactions";

export default function App() {
  const { user, loading, isAdmin } = useAuth();
  if (loading) return <p style={{ padding: "2rem" }}>Loading…</p>;
  if (!user) return <Routes><Route path="*" element={<Login />} /></Routes>;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="prescriptions" element={<Prescriptions />} />
        <Route path="prescriptions/:id" element={<PrescriptionDesk />} />
        <Route path="medicines" element={<Medicines />} />
        <Route path="inventory" element={<Inventory />} />
        <Route path="transactions" element={<Transactions />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="staff" element={isAdmin ? <Staff /> : <Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
