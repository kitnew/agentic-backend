# Agent Control Plane

`agentctl` is the command-line client for Backend Core's Admin API.

```bash
export AGENTCTL_API_URL=http://localhost:8000
export AGENTCTL_TOKEN=development-admin-token-change-me-now

uv run agentctl --help
uv run agentctl --version
uv run agentctl tenant list
```

`--api-url` overrides `AGENTCTL_API_URL`. The token is accepted only through the
environment and is never printed.
