import { useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import { Badge, Banner, PageHead } from "../components/ui";
import { dateTime } from "../format";

const BLANK = { name: "", username: "", email: "", password: "", role: "PHARMACIST" };

export default function Staff() {
  const { user: me } = useAuth();
  const [rows, setRows] = useState(null);
  const [form, setForm] = useState(BLANK);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api.get("/auth/staff").then((r) => setRows(r.data)).catch((e) => setError(errorMessage(e)));
  useEffect(() => { load(); }, []);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const act = async (fn, message) => {
    setError(""); setOk("");
    try { await fn(); setOk(message); load(); } catch (err) { setError(errorMessage(err)); }
  };
  const create = async (e) => {
    e.preventDefault(); setBusy(true);
    await act(async () => { await api.post("/auth/staff", form); setForm(BLANK); }, `Account created for ${form.username}.`);
    setBusy(false);
  };

  return (
    <>
      <PageHead title="Staff" subtitle="Accounts, roles, and admin approvals" />
      <Banner onClose={() => setError("")}>{error}</Banner>
      <Banner kind="ok" onClose={() => setOk("")}>{ok}</Banner>

      <form className="panel" onSubmit={create}>
        <h2>Add a staff account</h2>
        <div className="grid">
          <label>Full name<input required value={form.name} onChange={set("name")} /></label>
          <label>Username<input required value={form.username} onChange={set("username")} /></label>
          <label>Email<input required type="email" value={form.email} onChange={set("email")} /></label>
          <label>Temporary password<input required type="password" minLength={8} autoComplete="new-password" value={form.password} onChange={set("password")} /></label>
          <label>Role<select value={form.role} onChange={set("role")}><option value="PHARMACIST">Pharmacist</option><option value="ADMIN">Administrator</option></select></label>
        </div>
        <div className="spacer" />
        <button className="btn" disabled={busy}>Create account</button>
      </form>

      <div className="panel">
        <h2>Accounts</h2>
        {rows === null ? <p className="muted">Loading…</p> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Status</th><th>Created</th><th /></tr></thead>
              <tbody>
                {rows.map((u) => (
                  <tr key={u.id}>
                    <td>{u.name}<div className="muted small">{u.email}</div></td><td>{u.username}</td>
                    <td>{u.role === "ADMIN" ? "Administrator" : "Pharmacist"}</td>
                    <td>{!u.is_approved ? <Badge tone="amber">Pending approval</Badge> : u.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="red">Disabled</Badge>}</td>
                    <td>{dateTime(u.created_at)}</td>
                    <td>
                      <div className="row">
                        {!u.is_approved && <>
                          <button className="btn small" onClick={() => act(() => api.post(`/auth/approve-admin/${u.id}`), `${u.username} approved.`)}>Approve</button>
                          <button className="btn danger small" onClick={() => window.confirm(`Reject ${u.username}?`) && act(() => api.post(`/auth/reject-admin/${u.id}`), `${u.username} rejected.`)}>Reject</button>
                        </>}
                        {u.is_approved && u.id !== me.id && (
                          <button className="btn danger small" onClick={() => window.confirm(`Remove ${u.username}?`) && act(() => api.delete(`/auth/staff/${u.id}`), `${u.username} removed.`)}>Remove</button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
