// Dropdown that picks how the application cards are ordered.
// Controlled: the parent owns the active value and the change handler, exactly
// like Filters, so all list state lives in App.
import React from "react";

// The selectable sort orders. Keys are matched in App's sorter; labels are shown.
export const SORT_OPTIONS = [
  { key: "best", label: "Best match" },
  { key: "newest", label: "Newest applied" },
  { key: "oldest", label: "Oldest applied" },
  { key: "status", label: "Status" },
];

export default function Sort({ value, onChange }) {
  return (
    <label className="sort">
      <span className="sort-l">Sort</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {SORT_OPTIONS.map((o) => (
          <option key={o.key} value={o.key}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}
