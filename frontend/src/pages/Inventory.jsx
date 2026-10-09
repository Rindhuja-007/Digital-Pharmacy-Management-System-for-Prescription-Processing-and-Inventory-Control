import { useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { Badge, Banner, Empty, PageHead } from "../components/ui";
import { dateOnly, daysUntil, money } from "../format";

const BLANK = { medicine_id: "", batch_number: "", quantity: "", expiry_date: "", purchase_price: "", selling_price: "", supplier_id: "" };

function expiryBadge(b) {
  if (b.is_expired) return <Badge tone="red">Expired</Badge>;
  const d = daysUntil(b.expiry_date);
  return d <= 90 ? <Badge tone="amber">{d} days left</Badge> : <Badge tone="green">OK</Badge>;
}

export default function Inventory() {
  const [view, setView] = useState("batches");
  const [batches, setBatches] = useState(null);
  const [summary, setSummary] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [form, setForm] = useState(BLANK);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => Promise.all([api.get("/inventory/batches"), api.get("/inventory"), api.get("/suppliers")])
    .then(([b, s, sup]) => { setBatches(b.data); setSummary(s.data); setSuppliers(sup.data); })
    .catch((e) => setError(errorMessage(e)));
  useEffect(() => { load(); }, []);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const add = async (e) => {
    e.preventDefault();
    setBusy(true); setError(""); setOk("");
    try {
      await api.post("/inventory/stock", {
        medicine_id: Number(form.medicine_id), batch_number: form.batch_number, quantity: Number(form.quantity),
        expiry_date: form.expiry_date, purchase_price: form.purchase_price || "0", selling_price: form.selling_price,
        supplier_id: form.supplier_id ? Number(form.supplier_id) : null,
      });
      setOk("Batch added."); setForm(BLANK); load();
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };

  return (
    <>
      <PageHead title="Inventory" subtitle="Batches are used earliest expiry first. Expired batches are never dispensed." />
      <Banner onClose={() => setError("")}>{error}</Banner>
      <Banner kind="ok" onClose={() => setOk("")}>{ok}</Banner>

      <form className="panel" onSubmit={add}>
        <h2>Add a batch</h2>
        <div className="grid">
          <label>Medicine *
            <select required value={form.medicine_id} onChange={set("medicine_id")}>
              <option value="">Select…</option>
              {summary.map((m) => <option key={m.medicine_id} value={m.medicine_id}>{m.medicine_name}{m.strength ? ` (${m.strength})` : ""}</option>)}
            </select>
          </label>
          <label>Batch number *<input required value={form.batch_number} onChange={set("batch_number")} /></label>
          <label>Quantity *<input required type="number" min="1" value={form.quantity} onChange={set("quantity")} /></label>
          <label>Expiry date *<input required type="date" value={form.expiry_date} onChange={set("expiry_date")} /></label>
          <label>Purchase price (₹)<input inputMode="decimal" value={form.purchase_price} onChange={set("purchase_price")} /></label>
          <label>Selling price (₹) *<input required inputMode="decimal" value={form.selling_price} onChange={set("selling_price")} /></label>
          <label>Supplier
            <select value={form.supplier_id} onChange={set("supplier_id")}>
              <option value="">None</option>
              {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
        </div>
        <div className="spacer" />
        <button className="btn" disabled={busy}>{busy ? "Saving…" : "Add batch"}</button>
      </form>

      <div className="panel">
        <div className="tabs">
          <button className={view === "batches" ? "on" : ""} onClick={() => setView("batches")}>Batches</button>
          <button className={view === "summary" ? "on" : ""} onClick={() => setView("summary")}>By medicine</button>
        </div>
        {batches === null ? <p className="muted">Loading…</p> : view === "batches" ? (
          batches.length === 0 ? <Empty>No batches yet. Add stock above.</Empty> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Medicine</th><th>Batch</th><th className="right">Qty</th><th>Expiry</th><th>Status</th><th className="right">Purchase</th><th className="right">Selling</th><th>Received</th></tr></thead>
                <tbody>
                  {batches.map((b) => (
                    <tr key={b.id} className={b.is_expired ? "expired" : ""}>
                      <td>{b.medicine_name}</td><td>{b.batch_number}</td><td className="right mono">{b.quantity}</td>
                      <td>{dateOnly(b.expiry_date)}</td><td>{b.quantity === 0 ? <Badge tone="amber">Empty</Badge> : expiryBadge(b)}</td>
                      <td className="right mono">{money(b.purchase_price)}</td><td className="right mono">{money(b.selling_price)}</td><td>{dateOnly(b.received_date)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Medicine</th><th>Location</th><th className="right">Usable</th><th className="right">Total on hand</th><th className="right">Reorder at</th><th>Stock</th></tr></thead>
              <tbody>
                {summary.map((m) => (
                  <tr key={m.medicine_id}>
                    <td>{m.medicine_name}{m.strength ? ` (${m.strength})` : ""}</td>
                    <td>{[m.rack_location, m.shelf_number && `shelf ${m.shelf_number}`].filter(Boolean).join(", ") || "—"}</td>
                    <td className="right mono">{m.usable_units}</td><td className="right mono">{m.total_units}</td><td className="right mono">{m.reorder_level}</td>
                    <td>{m.out_of_stock ? <Badge tone="red">Out of stock</Badge> : m.low_stock ? <Badge tone="amber">Low</Badge> : <Badge tone="green">OK</Badge>}</td>
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
