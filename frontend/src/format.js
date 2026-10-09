// The API sends money as exact decimal strings. We only format for display; the UI never does money arithmetic.
const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" });
export const money = (v) => (v === null || v === undefined || v === "" ? "—" : inr.format(Number(v)));
export const dateOnly = (iso) => (iso ? new Date(iso + "T00:00:00").toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }) : "—");
export const dateTime = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");

export const daysUntil = (isoDate) => Math.round((new Date(isoDate + "T00:00:00") - new Date(new Date().toDateString())) / 86400000);
