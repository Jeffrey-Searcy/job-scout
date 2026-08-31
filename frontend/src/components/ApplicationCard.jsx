// One application rendered as a card: identity, fit, a stage stepper, a
// follow-up flag, an attached-resume record, and quick actions (inline status
// change + edit).
import React, { useRef, useState } from "react";
import {
  updateApplicationStatus,
  attachApplicationResume,
  deleteApplicationResume,
  applicationResumeUrl,
} from "../api/client.js";

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

// The "resume submitted for this application" record. Shows a download link and
// filename when a resume is attached, and an attach/replace/remove control. Owns
// its own upload state so one card's upload never touches its neighbors. `onDone`
// refreshes the list so the new resume_file block shows up.
function ResumeAttachment({ app, onDone }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const fileInput = useRef(null);

  const attached = app.resume_file; // {filename, download_url, updated_at} or null

  // Upload the picked file, then refresh. Surfaces the server's own message on a
  // rejection (wrong type / too large) rather than a generic error.
  async function onPick(e) {
    const file = e.target.files && e.target.files[0];
    // Reset the input so picking the same file again still fires onChange.
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    setErr("");
    try {
      await attachApplicationResume(app.id, file);
      onDone && onDone();
    } catch (ex) {
      setErr((ex.data && ex.data.detail) || "Could not attach the resume.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setErr("");
    try {
      await deleteApplicationResume(app.id);
      onDone && onDone();
    } catch (ex) {
      setErr((ex.data && ex.data.detail) || "Could not remove the resume.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="resattach">
      {/* Hidden real input; the visible buttons trigger it. Accepts PDF + .docx,
          the two formats the attach endpoint allows. */}
      <input
        ref={fileInput}
        type="file"
        accept=".pdf,.docx"
        style={{ display: "none" }}
        onChange={onPick}
      />
      {attached ? (
        <>
          <a className="apply" href={applicationResumeUrl(app.id)}>
            ⬇ Resume used: {attached.filename}
          </a>
          <span className="resattach-actions">
            <button className="btn ghost" disabled={busy} onClick={() => fileInput.current.click()}>
              {busy ? "Working…" : "Replace"}
            </button>
            <button className="btn ghost" disabled={busy} onClick={remove}>
              Remove
            </button>
          </span>
        </>
      ) : (
        <button className="btn ghost" disabled={busy} onClick={() => fileInput.current.click()}>
          {busy ? "Attaching…" : "📎 Attach resume used"}
        </button>
      )}
      {err && <div className="resattach-err">{err}</div>}
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
      <div className="meta applied">
        <span>{app.applied_date ? `Applied ${formatApplied(app.applied_date)}` : "No applied date set"}</span>
      </div>
      {app.contact && <div className="note">{app.contact}</div>}

      <div className="row">
        <select className={`statusSel ${active ? "active" : ""}`} value={app.status} onChange={changeStatus}>
          {Object.entries(STATUS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        {app.link && <a className="apply" href={app.link} target="_blank" rel="noopener noreferrer">View posting →</a>}
      </div>

      <ResumeAttachment app={app} onDone={onChanged} />
    </div>
  );
}

// Capitalize a work-mode label ("remote" -> "Remote").
function capitalize(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

// Format an ISO date string ("2026-03-04") as a short human date ("Mar 4, 2026").
// The "T00:00:00" anchor forces local time so the day never shifts by a timezone.
function formatApplied(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
