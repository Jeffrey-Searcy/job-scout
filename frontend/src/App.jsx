// Top-level app: gates on login, then loads the logged-in user's data and
// composes their dashboard. Every data call is scoped server-side to the session
// user, so each person sees only their own pipeline, leads, and resume.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  getStats,
  getApplications,
  getLeads,
  primeCsrf,
  getMe,
  logout,
} from "./api/client.js";
import StatTiles from "./components/StatTiles.jsx";
import PipelineFunnel from "./components/PipelineFunnel.jsx";
import Filters from "./components/Filters.jsx";
import Sort from "./components/Sort.jsx";
import ApplicationCard from "./components/ApplicationCard.jsx";
import ApplicationForm from "./components/ApplicationForm.jsx";
import LeadsInbox from "./components/LeadsInbox.jsx";
import AgentControls from "./components/AgentControls.jsx";
import AuthScreen from "./components/AuthScreen.jsx";
import ResumePanel from "./components/ResumePanel.jsx";

// Sort key: active first, then by fit (strong<good<stretch), locals nudged up.
function rank(a) {
  const fitWeight = a.fit === "strong" ? 0 : a.fit === "good" ? 0.3 : 0.6;
  return (a.is_active ? 0 : 1) + fitWeight + (a.is_local ? -0.15 : 0);
}

// A blank applied_date sorts to the very bottom in both date directions, so
// undated cards never jump above dated ones. We treat missing as null.
function appliedTime(a) {
  return a.applied_date ? new Date(a.applied_date + "T00:00:00").getTime() : null;
}

// Comparators for the "Sort by" views. Each returns a standard (x,y)=>number.
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
};

// The "Show only" status views: each maps a view key to the raw statuses it
// includes. "interviewing" groups every in-process stage. A view not listed
// here (and not in DATE_VIEW) is a sort view, so it shows all statuses.
const STATUS_VIEW = {
  applied: ["applied"],
  interviewing: ["phone_screen", "interview", "take_home", "onsite"],
  offer: ["offer"],
  rejected: ["rejected"],
};

// Today's date as a local "YYYY-MM-DD" string, to compare against applied_date
// (which the API stores in that same plain-date form). Built from local time so
// "today" matches the user's calendar day, not UTC.
function todayISO() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

// The "Show only" date views: each maps a view key to a predicate over an app.
const DATE_VIEW = {
  today: (a) => a.applied_date === todayISO(),
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
  // Auth state. `user` is null when logged out. `authChecked` gates the first
  // render so we don't flash the login screen before /auth/me/ answers.
  const [user, setUser] = useState(null);
  const [authChecked, setAuthChecked] = useState(false);

  const [stats, setStats] = useState(null);
  const [apps, setApps] = useState([]);
  const [leads, setLeads] = useState([]);
  const [filter, setFilter] = useState("all");
  // The View dropdown value: a sort key (best/newest/oldest) OR a status view
  // key (applied/interviewing/offer/rejected). See SORTERS and STATUS_VIEW.
  const [view, setView] = useState("best");
  const [error, setError] = useState(null);
  // Form state: null = closed, "new" = add, or an app object = edit.
  const [formTarget, setFormTarget] = useState(null);

  // On load: prime the CSRF cookie, then ask who we are. A logged-in user lands
  // straight on their dashboard; anyone else sees the login screen. We treat any
  // failure of getMe as "not logged in" (the endpoint 403s when unauthenticated).
  useEffect(() => {
    (async () => {
      try {
        await primeCsrf();
      } catch {
        // If even the CSRF prime fails the API is unreachable; the dashboard's
        // own refresh() will show the API-down banner. Still show the login UI.
      }
      try {
        const me = await getMe();
        setUser(me);
      } catch {
        setUser(null);
      } finally {
        setAuthChecked(true);
      }
    })();
  }, []);

  // Reload everything from the API. Passed to children so any edit refreshes
  // tiles, funnel, and lists together.
  const refresh = useCallback(async () => {
    try {
      const [s, a, l] = await Promise.all([getStats(), getApplications(), getLeads()]);
      setStats(s); setApps(a); setLeads(l); setError(null);
    } catch (e) {
      // A 403 here means the session ended (e.g. logged out in another tab).
      // Drop back to the login screen instead of showing a stale dashboard.
      if (e && e.status === 403) {
        setUser(null);
        return;
      }
      setError("Can't reach the API. Is the backend running (docker compose up)?");
    }
  }, []);

  // Load the dashboard data only once we have a logged-in user.
  useEffect(() => {
    if (user) refresh();
  }, [user, refresh]);

  // After a successful login/signup, remember the user and let the data effect
  // above pull their dashboard.
  const onAuthed = useCallback((u) => {
    setUser(u);
  }, []);

  // Log out: end the server session, clear local state back to the login screen.
  const onLogout = useCallback(async () => {
    try {
      await logout();
    } catch {
      // Even if the network call fails, drop the local user so the UI locks.
    }
    setUser(null);
    setStats(null);
    setApps([]);
    setLeads([]);
  }, []);

  // Close the form and refresh after a successful save/delete.
  const onSaved = useCallback(() => { setFormTarget(null); refresh(); }, [refresh]);

  // Build the visible list, memoized on inputs. Order of operations:
  //   1. Apply the chip filter (All/Active/Local/Strong fit).
  //   2. If the View is a "show only" status or date view, keep just its matches.
  //   3. Sort: by the chosen sort view, or Best match when a show-only view is on.
  const visible = useMemo(() => {
    const statuses = STATUS_VIEW[view];            // undefined for non-status views
    const datePred = DATE_VIEW[view];              // undefined for non-date views
    const sorter = SORTERS[view] || SORTERS.best;  // show-only views fall back to best
    return [...apps]
      .filter((a) => matchesFilter(a, filter))
      .filter((a) => (statuses ? statuses.includes(a.status) : true))
      .filter((a) => (datePred ? datePred(a) : true))
      .sort(sorter);
  }, [apps, filter, view]);

  // Wait for the auth check before deciding what to show, so we never flash the
  // login screen at an already-logged-in user.
  if (!authChecked) {
    return <div className="wrap"><p className="sub">Loading…</p></div>;
  }

  // Logged out → the login/signup screen. On success onAuthed swaps us in.
  if (!user) {
    return <AuthScreen onAuthed={onAuthed} />;
  }

  return (
    <div className="wrap">
      <header>
        <div className="header-top">
          <h1>{import.meta.env.VITE_APP_TITLE || "Job Scout"}</h1>
          {/* Who's logged in + a way out. */}
          <div className="user-box">
            <span className="user-name">{user.username}</span>
            <button className="btn ghost" onClick={onLogout}>Log out</button>
          </div>
        </div>
        <p className="sub">Live pipeline · powered by your local Job Scout app</p>
        <div className="scout"><span className="dot" />Job Scout is on · scans every weekday morning</div>
      </header>

      {error && <div className="errbar">{error}</div>}

      <ResumePanel />
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
          <Sort value={view} onChange={setView} />
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
