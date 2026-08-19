// Add / edit form for a job application, shown in a modal overlay.
import React, { useState } from "react";
import { createApplication, updateApplication, deleteApplication } from "../api/client.js";

// Choice lists mirror the backend model so the dropdowns stay valid.
const STATUSES = ["applied", "phone_screen", "interview", "take_home", "onsite", "offer", "rejected", "ghosted"];
const MODES = ["unknown", "onsite", "hybrid", "remote"];
const FITS = ["strong", "good", "stretch"];

// Build the initial form state from an existing app (edit) or blanks (add).
function initialState(app) {
  return {
    company: app?.company || "",
    role: app?.role || "",
    link: app?.link || "",
    status: app?.status || "applied",
    work_mode: app?.work_mode || "unknown",
    location: app?.location || "",
    is_local: app?.is_local || false,
    fit: app?.fit || "good",
    salary_min: app?.salary_min || "",
    salary_max: app?.salary_max || "",
    applied_date: app?.applied_date || "",
    followup_date: app?.followup_date || "",
    contact: app?.contact || "",
    notes: app?.notes || "",
  };
}

// Modal form. `app` is null for add, or an application object for edit.
// onSaved() refreshes the parent; onClose() dismisses without saving.
export default function ApplicationForm({ app, onSaved, onClose }) {
  const [form, setForm] = useState(initialState(app));
  const [saving, setSaving] = useState(false);
  const isEdit = Boolean(app?.id);

  // Update one field by name; checkboxes use `checked`, everything else `value`.
  function set(e) {
    const { name, value, type, checked } = e.target;
    setForm((f) => ({ ...f, [name]: type === "checkbox" ? checked : value }));
  }

  // Normalize + POST/PATCH the form, then tell the parent to refresh.
  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    // Empty numeric/date strings must become null, not "" (DRF rejects "").
    const payload = {
      ...form,
      salary_min: form.salary_min === "" ? null : Number(form.salary_min),
      salary_max: form.salary_max === "" ? null : Number(form.salary_max),
      applied_date: form.applied_date || null,
      followup_date: form.followup_date || null,
    };
    try {
      if (isEdit) await updateApplication(app.id, payload);
      else await createApplication(payload);
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  // Delete an existing application (edit mode only), with a confirm.
  async function remove() {
    if (!window.confirm(`Delete ${app.company} — ${app.role}?`)) return;
    await deleteApplication(app.id);
    onSaved();
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>{isEdit ? "Edit application" : "Add application"}</h3>

        <div className="frow">
          <label>Company<input name="company" value={form.company} onChange={set} required /></label>
          <label>Role / Title<input name="role" value={form.role} onChange={set} required /></label>
        </div>

        <label>Link<input name="link" value={form.link} onChange={set} placeholder="https://…" /></label>

        <div className="frow">
          <label>Status
            <select name="status" value={form.status} onChange={set}>
              {STATUSES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
            </select>
          </label>
          <label>Work mode
            <select name="work_mode" value={form.work_mode} onChange={set}>
              {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
          <label>Fit
            <select name="fit" value={form.fit} onChange={set}>
              {FITS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </label>
        </div>

        <div className="frow">
          <label>Location<input name="location" value={form.location} onChange={set} /></label>
          <label className="chk"><input type="checkbox" name="is_local" checked={form.is_local} onChange={set} /> Local (Tampa Bay)</label>
        </div>

        <div className="frow">
          <label>Salary min ($)<input type="number" name="salary_min" value={form.salary_min} onChange={set} placeholder="146000" /></label>
          <label>Salary max ($)<input type="number" name="salary_max" value={form.salary_max} onChange={set} placeholder="206000" /></label>
        </div>

        <div className="frow">
          <label>Applied date<input type="date" name="applied_date" value={form.applied_date} onChange={set} /></label>
          <label>Follow-up date<input type="date" name="followup_date" value={form.followup_date} onChange={set} /></label>
        </div>

        <label>Contact / referral<input name="contact" value={form.contact} onChange={set} /></label>
        <label>Notes<textarea name="notes" rows="3" value={form.notes} onChange={set} /></label>

        <div className="modal-actions">
          {isEdit && <button type="button" className="btn danger" onClick={remove}>Delete</button>}
          <span className="spacer" />
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn" disabled={saving}>{saving ? "Saving…" : "Save"}</button>
        </div>
      </form>
    </div>
  );
}
