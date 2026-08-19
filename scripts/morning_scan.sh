#!/usr/bin/env bash
# Create a "scan" AgentTask so the local worker runs a fresh scan and fills the
# Scout Inbox. Intended to be triggered on a weekday-morning schedule (launchd).
#
# Failures are reported (not swallowed): a bad port, a stopped backend, or a
# non-2xx response prints to stderr, which launchd captures in
# StandardErrorPath. On success it stays quiet.
set -euo pipefail

API="${JOBSCOUT_API_URL:-http://localhost:8000/api}"

# Capture body + HTTP status so we can tell a real 201 from a silent miss.
response="$(curl -sS -w '\n%{http_code}' -X POST "$API/agent-tasks/" \
  -H "Content-Type: application/json" \
  -d '{"kind":"scan","payload":{}}')" || {
    echo "morning_scan: could not reach $API (is the backend up?)" >&2
    exit 1
  }

status="$(printf '%s' "$response" | tail -n1)"
if [ "$status" != "201" ] && [ "$status" != "200" ]; then
  body="$(printf '%s' "$response" | sed '$d')"
  echo "morning_scan: unexpected HTTP $status from $API/agent-tasks/: $body" >&2
  exit 1
fi
