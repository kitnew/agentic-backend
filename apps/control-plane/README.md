# agentctl

`agentctl` is the operator CLI for the Backend Admin API.

## Workspace commands

The canonical workspace lifecycle is shared by Platform and all tenants:

```bash
uv run agentctl status
uv run agentctl pull
uv run agentctl plan
uv run agentctl push
uv run agentctl publish
```

Use the same explicit scope grammar for a narrower operation:

```bash
uv run agentctl status platform
uv run agentctl pull tenant hotel
uv run agentctl plan tenant hotel
uv run agentctl push tenant hotel
uv run agentctl publish tenant hotel
```

Global commands discover tenant identities through Backend. They do not infer
tenants only from local directories. `status` does not write workspace state;
`pull` writes projections only after global preflight; `plan` is read-only;
`push` saves drafts but never publishes; `publish` delegates aggregate Backend
publication and reports partial cross-scope failures without pretending that
rollback occurred.

## Tenant and operational commands

```bash
uv run agentctl tenant list
uv run agentctl tenant show hotel
uv run agentctl tenant create hotel --display-name "Hotel" --business-type hotel

uv run agentctl integration list hotel
uv run agentctl integration show hotel check-availability
uv run agentctl did show hotel
```

Integration and DID are live operational facades, not local workspace
resources. Platform inspection commands (`system-prompt`, `runtime`, and
`profile`) remain available for read-only active-value/revision inspection;
workspace mutation uses only the five lifecycle commands above.
