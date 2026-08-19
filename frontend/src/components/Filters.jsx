// Filter chips that narrow the visible application cards.
import React from "react";

const OPTIONS = [
  { key: "all", label: "All" },
  { key: "active", label: "Active" },
  { key: "local", label: "Local" },
  { key: "strong", label: "Strong fit" },
];

// Controlled chip row: parent owns the active value and the change handler.
export default function Filters({ value, onChange }) {
  return (
    <div className="filters">
      {OPTIONS.map((o) => (
        <span
          key={o.key}
          className={`chip ${value === o.key ? "on" : ""}`}
          onClick={() => onChange(o.key)}
        >
          {o.label}
        </span>
      ))}
    </div>
  );
}
