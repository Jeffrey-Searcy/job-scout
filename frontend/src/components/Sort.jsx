// Dropdown that picks how the application cards are shown — one menu that both
// orders the list (the first group) and narrows it to a status (the second).
// Controlled: the parent owns the active value and the change handler, exactly
// like Filters, so all list state lives in App.
import React from "react";

// The selectable views. `kind` tells App whether a choice sorts or filters:
//   - "sort"   -> reorder the visible cards (App's SORTERS map)
//   - "status" -> show only apps whose stage maps to this key (App's STATUS_VIEW)
// Keeping both in one menu matches how the user thinks about it: "show me …".
export const VIEW_OPTIONS = [
  { key: "best", label: "Best match", kind: "sort" },
  { key: "newest", label: "Newest applied", kind: "sort" },
  { key: "oldest", label: "Oldest applied", kind: "sort" },
  { key: "applied", label: "Applied only", kind: "status" },
  { key: "interviewing", label: "Interviewing", kind: "status" },
  { key: "offer", label: "Offers", kind: "status" },
  { key: "rejected", label: "Rejected", kind: "status" },
];

export default function Sort({ value, onChange }) {
  return (
    <label className="sort">
      <span className="sort-l">View</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <optgroup label="Sort by">
          {VIEW_OPTIONS.filter((o) => o.kind === "sort").map((o) => (
            <option key={o.key} value={o.key}>{o.label}</option>
          ))}
        </optgroup>
        <optgroup label="Show only">
          {VIEW_OPTIONS.filter((o) => o.kind === "status").map((o) => (
            <option key={o.key} value={o.key}>{o.label}</option>
          ))}
        </optgroup>
      </select>
    </label>
  );
}
