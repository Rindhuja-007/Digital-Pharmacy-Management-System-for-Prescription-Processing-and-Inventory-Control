import { Fragment, useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import Receipt from "../components/Receipt";
import { Banner, Empty, PageHead } from "../components/ui";
import { dateTime, money } from "../format";

const PAGE = 25;

export default function Transactions() {
  const [rows, setRows] = useState(null);
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setRows(null);
    api.get("/transactions", { params: { limit: PAGE, offset } }).then((r) => setRows(r.data)).catch((e) => setError(errorMessage(e)));
  }, [offset]);

  return (
    <>
      <PageHead title="Transactions" subtitle="Dispensing history and receipts" />
      <Banner onClose={() => setError("")}>{error}</Banner>
      <div className="panel">
        {rows === null ? <p className="muted">Loading…</p> : rows.length === 0 ? <Empty>{offset ? "No more transactions." : "Nothing has been dispensed yet."}</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Receipt</th><th>Date</th><th>Prescription</th><th>Pharmacist</th><th className="right">Lines</th><th className="right">Total</th></tr></thead>
              <tbody>
                {rows.map((t) => (
                  <Fragment key={t.id}>
                    <tr className="clickable" onClick={() => setOpen(open === t.id ? null : t.id)}>
                      <td>#{t.id}</td><td>{dateTime(t.created_at)}</td><td>{t.prescription_number || "—"}</td>
                      <td>{t.pharmacist_username}</td><td className="right mono">{t.items.length}</td><td className="right mono">{money(t.total_amount)}</td>
                    </tr>
                    {open === t.id && <tr><td colSpan={6}><Receipt tx={t} /></td></tr>}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="row" style={{ marginTop: ".8rem" }}>
          <button className="btn secondary small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Newer</button>
          <button className="btn secondary small" disabled={!rows || rows.length < PAGE} onClick={() => setOffset(offset + PAGE)}>Older</button>
        </div>
      </div>
    </>
  );
}
