// Top-level app: loads data from the API and composes the dashboard.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { getStats, getApplications, getLeads } from "./api/client.js";
import StatTiles from "./components/StatTiles.jsx";
import PipelineFunnel from "./components/PipelineFunnel.jsx";
import Filters from "./components/Filters.jsx";
import Sort from "./components/Sort.jsx";
import ApplicationCard from "./components/ApplicationCard.jsx";
import ApplicationForm from "./components/ApplicationForm.jsx";
import LeadsInbox from "./components/LeadsInbox.jsx";
import AgentControls from "./components/AgentControls.jsx";

// Sort key: active first, then by fit (strong<good<stretch), locals nudged up.
function rank(a) {
  const fitWeight = a.fit === "strong" ? 0 : a.fit === "good" ? 0.3 : 0.6;
  return (a.is_active ? 0 : 1) + fitWeight + (a.is_local ? -0.15 : 0);
}

// Rank a status for the "Status" sort: open/earlier stages first, closed last.
// Lower number sorts first, so live applications stay above rejected/ghosted.
const STATUS_ORDER = {
  offer: 0, onsite: 1, interview: 2, take_home: 3, phone_screen: 4,
  applied: 5, ghosted: 6, rejected: 7,
};

// A blank applied_date sorts to the very bottom in both date directions, so
// undated cards never jump above dated ones. We treat missing as +/-Infinity.
function appliedTime(a) {
  return a.applied_date ? new Date(a.applied_date + "T00:00:00").getTime() : null;
}

// Comparators for each Sort option key. Each returns a standard (x,y)=>number.
const SORTERS = {
  best: (x, y) => rank(x) - rank(y),
  newest: (x, y) => {
    const tx = appliedTime(x), ty = appliedTime(y);
    if (tx === null && ty === null) return 0;
    if (tx === null) return 1;   // undated after dated
    if (ty === null) return -1;
    return ty - tx;              // most recent first
  },
  oldest: (x, y) => {
    const tx = appliedTime(x), ty = appliedTime(y);
    if (tx === null && ty === null) return 0;
    if (tx === null) return 1;   // undated still last
    if (ty === null) return -1;
    return tx - ty;              // earliest first
  },
  status: (x, y) =>
    (STATUS_ORDER[x.status] ?? 99) - (STATUS_ORDER[y.status] ?? 99),
};

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
  const [sort, setSort] = useState("best");
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

  // Filter, then sort the applications for display, memoized on inputs.
  // Filtering first keeps the sort working on only the visible set.
  const visible = useMemo(() => {
    const sorter = SORTERS[sort] || SORTERS.best;
    return [...apps].filter((a) => matchesFilter(a, filter)).sort(sorter);
  }, [apps, filter, sort]);

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
        <div className="controls">
          <Filters value={filter} onChange={setFilter} />
          <Sort value={sort} onChange={setSort} />
        </div>
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
