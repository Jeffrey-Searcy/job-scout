// One application rendered as a card: identity, fit, a stage stepper, a
// follow-up flag, and quick actions (inline status change + edit).
import React from "react";
import { updateApplicationStatus } from "../api/client.js";

const FIT_LABEL = { strong: "Strong fit", good: "Good fit", stretch: "Stretch" };
const STATUS_LABEL = {
  applied: "Applied", phone_screen: "Phone screen", interview: "Interview",
  take_home: "Take-home", onsite: "Onsite", offer: "Offer",
  rejected: "Rejected", ghosted: "Ghosted",
};

// The visible funnel steps and which raw statuses map onto each step index.
const STEPS = ["Applied", "Phone", "Interview", "Offer"];
const STEP_OF = {
  applied: 0, phone_screen: 1, interview: 2, take_home: 2, onsite: 2, offer: 3,
};

// Compute follow-up urgency relative to today (client-side date is fine here).
// Returns null (nothing to show), "due" (today), or "overdue" (past).
function followupState(app) {
  const openStages = ["applied", "phone_screen", "interview", "take_home", "onsite"];
  if (!app.followup_date || !openStages.includes(app.status)) return null;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const fu = new Date(app.followup_date + "T00:00:00");
  if (fu < today) return "overdue";
  if (fu.getTime() === today.getTime()) return "due";
  return null;
}

// Small horizontal stepper showing how far this app has progressed.
function Stepper({ status }) {
  const closed = status === "rejected" || status === "ghosted";
  const current = STEP_OF[status] ?? 0;
  if (closed) return <div className="stepper closed">Closed · {STATUS_LABEL[status]}</div>;
  return (
    <div className="stepper">
      {STEPS.map((label, i) => (
        <React.Fragment key={label}>
          <div className={`step ${i < current ? "done" : ""} ${i === current ? "current" : ""}`}>
            <span className="node" />
            <span className="slabel">{label}</span>
          </div>
          {i < STEPS.length - 1 && <span className={`bar ${i < current ? "done" : ""}`} />}
        </React.Fragment>
      ))}
    </div>
  );
}

// Render a single application. `onEdit` opens the edit form; `onChanged`
// refreshes derived data after an inline status change.
export default function ApplicationCard({ app, onEdit, onChanged }) {
  const active = app.is_active;
  const fu = followupState(app);

  // Persist a status change from the quick dropdown, then refresh.
  async function changeStatus(e) {
    await updateApplicationStatus(app.id, e.target.value);
    onChanged && onChanged();
  }

  return (
    <div className={`card ${active ? "active" : ""}`}>
      <div className="top">
        <div>
          <div className="co">{app.company}</div>
          <div className="ro">{app.role}</div>
        </div>
        <button className="editbtn" title="Edit" onClick={() => onEdit(app)}>✎</button>
      </div>

      <Stepper status={app.status} />

      <div className="badges">
        {app.is_local && <span className="b local">📍 Local</span>}
        <span className={`b ${app.fit}`}>{FIT_LABEL[app.fit]}</span>
        {fu === "overdue" && <span className="b overdue">⏰ Follow-up overdue</span>}
        {fu === "due" && <span className="b due">⏰ Follow up today</span>}
      </div>

      <div className="meta">
        <span>{[app.work_mode !== "unknown" ? capitalize(app.work_mode) : null, app.location].filter(Boolean).join(" · ")}</span>
        {app.salary_display && <span><b>{app.salary_display}</b></span>}
      </div>
      {app.contact && <div className="note">{app.contact}</div>}

      <div className="row">
        <select className={`statusSel ${active ? "active" : ""}`} value={app.status} onChange={changeStatus}>
          {Object.entries(STATUS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        {app.link && <a className="apply" href={app.link} target="_blank" rel="noopener noreferrer">View posting →</a>}
      </div>
    </div>
  );
}

// Capitalize a work-mode label ("remote" -> "Remote").
function capitalize(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}
