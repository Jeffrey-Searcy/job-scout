// Resume panel: shows the current resume status and lets the user upload,
// replace, or remove their resume PDF. The scout searches against the profile
// distilled from this PDF, so this is the one thing a new user must set up.
//
// State the backend gives us (via getResume): null when none uploaded, or a
// resume object with `profile_ready` telling us whether the worker has distilled
// a search profile from the PDF yet.
import React, { useEffect, useRef, useState } from "react";
import { getResume, uploadResume, deleteResume } from "../api/client.js";

export default function ResumePanel() {
  const [resume, setResume] = useState(null); // null = none uploaded
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef(null);

  // Load the current resume status on mount.
  async function load() {
    setLoading(true);
    try {
      setResume(await getResume());
      setError("");
    } catch {
      setError("Couldn't load your resume status.");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    load();
  }, []);

  // Upload/replace: the file input's onChange hands us the chosen File.
  async function onFile(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const updated = await uploadResume(file);
      setResume(updated);
    } catch (err) {
      // Surface the server's validation message (e.g. "must be a .pdf file").
      const data = err?.data;
      const msg =
        (data && (data.detail || (data.pdf && data.pdf[0]))) ||
        "Upload failed. Make sure it's a PDF under 5 MB.";
      setError(msg);
    } finally {
      setBusy(false);
      // Reset the input so re-choosing the same filename still fires onChange.
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function onDelete() {
    setBusy(true);
    setError("");
    try {
      await deleteResume();
      setResume(null);
    } catch {
      setError("Couldn't remove your resume.");
    } finally {
      setBusy(false);
    }
  }

  const hasResume = resume !== null;
  // profile_ready: the worker has turned the PDF into a search profile. Until
  // then a scan can't run for this user, so we say so plainly.
  const ready = hasResume && resume.profile_ready;

  return (
    <div className="panel resume-panel">
      <div className="panel-head">
        <h2>Your resume</h2>
        {hasResume && (
          <span className={`resume-badge ${ready ? "ok" : "pending"}`}>
            {ready ? "Profile ready" : "Profile pending"}
          </span>
        )}
      </div>

      {loading ? (
        <p className="resume-hint">Loading…</p>
      ) : (
        <>
          {!hasResume && (
            <p className="resume-hint">
              Upload your resume (PDF) so the scout knows what roles to look for.
              The scan uses a short profile built from it.
            </p>
          )}
          {hasResume && !ready && (
            <p className="resume-hint">
              Uploaded. The scout builds your search profile the first time it
              runs — run a scan and it will read your resume once.
            </p>
          )}
          {hasResume && ready && (
            <p className="resume-hint">
              Your search profile is ready. Scans now look for roles that match
              your resume.
            </p>
          )}

          {error && <div className="resume-error">{error}</div>}

          <div className="resume-actions">
            {/* Hidden file input; the buttons drive it so we control the label. */}
            <input
              ref={fileInput}
              type="file"
              accept="application/pdf,.pdf"
              onChange={onFile}
              style={{ display: "none" }}
            />
            <button
              className="btn"
              disabled={busy}
              onClick={() => fileInput.current && fileInput.current.click()}
            >
              {busy ? "Uploading…" : hasResume ? "Replace resume" : "Upload resume (PDF)"}
            </button>
            {hasResume && (
              <button className="btn ghost" disabled={busy} onClick={onDelete}>
                Remove
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
