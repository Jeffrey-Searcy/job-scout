// Dashboard buttons that trigger AI work (scan / add-from-link) via the task
// queue. A host-side worker running Claude Code actually does the work; here we
// create the task and poll it, showing a live progress indicator so the user
// can always tell what state their scan is in (queued → running → done/failed).
//
// Why a live indicator: a scan is a background job the user cannot see. Without
// a clear status they cannot tell a finished scan from a stuck one. So we show
// the real task.status, an animated progress bar, an elapsed timer, and a clear
// final banner with the result or the error. We never fake a percentage — the
// worker does not report granular progress — so the bar is an honest
// "still working" animation, not a lie about how far along it is.
import React, { useEffect, useRef, useState } from "react";
import { createAgentTask, getAgentTask } from "../api/client.js";

// Poll every 3s. The worker's own hard ceiling is CLAUDE_TIMEOUT (default 600s
// = 10 min), so we poll a little past that before we stop watching. The OLD
// value (3 min) gave up while real scans were still running, which is exactly
// what made "did it finish?" impossible to answer. 220 tries × 3s ≈ 11 min.
const POLL_MS = 3000;
const MAX_TRIES = 220;

// The task lifecycle we surface, in order. Keep these strings in sync with the
// backend AgentTask.State values ("pending" | "running" | "done" | "error").
const PHASE = {
  pending: { label: "Queued", hint: "Waiting for the worker to pick it up…", live: true },
  running: { label: "Running", hint: "Claude is searching the boards. This can take a few minutes.", live: true },
  done: { label: "Done", hint: "", live: false },
  error: { label: "Failed", hint: "", live: false },
};

