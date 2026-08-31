// The logged-out screen: a single card that toggles between "Log in" and
// "Sign up". On success it calls onAuthed(user) so App swaps to the dashboard.
//
// Sign-up is open by design — the app runs on a private Tailscale network, so
// anyone who can reach the URL is already trusted (see the backend SignupView).
import React, { useState } from "react";
import { login, signup } from "../api/client.js";

export default function AuthScreen({ onAuthed }) {
  // mode: "login" | "signup". Starts on login; a first-time user flips to signup.
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const isSignup = mode === "signup";

  // Pull the most useful message out of a DRF error body. DRF returns either
  // {detail: "..."} or {field: ["msg", ...]}; we surface the first thing we find
  // rather than a generic string, so the user sees WHY it failed.
  function messageFrom(err) {
    const data = err?.data;
    if (!data) return "Something went wrong. Please try again.";
    if (typeof data === "string") return data;
    if (data.detail) return data.detail;
    // First field error (e.g. username/password validation).
    const firstKey = Object.keys(data)[0];
    const val = firstKey ? data[firstKey] : null;
    if (Array.isArray(val)) return val[0];
    if (typeof val === "string") return val;
    return "Something went wrong. Please try again.";
  }

  async function submit(e) {
    e.preventDefault();
    if (!username || !password) {
      setError("Enter a username and password.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const user = isSignup
        ? await signup(username, password)
        : await login(username, password);
      onAuthed(user);
    } catch (err) {
      setError(messageFrom(err));
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <h1>{import.meta.env.VITE_APP_TITLE || "Job Scout"}</h1>
        <p className="auth-sub">
          {isSignup
            ? "Create your account to start your own job search."
            : "Log in to your job search."}
        </p>

        <form onSubmit={submit} className="auth-form">
          <label>
            Username
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={isSignup ? "new-password" : "current-password"}
            />
          </label>

          {error && <div className="auth-error">{error}</div>}

          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Please wait…" : isSignup ? "Sign up" : "Log in"}
          </button>
        </form>

        <button
          className="auth-toggle"
          type="button"
          onClick={() => {
            setMode(isSignup ? "login" : "signup");
            setError("");
          }}
        >
          {isSignup
            ? "Already have an account? Log in"
            : "New here? Create an account"}
        </button>
      </div>
    </div>
  );
}
