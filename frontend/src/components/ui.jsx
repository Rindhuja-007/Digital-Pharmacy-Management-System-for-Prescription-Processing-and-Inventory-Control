import { useEffect } from "react";

export function Badge({ tone = "amber", children }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

const STATUS_TONE = { UPLOADED: "amber", PROCESSED: "amber", PENDING: "amber", VERIFIED: "green", DISPENSED: "green", REJECTED: "red" };
export const StatusBadge = ({ status }) => <Badge tone={STATUS_TONE[status] || "amber"}>{status}</Badge>;

export const SEVERITY_TONE = { INFO: "green", WARNING: "amber", CRITICAL: "red" };
export const LEVEL_TONE = { HIGH: "green", MEDIUM: "amber", LOW: "red" };

export function Banner({ kind = "error", children, onClose }) {
  if (!children) return null;
  return (
    <div className={`banner ${kind}`} role={kind === "error" ? "alert" : "status"}>
      <div>{children}</div>
      {onClose && <button onClick={onClose} aria-label="Dismiss">×</button>}
    </div>
  );
}

export function Modal({ title, children, onClose }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose?.();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export const Empty = ({ children }) => <div className="empty">{children}</div>;

export function PageHead({ title, subtitle, children }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      <div className="row">{children}</div>
    </div>
  );
}
