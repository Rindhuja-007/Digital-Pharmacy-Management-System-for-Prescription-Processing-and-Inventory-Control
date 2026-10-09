import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api, { errorMessage } from "../api";
import Receipt from "../components/Receipt";
import { Badge, Banner, LEVEL_TONE, Modal, PageHead, StatusBadge } from "../components/ui";
import { dateOnly } from "../format";

/** Fetch a protected image as a blob (an <img> tag cannot send the Bearer token). */
function useScan(id, kind, enabled, version) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    if (!enabled) { setUrl(null); return; }
    let objectUrl, cancelled = false;
    api.get(`/prescriptions/${id}/image`, { params: { kind }, responseType: "blob" })
      .then((r) => { if (!cancelled) { objectUrl = URL.createObjectURL(r.data); setUrl(objectUrl); } })
      .catch(() => !cancelled && setUrl(null));
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [id, kind, enabled, version]);
  return url;
}

const EDITABLE = ["UPLOADED", "PROCESSED"];

export default function PrescriptionDesk() {
  const { id } = useParams();
  const [rx, setRx] = useState(null);
  const [catalogue, setCatalogue] = useState([]);
  const [matches, setMatches] = useState({});
  const [skipped, setSkipped] = useState([]);
  const [rows, setRows] = useState({});
  const [rowErrors, setRowErrors] = useState({});
  const [availability, setAvailability] = useState(null);
  const [tab, setTab] = useState("original");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const [discount, setDiscount] = useState("0");
  const [tax, setTax] = useState("0");
  const [confirming, setConfirming] = useState(false);
  const [checked, setChecked] = useState(false);
  const [receipt, setReceipt] = useState(null);
  const [newLine, setNewLine] = useState({ name: "", quantity: "1" });
  const [scanVersion, setScanVersion] = useState(0);

  const original = useScan(id, "original", true, 0);
  const processed = useScan(id, "processed", !!rx?.has_processed_image, scanVersion);

  const load = useCallback(async () => {
    const { data } = await api.get(`/prescriptions/${id}`);
    setRx(data);
    return data;
  }, [id]);

  useEffect(() => {
    load().catch((e) => setError(errorMessage(e)));
    api.get("/inventory").then((r) => setCatalogue(r.data)).catch(() => {});
  }, [load]);

  // Keep the editable rows in step with the server's items without losing what the pharmacist has typed.
  useEffect(() => {
    if (!rx) return;
    setRows((prev) => {
      const next = {};
      for (const it of rx.items) {
        next[it.id] = prev[it.id] || {
          decision: it.verification_status === "PENDING" ? null : it.verification_status,
          medicine_id: it.medicine_id ?? "",
          quantity: it.quantity ?? "",
          dosage: it.dosage ?? "", frequency: it.frequency ?? "", duration: it.duration ?? "",
        };
      }
      return next;
    });
  }, [rx]);

  const stockById = useMemo(() => Object.fromEntries(catalogue.map((m) => [m.medicine_id, m.usable_units])), [catalogue]);
  const nameById = useMemo(() => Object.fromEntries(catalogue.map((m) => [m.medicine_id, m.medicine_name])), [catalogue]);

  const run = async (key, fn, success) => {
    setBusy(key); setError(""); setOk("");
    try { await fn(); if (success) setOk(success); } catch (err) { setError(errorMessage(err)); } finally { setBusy(""); }
  };

  const doPreprocess = () => run("pre", async () => {
    const { data } = await api.post(`/prescriptions/${id}/preprocess`); setRx(data); setScanVersion((v) => v + 1); setTab("processed");
  }, "Image cleaned up. Run OCR next.");
  const doOcr = () => run("ocr", async () => { const { data } = await api.post(`/prescriptions/${id}/process`); setRx(data); }, "Text read. Extract the medicine lines next.");
  const doExtract = () => run("ext", async () => {
    const { data } = await api.post(`/prescriptions/${id}/extract`);
    setRx(data.prescription); setSkipped(data.skipped_lines); setRows({}); setMatches({}); setAvailability(null);
  }, "Medicine lines extracted. Run Match to see catalogue suggestions.");
  const doMatch = () => run("match", async () => {
    const { data } = await api.post(`/prescriptions/${id}/match`);
    setMatches(Object.fromEntries(data.matches.map((m) => [m.item_id, m])));
    const fresh = await load();
    // Pre-select the top suggestion only where nothing is chosen yet. The pharmacist still has to decide.
    setRows((prev) => {
      const next = { ...prev };
      for (const it of fresh.items) if (next[it.id] && next[it.id].medicine_id === "" && it.medicine_id) next[it.id] = { ...next[it.id], medicine_id: it.medicine_id };
      return next;
    });
  }, "Suggestions ready. Review each line, then save your verification.");

  const setRow = (itemId, patch) => { setRows((r) => ({ ...r, [itemId]: { ...r[itemId], ...patch } })); setRowErrors((e) => ({ ...e, [itemId]: undefined })); };

  const addLine = (e) => {
    e.preventDefault();
    run("add", async () => {
      await api.post(`/prescriptions/${id}/items`, { extracted_medicine_name: newLine.name, quantity: Number(newLine.quantity) || 1 });
      setNewLine({ name: "", quantity: "1" });
      await load();
    }, "Line added.");
  };

  const saveVerification = () => {
    const errs = {};
    const decisions = rx.items.map((it) => {
      const r = rows[it.id] || {};
      if (!r.decision) errs[it.id] = "Choose Verified or Rejected for this line.";
      else if (r.decision === "VERIFIED") {
        if (!r.medicine_id) errs[it.id] = "Pick the catalogue medicine to dispense.";
        else if (!(Number(r.quantity) > 0)) errs[it.id] = "Quantity must be greater than 0.";
      }
      return {
        item_id: it.id, decision: r.decision || "REJECTED",
        medicine_id: r.decision === "VERIFIED" ? Number(r.medicine_id) : null,
        quantity: r.decision === "VERIFIED" ? Number(r.quantity) : null,
        dosage: r.dosage, frequency: r.frequency, duration: r.duration,
      };
    });
    setRowErrors(errs);
    if (Object.keys(errs).length) { setError("Every line needs a decision before saving. See the highlighted lines."); return; }
    run("verify", async () => {
      const { data } = await api.put(`/prescriptions/${id}/verify`, { decisions });
      setRx(data); setAvailability(null);
      const v = data.items.filter((i) => i.verification_status === "VERIFIED").length;
      setOk(`Verification saved: ${v} verified, ${data.items.length - v} rejected. Prescription is ${data.status}.`);
    });
  };

  const checkAvailability = () => run("avail", async () => { const { data } = await api.post(`/prescriptions/${id}/availability`); setAvailability(data); });

  const validMoney = (s) => /^\d+(\.\d{1,2})?$/.test(s.trim());
  const dispense = () => run("disp", async () => {
    const { data } = await api.post("/transactions", { prescription_id: Number(id), confirmed_dispensing: true, discount: discount.trim() || "0", tax: tax.trim() || "0" });
    setConfirming(false); setChecked(false); setReceipt(data); await load(); setAvailability(null);
  });
  const openConfirm = () => {
    if (!validMoney(discount || "0") || !validMoney(tax || "0")) { setError("Discount and tax must be amounts like 10 or 10.50."); return; }
    setError(""); setChecked(false); setConfirming(true);
  };
  const viewReceipt = () => run("rcpt", async () => {
    const { data } = await api.get("/transactions", { params: { limit: 200 } });
    const tx = data.find((t) => t.prescription_id === Number(id));
    if (!tx) throw { response: { status: 404, data: { detail: "Receipt not found in recent transactions" } } };
    setReceipt(tx);
  });

  if (!rx) return <>{error ? <Banner>{error}</Banner> : <p className="muted">Loading…</p>}</>;

  const editable = EDITABLE.includes(rx.status);
  const locked = rx.status === "DISPENSED";
  const verifiedLines = rx.items.filter((i) => i.verification_status === "VERIFIED");

  return (
    <>
      <PageHead title={`Prescription ${rx.prescription_number}`} subtitle={`${rx.patient_reference || "No patient reference"} · ${rx.doctor_name || "Doctor not recorded"}`}>
        <StatusBadge status={rx.status} />
        <Link className="btn secondary small" to="/prescriptions">Back to list</Link>
      </PageHead>
      <Banner onClose={() => setError("")}>{error}</Banner>
      <Banner kind="ok" onClose={() => setOk("")}>{ok}</Banner>

      <div className="desk">
        {/* ---------- left: the scan and what OCR read ---------- */}
        <div>
          <div className="panel">
            <div className="tabs" role="tablist">
              <button role="tab" className={tab === "original" ? "on" : ""} onClick={() => setTab("original")}>Original</button>
              <button role="tab" className={tab === "processed" ? "on" : ""} disabled={!rx.has_processed_image} onClick={() => setTab("processed")}>Processed</button>
            </div>
            <div className="scan">
              {(tab === "original" ? original : processed)
                ? <img src={tab === "original" ? original : processed} alt={`${tab} prescription scan`} />
                : <span className="muted">{tab === "processed" ? "Run Preprocess to see the cleaned image." : "Loading image…"}</span>}
            </div>
          </div>
          <div className="panel">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h3 style={{ margin: 0 }}>Text read by OCR</h3>
              {rx.confidence_score != null && <Badge tone={rx.confidence_score >= 85 ? "green" : rx.confidence_score >= 65 ? "amber" : "red"}>{rx.confidence_score.toFixed(1)}% confidence</Badge>}
            </div>
            {rx.extracted_text == null ? <p className="muted small">Nothing read yet.</p> : <pre className="ocr-text">{rx.extracted_text || "(no text found)"}</pre>}
            {skipped.length > 0 && (
              <Banner kind="warn">Skipped {skipped.length} line(s) that looked like non-medicine text. If one is a real medicine, add it below:
                <ul style={{ margin: ".3rem 0 0", paddingLeft: "1.1rem" }}>{skipped.map((s, i) => <li key={i}>{s.line}</li>)}</ul></Banner>
            )}
          </div>
        </div>

        {/* ---------- right: stages, lines, verification, dispensing ---------- */}
        <div>
          <div className="panel">
            <h3>Reading stages</h3>
            <div className="stages">
              <button className="btn secondary" disabled={!editable || !!busy} onClick={doPreprocess}>{busy === "pre" ? "Working…" : "Preprocess"}</button>
              <button className="btn secondary" disabled={!editable || !!busy} onClick={doOcr}>{busy === "ocr" ? "Reading… (first run is slow)" : "Run OCR"}</button>
              <button className="btn secondary" disabled={!editable || rx.extracted_text == null || !!busy} onClick={doExtract}>{busy === "ext" ? "Working…" : "Extract"}</button>
              <button className="btn secondary" disabled={locked || rx.items.length === 0 || !!busy} onClick={doMatch}>{busy === "match" ? "Working…" : "Match"}</button>
            </div>
            <p className="muted small" style={{ marginTop: ".6rem" }}>These steps only suggest. Nothing is approved and no stock moves until you verify and dispense.</p>
          </div>

          <div className="panel">
            <h3>Medicine lines</h3>
            {rx.items.length === 0 && <p className="muted">No lines yet. Run OCR and Extract, or add a line below.</p>}
            {rx.items.map((it) => (
              <ItemCard key={it.id} item={it} row={rows[it.id]} match={matches[it.id]} catalogue={catalogue} stockById={stockById}
                error={rowErrors[it.id]} disabled={locked} onChange={(p) => setRow(it.id, p)} />
            ))}
            {!locked && (
              <form className="row" onSubmit={addLine} style={{ marginTop: ".5rem", alignItems: "flex-end" }}>
                <label style={{ flex: "2 1 180px" }}>Add a line OCR missed<input required value={newLine.name} onChange={(e) => setNewLine({ ...newLine, name: e.target.value })} placeholder="e.g. Dolo 500" /></label>
                <label style={{ flex: "0 1 90px" }}>Quantity<input type="number" min="1" value={newLine.quantity} onChange={(e) => setNewLine({ ...newLine, quantity: e.target.value })} /></label>
                <button className="btn secondary" disabled={!editable || !!busy} title={!editable ? "Lines can only be added before verification" : ""}>Add line</button>
              </form>
            )}
            {!locked && rx.items.length > 0 && (
              <div className="row end" style={{ marginTop: "1rem" }}>
                <button className="btn" disabled={!!busy} onClick={saveVerification}>{busy === "verify" ? "Saving…" : "Save verification"}</button>
              </div>
            )}
          </div>

          {(rx.status === "VERIFIED" || locked) && (
            <div className="panel">
              <h3>Dispensing</h3>
              {rx.status === "VERIFIED" && (
                <>
                  <button className="btn secondary" disabled={!!busy} onClick={checkAvailability}>{busy === "avail" ? "Checking…" : "Check availability"}</button>
                  {availability && <Availability data={availability} />}
                  <div className="spacer" />
                  <div className="grid" style={{ maxWidth: 420 }}>
                    <label>Discount (₹)<input inputMode="decimal" value={discount} onChange={(e) => setDiscount(e.target.value)} /></label>
                    <label>Tax (₹)<input inputMode="decimal" value={tax} onChange={(e) => setTax(e.target.value)} /></label>
                  </div>
                  <div className="spacer" />
                  <button className="btn big" disabled={!!busy || verifiedLines.length === 0} onClick={openConfirm}>Confirm &amp; dispense</button>
                </>
              )}
              {locked && (<><p>This prescription has been dispensed and is now read-only.</p><button className="btn secondary" onClick={viewReceipt} disabled={!!busy}>View receipt</button></>)}
            </div>
          )}
        </div>
      </div>

      {confirming && (
        <Modal title="Dispense this prescription?" onClose={() => setConfirming(false)}>
          <p>Stock will be deducted from the batches that expire first. This cannot be undone.</p>
          <ul>{verifiedLines.map((l) => <li key={l.id}><strong>{l.quantity} ×</strong> {l.matched_medicine_name || nameById[l.medicine_id] || l.extracted_medicine_name}</li>)}</ul>
          <label className="check"><input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
            I have checked these medicines against the prescription.</label>
          <div className="spacer" />
          <div className="row end">
            <button className="btn secondary" onClick={() => setConfirming(false)}>Cancel</button>
            <button className="btn" disabled={!checked || busy === "disp"} onClick={dispense}>{busy === "disp" ? "Dispensing…" : "Dispense now"}</button>
          </div>
        </Modal>
      )}
      {receipt && (
        <Modal title="Receipt" onClose={() => setReceipt(null)}>
          <Receipt tx={receipt} />
          <div className="spacer" />
          <div className="row end no-print">
            <button className="btn secondary" onClick={() => window.print()}>Print</button>
            <button className="btn" onClick={() => setReceipt(null)}>Close</button>
          </div>
        </Modal>
      )}
    </>
  );
}

