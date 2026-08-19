// Top-level app: loads data from the API and composes the dashboard.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { getStats, getApplications, getLeads } from "./api/client.js";
import StatTiles from "./components/StatTiles.jsx";
import PipelineFunnel from "./components/PipelineFunnel.jsx";
import Filters from "./components/Filters.jsx";
import ApplicationCard from "./components/ApplicationCard.jsx";
import ApplicationForm from "./components/ApplicationForm.jsx";
import LeadsInbox from "./components/LeadsInbox.jsx";
import AgentControls from "./components/AgentControls.jsx";

// Sort key: active first, then by fit (strong<good<stretch), locals nudged up.
function rank(a) {
  const fitWeight = a.fit === "strong" ? 0 : a.fit === "good" ? 0.3 : 0.6;
  return (a.is_active ? 0 : 1) + fitWeight + (a.is_local ? -0.15 : 0);
}

// Decide whether a card passes the active filter chip.
function matchesFilter(app, filter) {
  if (filter === "all") return true;
  if (filter === "active") return app.is_active;
  if (filter === "local") return app.is_local;
  if (filter === "strong") return app.fit === "strong";
  return true;
}

export default function App() {
  const [stats, setStats] = useState(null);
  const [apps, setApps] = useState([]);
  const [leads, setLeads] = useState([]);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState(null);
  // Form state: null = closed, "new" = add, or an app object = edit.
  const [formTarget, setFormTarget] = useState(null);

  // Reload everything from the API. Passed to children so any edit refreshes
  // tiles, funnel, and lists together.
  const refresh = useCallback(async () => {
    try {
      const [s, a, l] = await Promise.all([getStats(), getApplications(), getLeads()]);
      setStats(s); setApps(a); setLeads(l); setError(null);
    } catch (e) {
      setError("Can't reach the API. Is the backend running (docker compose up)?");
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // Close the form and refresh after a successful save/delete.
  const onSaved = useCallback(() => { setFormTarget(null); refresh(); }, [refresh]);

  // Sort + filter the applications for display, memoized on inputs.
  const visible = useMemo(
    () => [...apps].sort((x, y) => rank(x) - rank(y)).filter((a) => matchesFilter(a, filter)),
    [apps, filter]
  );

  return (
    <div className="wrap">
      <header>
        <h1>{import.meta.env.VITE_APP_TITLE || "Job Scout"}</h1>
        <p className="sub">Live pipeline · powered by your local Job Scout app</p>
        <div className="scout"><span className="dot" />Job Scout is on · scans every weekday morning</div>
      </header>

      {error && <div className="errbar">{error}</div>}

      <StatTiles stats={stats} />
      <PipelineFunnel funnel={stats?.funnel} />
      <AgentControls onDone={refresh} />
      <LeadsInbox leads={leads} onChanged={refresh} />

      <div className="panel">
        <div className="panel-head">
          <h2>Applications</h2>
          <button className="btn" onClick={() => setFormTarget("new")}>+ Add application</button>
        </div>
        <Filters value={filter} onChange={setFilter} />
        <div className="grid">
          {visible.map((app) => (
            <ApplicationCard key={app.id} app={app} onEdit={setFormTarget} onChanged={refresh} />
          ))}
        </div>
      </div>

      <p className="foot">
        <b>How this works:</b> Your Job Scout runs each weekday morning, finds roles matching your
        profile, and drops them in the Scout inbox above. Apply to the good ones, then file them
        with "Add from link"; dismiss the rest. Every change is saved to your local database.
      </p>

      {formTarget && (
        <ApplicationForm
          app={formTarget === "new" ? null : formTarget}
          onSaved={onSaved}
          onClose={() => setFormTarget(null)}
        />
      )}
    </div>
  );
}
