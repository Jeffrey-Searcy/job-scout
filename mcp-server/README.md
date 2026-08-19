# Job Scout MCP server

Exposes the job-search app to AI agents over the Model Context Protocol. It is a
thin, API-first wrapper over the Django REST API — no business logic lives here.

## Tools
- `pipeline_stats` — pipeline metrics
- `list_applications` — everything in the pipeline
- `add_application` — add a role you've applied to
- `update_application_status` — advance a stage
- `list_leads` — scout inbox (new by default)
- `add_lead` — **what the scout calls** to push a fresh find into the inbox
- `promote_lead` — turn a lead into an application

## Run
```
pip install -r requirements.txt
JOBSCOUT_API_URL=http://localhost:8000/api python server.py
```

## Connect to Claude Desktop
Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "job-scout": {
      "command": "python",
      "args": ["/absolute/path/to/mcp-server/server.py"],
      "env": { "JOBSCOUT_API_URL": "http://localhost:8000/api" }
    }
  }
}
```
Then ask Claude things like "add this job to my scout inbox" or "how's my pipeline?"
