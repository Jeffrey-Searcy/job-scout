// The scout's inbox: newly discovered roles awaiting your triage.
import React from "react";
import { dismissLead } from "../api/client.js";

// List "new" leads with a Dismiss action. To pursue a lead, the user applies on
// the posting site and files it via "Add from link" (which enriches from the
// real posting) — so there is deliberately no one-click promote here. When the
// list is empty we explain that the scout will fill it, so the panel is never
// a confusing blank.
export default function LeadsInbox({ leads, onChanged }) {
  const newLeads = (leads || []).filter((l) => l.status === "new");

  // Dismiss a lead so it leaves the inbox, then refresh.
  async function dismiss(id) {
    await dismissLead(id);
    onChanged && onChanged();
  }

  return (
    <div className="panel">
      <h2>Scout inbox {newLeads.length ? `(${newLeads.length} new)` : ""}</h2>
      {newLeads.length === 0 ? (
        <p className="empty">
          No new leads right now. Your Job Scout adds matching roles here as it finds
          them — apply to the good ones (then file them with "Add from link"), dismiss the rest.
        </p>
      ) : (
        <div className="grid">
          {newLeads.map((l) => (
            <div className="card" key={l.id}>
              <div className="top">
                <div>
                  <div className="co">{l.company}</div>
                  <div className="ro">{l.title}</div>
                </div>
                {l.is_local && <span className="b local">📍 Local</span>}
              </div>
              <div className="meta">
                <span>{[l.work_mode !== "unknown" ? l.work_mode : null, l.location].filter(Boolean).join(" · ")}</span>
                {l.salary_text && <span><b>{l.salary_text}</b></span>}
              </div>
              {l.summary && <div className="note">{l.summary}</div>}
              <div className="row">
                {l.url && <a className="apply" href={l.url} target="_blank" rel="noopener noreferrer">View →</a>}
                <span>
                  <button className="btn ghost" onClick={() => dismiss(l.id)}>Dismiss</button>
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
