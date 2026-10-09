import { dateOnly, dateTime, money } from "../format";

export default function Receipt({ tx }) {
  return (
    <div className="receipt">
      <p className="muted small">
        Receipt #{tx.id} · {dateTime(tx.created_at)}<br />
        Prescription {tx.prescription_number || "—"}{tx.patient_reference ? ` · Patient ${tx.patient_reference}` : ""}<br />
        Dispensed by <strong>{tx.pharmacist_username}</strong>
      </p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Medicine</th><th>Batch (expiry)</th><th className="right">Qty</th><th className="right">Price</th><th className="right">Total</th></tr></thead>
          <tbody>
            {tx.items.map((i, n) => (
              <tr key={n}>
                <td>{i.medicine_name}</td>
                <td>{i.batch_number} <span className="muted">({dateOnly(i.expiry_date)})</span></td>
                <td className="right mono">{i.quantity}</td>
                <td className="right mono">{money(i.unit_price)}</td>
                <td className="right mono">{money(i.total_price)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="spacer" />
      <div className="totals mono">
        <div><span>Subtotal</span><span>{money(tx.subtotal)}</span></div>
        <div><span>Discount</span><span>− {money(tx.discount)}</span></div>
        <div><span>Tax</span><span>{money(tx.tax)}</span></div>
        <div className="grand"><span>Total</span><span>{money(tx.total_amount)}</span></div>
      </div>
    </div>
  );
}
