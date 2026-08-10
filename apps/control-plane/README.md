# Agent Control Plane

`agentctl` is the command-line client for Backend Core's Admin API.

```bash
export AGENTCTL_API_URL=http://localhost:8000
export AGENTCTL_TOKEN=development-admin-token-change-me-now
export AGENTCTL_STATE_DIR=./control-plane

uv run agentctl --help
uv run agentctl --version
uv run agentctl tenant list
uv run agentctl system-prompt plan
uv run agentctl profile list
```

`--api-url` overrides `AGENTCTL_API_URL`. The token is accepted only through the
environment and is never printed. `--state-dir` overrides `AGENTCTL_STATE_DIR`;
the default canonical state root is `./control-plane`.

```bash
uv run agentctl system-prompt pull
# edit control-plane/platform/system_prompt.md
uv run agentctl system-prompt plan
uv run agentctl system-prompt push
uv run agentctl system-prompt publish

uv run agentctl profile pull hotel_assistant
# for a new key with an existing canonical file:
# uv run agentctl profile create hotel_assistant
uv run agentctl profile plan hotel_assistant
uv run agentctl profile push hotel_assistant
uv run agentctl profile publish hotel_assistant

uv run agentctl tenant prompt pull penzion-grand
# edit control-plane/tenants/penzion-grand/tenant_prompt.md
uv run agentctl tenant prompt plan penzion-grand
uv run agentctl tenant prompt push penzion-grand
uv run agentctl tenant prompt publish penzion-grand
```

TenantPrompt publication remains separate from PromptSet composition and
activation; publishing the artifact alone does not change runtime behavior.
