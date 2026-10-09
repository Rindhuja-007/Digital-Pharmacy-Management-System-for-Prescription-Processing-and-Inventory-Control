import { useEffect, useState } from "react";
import api, { errorMessage } from "../api";
import { Banner, PageHead } from "../components/ui";
import { money } from "../format";

export default function Dashboard() {
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { api.get("/reports/dashboard").then((r) => setD(r.data)).catch((e) => setError(errorMessage(e))); }, []);

  const cards = d && [
    { label: "Units in stock (usable)", value: d.total_units.toLocaleString(), tone: "" },
    { label: "Batches expiring within 90 days", value: d.expiring_soon_batches, tone: d.expiring_soon_batches ? "amber" : "" },
    { label: "Medicines out of stock", value: d.out_of_stock_count, tone: d.out_of_stock_count ? "red" : "" },
    { label: `Today's sales (${d.todays_transactions} ${d.todays_transactions === 1 ? "sale" : "sales"})`, value: money(d.todays_sales), tone: "" },
  ];
  return (
    <>
      <PageHead title="Dashboard" subtitle="Stock and sales at a glance" />
      <Banner onClose={() => setError("")}>{error}</Banner>
      <div className="kpis">
        {cards ? cards.map((c) => (
          <div key={c.label} className={`kpi ${c.tone}`}><div className="value mono">{c.value}</div><div className="label">{c.label}</div></div>
        )) : !error && <p className="muted">Loading…</p>}
      </div>
    </>
  );
}
