# Admin client

Typed Python client generated from Backend Core's supported Admin OpenAPI surface.
Do not edit `src/admin_client/generated` manually.

Regenerate the schema and client together:

```bash
uv run python -m scripts.generate_admin_client
```

The script runs the pinned `openapi-python-client==0.29.0` generator through
`uvx`, keeping code-generation dependencies out of workspace runtimes.

Verify committed output is current:

```bash
uv run python -m scripts.generate_admin_client --check
```

The Control Plane Management client is generated independently from the mounted
`/management/v1` schema:

```bash
uv run python -m scripts.generate_control_plane_client
uv run python -m scripts.generate_control_plane_client --check
```
