import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api, { errorMessage } from "../api";
import { Banner, Empty, PageHead, StatusBadge } from "../components/ui";
import { dateTime } from "../format";

export default function Prescriptions() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [patient, setPatient] = useState("");
  const [doctor, setDoctor] = useState("");
  const [file, setFile] = useState(null);
  const fileRef = useRef();

  const load = () => api.get("/prescriptions").then((r) => setRows(r.data)).catch((e) => setError(errorMessage(e)));
  useEffect(() => { load(); }, []);

  const upload = async (e) => {
    e.preventDefault();
    if (!file) { setError("Choose a JPG or PNG photo of the prescription."); return; }
    setBusy(true); setError("");
    const fd = new FormData();
    fd.append("file", file);
    fd.append("patient_reference", patient);
    fd.append("doctor_name", doctor);
    try {
      const { data } = await api.post("/prescriptions/upload", fd);
      navigate(`/prescriptions/${data.id}`);
    } catch (err) { setError(errorMessage(err)); } finally { setBusy(false); }
  };

  return (
    <>
      <PageHead title="Prescriptions" subtitle="Upload a photo, review what was read, then verify and dispense" />
      <Banner onClose={() => setError("")}>{error}</Banner>

      <form className="panel" onSubmit={upload}>
        <h2>Upload a prescription</h2>
        <div className="grid">
          <label>Photo (JPG or PNG, up to 10 MB)
            <input ref={fileRef} type="file" accept="image/jpeg,image/png" onChange={(e) => setFile(e.target.files[0] || null)} />
          </label>
          <label>Patient reference<input value={patient} onChange={(e) => setPatient(e.target.value)} placeholder="Name or ID" /></label>
          <label>Doctor<input value={doctor} onChange={(e) => setDoctor(e.target.value)} /></label>
        </div>
        <div className="spacer" />
        <button className="btn" disabled={busy}>{busy ? "Uploading…" : "Upload and open review desk"}</button>
        <span className="muted small"> Uploading never approves anything or changes stock.</span>
      </form>

      <div className="panel">
        <h2>All prescriptions</h2>
        {rows === null ? <p className="muted">Loading…</p> : rows.length === 0 ? <Empty>No prescriptions yet. Upload the first one above.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Number</th><th>Patient</th><th>Doctor</th><th>Status</th><th>OCR confidence</th><th>Lines</th><th>Uploaded</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => navigate(`/prescriptions/${r.id}`)}>
                    <td><a href={`/prescriptions/${r.id}`} onClick={(e) => e.preventDefault()}>{r.prescription_number}</a></td>
                    <td>{r.patient_reference || "—"}</td><td>{r.doctor_name || "—"}</td>
                    <td><StatusBadge status={r.status} /></td>
                    <td className="mono">{r.confidence_score != null ? `${r.confidence_score.toFixed(1)}%` : "—"}</td>
                    <td className="mono">{r.item_count}</td><td>{dateTime(r.created_at)}</td>
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
