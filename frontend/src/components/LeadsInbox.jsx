// The scout's inbox: newly discovered roles awaiting your triage.
import React, { useEffect, useRef, useState } from "react";
import { dismissLead, tailorLead, getAgentTask, tailoredResumeUrl } from "../api/client.js";

// Poll a tailor task on the same cadence and ceiling as a scan (the worker's
// CLAUDE_TIMEOUT is 600s; 220 × 3s ≈ 11 min covers it with margin). Kept in sync
// with AgentControls so both AI jobs behave the same for the user.
const POLL_MS = 3000;
const MAX_TRIES = 220;

// Human labels for the tailor task's live phases. Matches AgentTask.State.
const TAILOR_PHASE = {
  pending: { label: "Queued", hint: "Waiting for the worker…", live: true },
  running: { label: "Tailoring", hint: "Reading the job post and matching keywords. A couple of minutes.", live: true },
};

// One lead card. Owns its own "tailor" job state so each lead can be tailored and
// polled independently without touching its neighbors.
function LeadCard({ lead, onChanged }) {
  // Live phase of THIS lead's tailor job: null when idle, "pending"/"running"
  // while working, or a terminal marker ("done"/"error"/"timeout"/"lost").
  const [phase, setPhase] = useState(null);
  const [msg, setMsg] = useState("");
  const pollTimer = useRef(null);

  // Clear the poll timer if the card unmounts mid-job (e.g. list refresh).
  useEffect(() => () => clearInterval(pollTimer.current), []);

  const isLive = phase === "pending" || phase === "running";

  // Poll the tailor task until it ends, reflecting the real status as it goes.
  function poll(id) {
    let tries = 0;
    pollTimer.current = setInterval(async () => {
      tries += 1;
      try {
        const t = await getAgentTask(id);
        if (t.status === "pending" || t.status === "running") {
          setPhase(t.status);
          if (tries >= MAX_TRIES) {
            clearInterval(pollTimer.current);
            setPhase("timeout");
            setMsg("Still working — refresh in a bit to see the tailored resume.");
          }
          return;
        }
        if (t.status === "done") {
          clearInterval(pollTimer.current);
          setPhase("done");
          setMsg(t.result || "Tailored resume ready.");
          // Refresh the leads so this card picks up its new download link.
          onChanged && onChanged();
          return;
        }
        if (t.status === "error") {
          clearInterval(pollTimer.current);
          setPhase("error");
          setMsg(t.result || "Tailoring failed.");
          return;
        }
      } catch {
        // Lost contact with the API — say so, don't spin silently.
        clearInterval(pollTimer.current);
        setPhase("lost");
        setMsg("Lost contact with the app. Check your connection and refresh.");
      }
    }, POLL_MS);
  }

  // Start tailoring this lead. Surfaces the server's own message on a rejection
  // (e.g. "upload your resume first") rather than a generic error.
  async function startTailor() {
    setPhase("pending");
    setMsg("");
    try {
      const task = await tailorLead(lead.id);
      poll(task.id);
    } catch (e) {
      setPhase("error");
      // The backend sends {detail: "..."} for the known preconditions; show it.
      setMsg((e.data && e.data.detail) || "Could not start tailoring.");
    }
  }

  async function dismiss() {
    await dismissLead(lead.id);
    onChanged && onChanged();
  }

  const tr = lead.tailored_resume; // null until this lead has been tailored

  return (
    <div className="card">
      <div className="top">
        <div>
          <div className="co">{lead.company}</div>
          <div className="ro">{lead.title}</div>
        </div>
        {lead.is_local && <span className="b local">📍 Local</span>}
      </div>
      <div className="meta">
        <span>{[lead.work_mode !== "unknown" ? lead.work_mode : null, lead.location].filter(Boolean).join(" · ")}</span>
        {lead.salary_text && <span><b>{lead.salary_text}</b></span>}
      </div>
      {lead.summary && <div className="note">{lead.summary}</div>}

      <div className="row">
        {lead.url && <a className="apply" href={lead.url} target="_blank" rel="noopener noreferrer">View →</a>}
        <span>
          {/* Tailor button: disabled while its own job runs. If a tailored resume
              already exists, the label says "Re-tailor" since it replaces it. */}
          <button
            className="btn ghost"
            disabled={isLive || !lead.url}
            title={!lead.url ? "This lead has no job link to tailor against." : ""}
            onClick={startTailor}
          >
            {tr ? "↻ Re-tailor" : "✎ Tailor resume"}
          </button>
          <button className="btn ghost" onClick={dismiss}>Dismiss</button>
        </span>
      </div>

      {/* Live progress while THIS lead is being tailored. */}
      {isLive && (
        <div className="jobprog" role="status" aria-live="polite">
          <div className="jobprog-head">
            <span className="jobprog-title">
              <span className="spin" /> {TAILOR_PHASE[phase].label}
            </span>
          </div>
          <div className="jobprog-bar"><span className="jobprog-fill" /></div>
          <div className="jobprog-hint">{TAILOR_PHASE[phase].hint}</div>
        </div>
      )}

      {/* Terminal banners for the tailor job. */}
      {phase === "error" && (
        <div className="jobdone fail"><strong>✕ Tailoring failed</strong><span>{msg}</span></div>
      )}
      {(phase === "timeout" || phase === "lost") && (
        <div className="jobdone warn"><strong>⏳ Still working / interrupted</strong><span>{msg}</span></div>
      )}

      {/* The tailored resume itself, once it exists. Shows the download link and
          the keywords that were worked in, so the user can see what changed. */}
      {tr && (
        <div className="tailored">
          <a className="apply" href={tailoredResumeUrl(lead.id)}>⬇ Download tailored resume (.docx)</a>
          {tr.keywords && tr.keywords.length > 0 && (
            <div className="kw">
              <span className="kw-label">Keywords worked in:</span>{" "}
              {tr.keywords.join(", ")}
            </div>
          )}
          <div className="tailored-hint">
            Open it, tweak if you like, then <b>Save as PDF</b> to apply.
          </div>
        </div>
      )}
    </div>
  );
}

// List "new" leads with Tailor + Dismiss actions. To pursue a lead, the user
// applies on the posting site and files it via "Add from link" — so there is
// deliberately no one-click promote here. When the list is empty we explain that
// the scout will fill it, so the panel is never a confusing blank.
export default function LeadsInbox({ leads, onChanged }) {
  const newLeads = (leads || []).filter((l) => l.status === "new");

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
            <LeadCard key={l.id} lead={l} onChanged={onChanged} />
          ))}
        </div>
      )}
    </div>
  );
}
