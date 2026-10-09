import { useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { useAuth } from "../auth";
import { Badge, Banner, Empty, PageHead } from "../components/ui";
import { money } from "../format";

const BLANK = { medicine_name: "", generic_name: "", composition: "", brand_name: "", strength: "", dosage_form: "", category: "",
  manufacturer: "", barcode: "", rack_location: "", shelf_number: "", hsn_code: "", reorder_level: "15", mrp: "", prescription_required: false };

export default function Medicines() {
  const { isAdmin } = useAuth();
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(BLANK);
  const [csv, setCsv] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = (query = q) => api.get("/medicines", { params: { q: query || undefined, limit: 500 } })
    .then((r) => setRows(r.data)).catch((e) => setError(errorMessage(e)));
  useEffect(() => { const t = setTimeout(() => load(q), 250); return () => clearTimeout(t); }, [q]);  // debounced search

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const add = async (e) => {
    e.preventDefault();
    setBusy(true); setError(""); setOk("");
    const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === "" ? null : v]));
    body.reorder_level = Number(form.reorder_level || 15);
    try {
      await api.post("/medicines", body);
      setOk(`Added ${form.medicine_name}. It shows as out of stock until you add a batch in Inventory.`);
      setForm(BLANK); setShowForm(false); load();
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };

  const importCsv = async (e) => {
    e.preventDefault();
    if (!csv) { setError("Choose a CSV file first."); return; }
    setBusy(true); setError(""); setResult(null);
    const fd = new FormData(); fd.append("file", csv);
    try { const { data } = await api.post("/medicines/import-csv", fd); setResult(data); load(); }
    catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };

  const downloadSample = async () => {
    try {
      const { data } = await api.get("/medicines/sample-csv", { responseType: "blob" });
      const url = URL.createObjectURL(data);
      const a = document.createElement("a"); a.href = url; a.download = "medicines-sample.csv"; a.click();
      URL.revokeObjectURL(url);
    } catch (err) { setError(errorMessage(err)); }
  };

  const remove = async (m) => {
    if (!window.confirm(`Delete ${m.medicine_name}? This cannot be undone.`)) return;
    setError(""); setOk("");
    try { await api.delete(`/medicines/${m.id}`); setOk(`Deleted ${m.medicine_name}.`); load(); } catch (err) { setError(errorMessage(err)); }
  };

  return (
    <>
      <PageHead title="Medicines" subtitle="The catalogue prescriptions are matched against">
        <button className="btn" onClick={() => setShowForm(!showForm)}>{showForm ? "Close form" : "Add medicine"}</button>
      </PageHead>
      <Banner onClose={() => setError("")}>{error}</Banner>
      <Banner kind="ok" onClose={() => setOk("")}>{ok}</Banner>

      {showForm && (
        <form className="panel" onSubmit={add}>
          <h2>New medicine</h2>
          <div className="grid">
            <label>Medicine name *<input required value={form.medicine_name} onChange={set("medicine_name")} /></label>
            <label>Generic name<input value={form.generic_name} onChange={set("generic_name")} /></label>
            <label>Composition<input value={form.composition} onChange={set("composition")} placeholder="Paracetamol 500 mg" /></label>
            <label>Brand<input value={form.brand_name} onChange={set("brand_name")} /></label>
            <label>Strength<input value={form.strength} onChange={set("strength")} placeholder="500 mg" /></label>
            <label>Dosage form<input value={form.dosage_form} onChange={set("dosage_form")} placeholder="Tablet" /></label>
            <label>Category<input value={form.category} onChange={set("category")} /></label>
            <label>Manufacturer<input value={form.manufacturer} onChange={set("manufacturer")} /></label>
            <label>Barcode<input value={form.barcode} onChange={set("barcode")} /></label>
            <label>Rack<input value={form.rack_location} onChange={set("rack_location")} /></label>
            <label>Shelf<input value={form.shelf_number} onChange={set("shelf_number")} /></label>
            <label>HSN code<input value={form.hsn_code} onChange={set("hsn_code")} /></label>
            <label>Reorder level<input type="number" min="0" value={form.reorder_level} onChange={set("reorder_level")} /></label>
            <label>MRP (₹)<input inputMode="decimal" value={form.mrp} onChange={set("mrp")} /></label>
          </div>
          <div className="spacer" />
          <label className="check"><input type="checkbox" checked={form.prescription_required} onChange={set("prescription_required")} />Prescription required</label>
          <div className="spacer" />
          <button className="btn" disabled={busy}>{busy ? "Saving…" : "Save medicine"}</button>
        </form>
      )}

      <form className="panel" onSubmit={importCsv}>
        <h2>Import from CSV</h2>
        <p className="muted small">Creates medicines, sets rack locations, and appends stock batches. Existing medicines are only updated with rack and shelf.</p>
        <div className="row">
          <input style={{ maxWidth: 340 }} type="file" accept=".csv,text/csv" onChange={(e) => setCsv(e.target.files[0] || null)} />
          <button className="btn" disabled={busy}>Import</button>
          <button type="button" className="btn secondary" onClick={downloadSample}>Download sample CSV</button>
        </div>
        {result && (
          <div style={{ marginTop: ".8rem" }}>
            <Banner kind={result.errors.length ? "warn" : "ok"}>
              {result.created_medicines} created, {result.updated_medicines} updated, {result.batches_added} batches added, {result.skipped_batches} duplicate batches skipped.
              {result.errors.length > 0 && <ul style={{ margin: ".3rem 0 0", paddingLeft: "1.1rem" }}>{result.errors.map((e, i) => <li key={i}>Row {e.row}: {e.message}</li>)}</ul>}
            </Banner>
          </div>
        )}
      </form>

      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between", marginBottom: ".6rem" }}>
          <h2 style={{ margin: 0 }}>Catalogue</h2>
          <input style={{ maxWidth: 300 }} type="search" placeholder="Search name, brand, generic, barcode" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search medicines" />
        </div>
        {rows === null ? <p className="muted">Loading…</p> : rows.length === 0 ? <Empty>No medicines found.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Generic</th><th>Strength</th><th>Form</th><th>Location</th><th className="right">Reorder</th><th className="right">MRP</th><th>Rx</th>{isAdmin && <th />}</tr></thead>
              <tbody>
                {rows.map((m) => (
                  <tr key={m.id}>
                    <td><strong>{m.medicine_name}</strong>{m.brand_name && <div className="muted small">{m.brand_name}</div>}</td>
                    <td>{m.generic_name || "—"}</td><td>{m.strength || "—"}</td><td>{m.dosage_form || "—"}</td>
                    <td>{[m.rack_location, m.shelf_number && `shelf ${m.shelf_number}`].filter(Boolean).join(", ") || "—"}</td>
                    <td className="right mono">{m.reorder_level}</td><td className="right mono">{money(m.mrp)}</td>
                    <td>{m.prescription_required ? <Badge tone="amber">Rx</Badge> : "—"}</td>
                    {isAdmin && <td><button className="btn danger small" onClick={() => remove(m)}>Delete</button></td>}
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
