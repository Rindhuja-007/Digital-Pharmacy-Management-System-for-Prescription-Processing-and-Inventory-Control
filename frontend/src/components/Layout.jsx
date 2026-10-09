import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import api from "../api";
import { useAuth } from "../auth";

const LINKS = [
  ["/", "Dashboard"], ["/prescriptions", "Prescriptions"], ["/medicines", "Medicines"],
  ["/inventory", "Inventory"], ["/transactions", "Transactions"], ["/alerts", "Alerts"],
];

export default function Layout() {
  const { user, logout, isAdmin } = useAuth();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const location = useLocation();

  useEffect(() => { setOpen(false); }, [location.pathname]);
  useEffect(() => {
    api.get("/alerts", { params: { unread_only: true } }).then((r) => setUnread(r.data.length)).catch(() => {});
  }, [location.pathname]);

  return (
    <div className="shell">
      <div className="topbar">
        <button onClick={() => setOpen(true)} aria-label="Open menu">☰</button>
        <span className="brand">PharmaCare</span>
      </div>
      {open && <div className="scrim" onClick={() => setOpen(false)} />}
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="brand">PharmaCare<small>Pharmacist-assisted dispensing</small></div>
        <nav className="nav">
          {LINKS.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              {label}
              {label === "Alerts" && unread > 0 && <span className="count">{unread}</span>}
            </NavLink>
          ))}
          {isAdmin && <NavLink to="/staff" className={({ isActive }) => (isActive ? "active" : "")}>Staff</NavLink>}
        </nav>
        <div className="userbox">
          <strong>{user.name}</strong>
          <span>{user.role === "ADMIN" ? "Administrator" : "Pharmacist"}</span>
          <div className="spacer" />
          <button className="btn secondary small" onClick={logout}>Sign out</button>
        </div>
      </aside>
      <main className="main"><Outlet /></main>
    </div>
  );
}
