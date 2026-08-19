// Dashboard buttons that trigger AI work (scan / add-from-link) via the task
// queue. A host-side worker running Claude Code actually does the work; here we
// just create the task and poll until it finishes, then refresh the board.
import React, { useEffect, useRef, useState } from "react";
import { createAgentTask, getAgentTask } from "../api/client.js";

// Poll settings: check every 3s, give up after ~3 minutes (scans take a bit).
const POLL_MS = 3000;
const MAX_TRIES = 60;

export default function AgentControls({ onDone }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [showLink, setShowLink] = useState(false);
  const [url, setUrl] = useState("");
  const [linkStatus, setLinkStatus] = useState("applied");
  const timer = useRef(null);

  // Clean up any running poll timer if the component unmounts.
  useEffect(() => () => clearInterval(timer.current), []);

  // Poll a task until it reaches done/error (or we time out), then refresh.
  function poll(id) {
    let tries = 0;
    timer.current = setInterval(async () => {
      tries += 1;
      try {
        const t = await getAgentTask(id);
        if (t.status === "done") {
          clearInterval(timer.current);
          setBusy(false);
          setMsg(t.result || "Done.");
          onDone && onDone();
        } else if (t.status === "error") {
          clearInterval(timer.current);
          setBusy(false);
          setMsg("Something went wrong: " + (t.result || "unknown error"));
        } else if (tries >= MAX_TRIES) {
          clearInterval(timer.current);
          setBusy(false);
          setMsg("Still running… check back in a moment, then refresh.");
        }
      } catch {
        clearInterval(timer.current);
        setBusy(false);
        setMsg("Lost contact with the API.");
      }
    }, POLL_MS);
  }

  // Kick off a scan and start polling.
  async function runScan() {
    setBusy(true);
    setMsg("Scanning for new roles… Claude is searching the boards. This can take a minute.");
    const task = await createAgentTask("scan", {});
    poll(task.id);
  }

  // Submit the add-from-link form: create an enrich task for the URL.
  async function submitLink(e) {
    e.preventDefault();
    if (!url) return;
    setShowLink(false);
    setBusy(true);
    setMsg("Reading that posting and adding it… ");
    const task = await createAgentTask("enrich", { url, status: linkStatus });
    setUrl("");
    poll(task.id);
  }

  return (
    <div className="panel actions-panel">
      <div className="actions-row">
        <button className="btn" disabled={busy} onClick={runScan}>🔍 Run scan now</button>
        <button className="btn ghost" disabled={busy} onClick={() => setShowLink((s) => !s)}>+ Add from link</button>
        {busy && <span className="working"><span className="spin" /> Working…</span>}
      </div>

      {showLink && (
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

      {msg && <div className="action-msg">{msg}</div>}
    </div>
  );
}