function ItemCard({ item, row, match, catalogue, stockById, error, disabled, onChange }) {
  if (!row) return null;
  const cands = match?.candidates || [];
  const subs = match?.substitutes || [];
  const top = cands[0];
  const inGroups = new Set([...cands.map((c) => c.medicine_id), ...subs.map((s) => s.medicine_id)]);
  const others = catalogue.filter((m) => !inGroups.has(m.medicine_id));
  const chosen = row.medicine_id ? Number(row.medicine_id) : null;
  const chosenStock = chosen != null ? stockById[chosen] : undefined;
  const qty = Number(row.quantity) || 0;
  const label = (name, strength, stock, extra = "") => `${name}${strength ? ` (${strength})` : ""} — ${stock ?? "?"} in stock${extra}`;
  const inStockSubs = subs.filter((s) => s.usable_stock > 0).slice(0, 3);
  const topShort = top && top.usable_stock < Math.max(qty, 1);

  return (
    <div className={`item ${row.decision || ""}`}>
      <div className="item-head">
        <div>
          <div className="name">{item.extracted_medicine_name}</div>
          <div className="row">
            {top ? <Badge tone={LEVEL_TONE[top.level]}>{top.level} match · {top.score}%</Badge>
              : item.matched_medicine_name ? <Badge tone="amber">Suggested: {item.matched_medicine_name}</Badge> : <Badge tone="amber">Not matched yet</Badge>}
            {top?.strength_mismatch && <Badge tone="red">Strength differs</Badge>}
          </div>
        </div>
        <div className="seg" role="group" aria-label="Decision">
          <button type="button" className={`v ${row.decision === "VERIFIED" ? "on" : ""}`} disabled={disabled} onClick={() => onChange({ decision: "VERIFIED" })}>Verified</button>
          <button type="button" className={`r ${row.decision === "REJECTED" ? "on" : ""}`} disabled={disabled} onClick={() => onChange({ decision: "REJECTED" })}>Rejected</button>
        </div>
      </div>

      <label>Catalogue medicine
        <select value={row.medicine_id} disabled={disabled} onChange={(e) => onChange({ medicine_id: e.target.value })}>
          <option value="">Select a medicine…</option>
          {cands.length > 0 && <optgroup label="Suggested matches">
            {cands.map((c) => <option key={c.medicine_id} value={c.medicine_id}>{label(c.medicine_name, c.strength, c.usable_stock, ` · ${c.score}%`)}</option>)}
          </optgroup>}
          {subs.length > 0 && <optgroup label="Same-ingredient substitutes">
            {subs.map((s) => <option key={s.medicine_id} value={s.medicine_id}>{label(s.medicine_name, s.strength, s.usable_stock, s.strength_differs ? " · different strength" : "")}</option>)}
          </optgroup>}
          <optgroup label="All medicines">
            {others.map((m) => <option key={m.medicine_id} value={m.medicine_id}>{label(m.medicine_name, m.strength, m.usable_units)}</option>)}
          </optgroup>
        </select>
      </label>

      {!disabled && topShort && inStockSubs.length > 0 && (
        <p className="sub-hint">{top.medicine_name} has {top.usable_stock} in stock. In-stock alternatives with the same ingredient:
          {inStockSubs.map((s) => <button type="button" key={s.medicine_id} onClick={() => onChange({ medicine_id: s.medicine_id })}>{s.medicine_name} ({s.usable_stock})</button>)}
          Check the strength before choosing a substitute.</p>
      )}
      {chosenStock !== undefined && qty > chosenStock && row.decision === "VERIFIED" && (
        <p className="field-err" style={{ color: "var(--amber-ink)" }}>Only {chosenStock} usable units in stock; you need {qty}.</p>
      )}

      <div className="grid" style={{ marginTop: ".7rem" }}>
        <label>Quantity<input type="number" min="1" disabled={disabled} value={row.quantity} onChange={(e) => onChange({ quantity: e.target.value })} /></label>
        <label>Dosage<input disabled={disabled} value={row.dosage} onChange={(e) => onChange({ dosage: e.target.value })} /></label>
        <label>Frequency<input disabled={disabled} value={row.frequency} onChange={(e) => onChange({ frequency: e.target.value })} /></label>
        <label>Duration<input disabled={disabled} value={row.duration} onChange={(e) => onChange({ duration: e.target.value })} /></label>
      </div>
      {error && <div className="field-err" role="alert">{error}</div>}
    </div>
  );
}

function Availability({ data }) {
  if (data.items.length === 0) return <p className="muted">No verified lines to check.</p>;
  return (
    <div style={{ marginTop: ".8rem" }}>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Medicine</th><th className="right">Needed</th><th className="right">Available</th><th className="right">Shortage</th></tr></thead>
          <tbody>
            {data.items.map((i) => (
              <tr key={i.item_id}>
                <td>{i.medicine_name}
                  {i.batches.length > 0 && <ul className="batches">{i.batches.map((b) => <li key={b.batch_id}>Batch {b.batch_number}: {b.quantity} units, expires {dateOnly(b.expiry_date)} (used first → last)</li>)}</ul>}
                </td>
                <td className="right mono">{i.needed}</td><td className="right mono">{i.available}</td>
                <td className="right">{i.shortage > 0 ? <Badge tone="red">Short by {i.shortage}</Badge> : <Badge tone="green">OK</Badge>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Banner kind={data.can_dispense ? "ok" : "warn"}>{data.can_dispense ? "All verified lines can be filled from usable stock." : "Some lines are short. Change the medicine or quantity, or restock, before dispensing."}</Banner>
    </div>
  );
}