// Format a whole-second elapsed count as "0:07" / "1:23".
function fmtElapsed(totalSeconds) {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function AgentControls({ onDone }) {
  const [busy, setBusy] = useState(false);
  // The live task status string ("pending"/"running") while a job runs, or a
  // terminal marker ("done"/"error"/"timeout"/"lost") once it ends.
  const [phase, setPhase] = useState(null);
  // The final message shown in the terminal banner (result text or error text).
  const [finalMsg, setFinalMsg] = useState("");
  // What kind of job is running, for the label ("scan" / "link").
  const [jobKind, setJobKind] = useState("");
  // Seconds since the job started, driven by a 1s ticker while busy.
  const [elapsed, setElapsed] = useState(0);

  const [showLink, setShowLink] = useState(false);
  const [url, setUrl] = useState("");
  const [linkStatus, setLinkStatus] = useState("applied");

  const pollTimer = useRef(null);
  const tickTimer = useRef(null);

  // Clean up both timers if the component unmounts mid-poll.
  useEffect(() => () => {
    clearInterval(pollTimer.current);
    clearInterval(tickTimer.current);
  }, []);

  // Stop both timers and drop out of the busy state. Called on every terminal
  // outcome so we never leave a timer running.
  function stopWatching() {
    clearInterval(pollTimer.current);
    clearInterval(tickTimer.current);
    setBusy(false);
  }

  // Poll a task until it reaches done/error (or we time out), updating `phase`
  // live so the indicator reflects the real backend state at each step.
  function poll(id) {
    let tries = 0;
    pollTimer.current = setInterval(async () => {
      tries += 1;
      try {
        const t = await getAgentTask(id);
        // Reflect the real status (pending vs running) as it changes.
        if (t.status === "pending" || t.status === "running") {
          setPhase(t.status);
          if (tries >= MAX_TRIES) {
            // We stopped watching, but the job may still finish on the worker.
            // Say so honestly rather than claiming success or failure.
            stopWatching();
            setPhase("timeout");
            setFinalMsg(
              "Still running after a while — the worker may still finish it. " +
              "Refresh in a bit to see new results."
            );
          }
          return;
        }
        if (t.status === "done") {
          stopWatching();
          setPhase("done");
          setFinalMsg(t.result || "Finished. No new results this time.");
          onDone && onDone();
          return;
        }
        if (t.status === "error") {
          stopWatching();
          setPhase("error");
          setFinalMsg(t.result || "Unknown error.");
          return;
        }
      } catch {
        // A failed poll means we lost contact with the API. Surface it — do not
        // silently keep spinning as if all were well.
        stopWatching();
        setPhase("lost");
        setFinalMsg("Lost contact with the app. Check your connection and refresh.");
      }
    }, POLL_MS);
  }

  // Shared start-up for any job: reset the indicator, start the elapsed ticker,
  // and begin polling the given task id.
  function begin(kind, taskId) {
    setBusy(true);
    setJobKind(kind);
    setPhase("pending");
    setFinalMsg("");
    setElapsed(0);
    // Drive the visible elapsed timer once a second, independent of the 3s poll.
    tickTimer.current = setInterval(() => setElapsed((e) => e + 1), 1000);
    poll(taskId);
  }

  // Kick off a scan.
  async function runScan() {
    try {
      const task = await createAgentTask("scan", {});
      begin("scan", task.id);
    } catch {
      setPhase("lost");
      setFinalMsg("Could not start the scan — the app did not accept the request.");
    }
  }

  // Submit the add-from-link form: create an enrich task for the URL.
  async function submitLink(e) {
    e.preventDefault();
    if (!url) return;
    setShowLink(false);
    try {
      const task = await createAgentTask("enrich", { url, status: linkStatus });
      setUrl("");
      begin("link", task.id);
    } catch {
      setPhase("lost");
      setFinalMsg("Could not add that link — the app did not accept the request.");
    }
  }

  // A job is "live" (bar animating) only while queued or running.
  const isLive = phase != null && PHASE[phase]?.live === true;
  const jobNoun = jobKind === "link" ? "Add-from-link" : "Scan";

  return (
    <div className="panel actions-panel">
      <div className="actions-row">
        <button className="btn" disabled={busy} onClick={runScan}>🔍 Run scan now</button>
        <button className="btn ghost" disabled={busy} onClick={() => setShowLink((s) => !s)}>+ Add from link</button>
      </div>

      {showLink && !busy && (
        <form className="linkform" onSubmit={submitLink}>
          <input placeholder="Paste a job posting URL" value={url} onChange={(e) => setUrl(e.target.value)} />
          <select value={linkStatus} onChange={(e) => setLinkStatus(e.target.value)}>
            <option value="applied">Applied</option>
            <option value="phone_screen">Phone screen</option>
            <option value="interview">Interview</option>
          </select>
          <button className="btn" type="submit">Add</button>
        </form>
      )}

      {/* Live progress panel: shown while a job runs (queued/running). */}
      {isLive && (
        <div className="jobprog" role="status" aria-live="polite">
          <div className="jobprog-head">
            <span className="jobprog-title">
              <span className="spin" /> {jobNoun}: {PHASE[phase].label}
            </span>
            <span className="jobprog-time">{fmtElapsed(elapsed)}</span>
          </div>
          <div className="jobprog-bar"><span className="jobprog-fill" /></div>
          <div className="jobprog-hint">{PHASE[phase].hint}</div>
        </div>
      )}

      {/* Terminal banner: one clear final state once the job ends. */}
      {!isLive && phase === "done" && (
        <div className="jobdone ok">
          <strong>✓ {jobNoun} complete</strong>
          <span>{finalMsg}</span>
        </div>
      )}
      {!isLive && phase === "error" && (
        <div className="jobdone fail">
          <strong>✕ {jobNoun} failed</strong>
          <span>{finalMsg}</span>
        </div>
      )}
      {!isLive && (phase === "timeout" || phase === "lost") && (
        <div className="jobdone warn">
          <strong>⏳ {jobNoun}: still working / interrupted</strong>
          <span>{finalMsg}</span>
        </div>
      )}
    </div>
  );
}
