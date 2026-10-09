import { useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import { Banner } from "../components/ui";

export default function Login() {
  const { login, notice } = useAuth();
  const [mode, setMode] = useState("login"); // login | register
  const [status, setStatus] = useState(null);
  const [form, setForm] = useState({ name: "", username: "", email: "", password: "", approval_code: "" });
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  const loadStatus = () => api.get("/auth/status").then((r) => {
    setStatus(r.data);
    if (r.data.setup_required) setMode("register");
  }).catch((e) => setError(errorMessage(e)));
  useEffect(() => { loadStatus(); }, []);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(""); setInfo("");
    try {
      if (mode === "login") {
        await login(form.username, form.password);
      } else {
        const body = { ...form, approval_code: form.approval_code || null };
        const r = await api.post("/auth/register-admin", body);
        if (r.status === 202) {
          setInfo(r.data.message);
          setMode("login");
        } else {
          await login(form.username, form.password); // first admin is approved: sign straight in
        }
      }
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };

  const seed = async () => {
    setBusy(true); setError("");
    try {
      await api.post("/auth/seed-demo");
      setInfo("Demo data loaded. Sign in as admin / Admin@123 or pharmacist / Pharmacist@123.");
      setMode("login");
      await loadStatus();
      setMode("login");
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };

  return (
    <div className="login">
      <section className="login-art">
        <div className="brand">PharmaCare</div>
        <h1>A pharmacist confirms every line.</h1>
        <p>Upload a prescription, review what the software read, and dispense from the batch that expires first.
          The system suggests; you decide.</p>
      </section>
      <section className="login-form">
        <div className="login-card">
          <h2>{mode === "login" ? "Sign in" : status?.setup_required ? "Create the first administrator" : "Request admin access"}</h2>
          {status?.setup_required && <p className="muted">No accounts exist yet. The first administrator is approved automatically.</p>}
          <Banner kind="warn">{notice}</Banner>
          <Banner kind="error" onClose={() => setError("")}>{error}</Banner>
          <Banner kind="ok" onClose={() => setInfo("")}>{info}</Banner>
          <form onSubmit={submit}>
            {mode === "register" && (
              <>
                <label>Full name<input required value={form.name} onChange={set("name")} /></label>
                <label>Email<input required type="email" value={form.email} onChange={set("email")} /></label>
              </>
            )}
            <label>Username<input required autoComplete="username" value={form.username} onChange={set("username")} /></label>
            <label>Password<input required type="password" minLength={mode === "register" ? 8 : undefined}
              autoComplete={mode === "login" ? "current-password" : "new-password"} value={form.password} onChange={set("password")} /></label>
            {mode === "register" && !status?.setup_required && (
              <label>Approval code (optional)<input value={form.approval_code} onChange={set("approval_code")} /></label>
            )}
            <button className="btn big" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}</button>
          </form>
          <div className="spacer" />
          {!status?.setup_required && (
            <button className="btn secondary small" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
              {mode === "login" ? "Request admin access" : "Back to sign in"}
            </button>
          )}
          {status?.setup_required && (
            <button className="btn secondary small" onClick={seed} disabled={busy}>Load demo data instead</button>
          )}
        </div>
      </section>
    </div>
  );
}
