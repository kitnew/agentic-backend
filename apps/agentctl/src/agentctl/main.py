import sys
from argparse import ArgumentParser
from collections.abc import Sequence
from json import dumps, loads

import httpx

from agentctl import __version__
from agentctl.commands.errors import CommandError
from agentctl.commands.platform import (
    run_platform_runtime,
    run_profile,
    run_system_prompt,
)
from agentctl.commands.workspace import WorkspaceSelection, run_workspace
from agentctl.settings import Settings, SettingsError


def run_integration(*args, **kwargs):
    from agentctl.commands.integrations import run_integration as command

    return command(*args, **kwargs)


def run_did(*args, **kwargs):
    from agentctl.commands.did import run_did as command

    return command(*args, **kwargs)


def fetch_tenants(*args, **kwargs):
    from agentctl.commands.tenants import fetch_tenants as command

    return command(*args, **kwargs)


def run_tenant_create(*args, **kwargs):
    from agentctl.commands.tenants import run_tenant_create as command

    return command(*args, **kwargs)


def run_tenant_show(*args, **kwargs):
    from agentctl.commands.tenants import run_tenant_show as command

    return command(*args, **kwargs)


def run_managed(*args, **kwargs):
    from agentctl.commands.managed import run_managed as command

    return command(*args, **kwargs)


def parser() -> ArgumentParser:
    root = ArgumentParser(prog="agentctl")
    root.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    root.add_argument("--api-url", help="override AGENTCTL_API_URL")
    root.add_argument("--control-plane-url", help="override AGENTCTL_CONTROL_PLANE_URL")
    root.add_argument("--state-dir", help="override AGENTCTL_STATE_DIR")
    resources = root.add_subparsers(dest="resource", required=True)
    tenant = resources.add_parser("tenant", help="inspect tenants")
    actions = tenant.add_subparsers(dest="tenant_action", required=True)
    actions.add_parser("list", help="list tenants")
    actions.add_parser("show", help="show tenant state").add_argument("slug")
    create = actions.add_parser("create", help="create a tenant")
    create.add_argument("slug")
    create.add_argument("--display-name", required=True)
    create.add_argument("--business-type", required=True)
    create.add_argument(
        "--status", choices=("active", "suspended", "archived"), default="active"
    )
    system = resources.add_parser(
        "system-prompt", help="inspect the platform System Prompt"
    )
    system_actions = system.add_subparsers(dest="action", required=True)
    for action in ("show", "push", "publish", "revisions"):
        system_actions.add_parser(action)
    rollback = system_actions.add_parser("rollback")
    rollback.add_argument("revision_number", type=int)
    runtime = resources.add_parser("runtime", help="inspect the platform Runtime policy")
    runtime_actions = runtime.add_subparsers(dest="action", required=True)
    runtime_actions.add_parser("show")
    runtime_actions.add_parser("push")
    runtime_actions.add_parser("publish")
    revisions = runtime_actions.add_parser("revisions")
    revisions.add_argument("component", choices=("llm", "stt", "tts", "cascade", "realtime"), nargs="?")
    rollback = runtime_actions.add_parser("rollback")
    rollback.add_argument("component", choices=("llm", "stt", "tts", "cascade", "realtime"))
    rollback.add_argument("revision_number", type=int)
    profile = resources.add_parser("profile", help="inspect platform Profile Prompts")
    profile_actions = profile.add_subparsers(dest="action", required=True)
    profile_actions.add_parser("list")
    for action in ("show", "push", "publish", "revisions"):
        command = profile_actions.add_parser(action)
        command.add_argument("profile_key")
    rollback = profile_actions.add_parser("rollback")
    rollback.add_argument("profile_key")
    rollback.add_argument("revision_number", type=int)
    for workspace_action in ("status", "pull", "plan", "push", "publish"):
        workspace = resources.add_parser(
            workspace_action, help=f"workspace {workspace_action}"
        )
        scopes = workspace.add_subparsers(dest="workspace_scope")
        scopes.add_parser("platform", help="select Platform")
        tenant_scope = scopes.add_parser("tenant", help="select one tenant")
        tenant_scope.add_argument("tenant_slug")
    did = resources.add_parser("did", help="manage tenant phone assignments")
    did_actions = did.add_subparsers(dest="action", required=True)
    did_actions.add_parser("show").add_argument("tenant_slug")
    assign = did_actions.add_parser("assign")
    assign.add_argument("tenant_slug")
    assign.add_argument("phone_number")
    did_actions.add_parser("remove").add_argument("tenant_slug")
    integration = resources.add_parser(
        "integration", help="manage live tenant integration connections"
    )
    integration_actions = integration.add_subparsers(dest="action", required=True)
    integration_actions.add_parser("list").add_argument("tenant_slug")
    for action in (
        "show",
        "plan",
        "configure",
        "validate",
        "enable",
        "disable",
        "rotate-credential",
        "revoke-credential",
        "delete",
    ):
        command = integration_actions.add_parser(action)
        command.add_argument("tenant_slug")
        command.add_argument("key")
    create_connection = integration_actions.add_parser("create")
    create_connection.add_argument("tenant_slug")
    create_connection.add_argument("key")
    create_connection.add_argument("--kind", choices=("http",), required=True)
    create_connection.add_argument("--endpoint")
    create_connection.add_argument("--auth", choices=("none", "api_key_header"), default="none")
    create_connection.add_argument("--auth-header", default="X-API-Key")
    create_connection.add_argument("--header", action="append", default=[])
    for action in ("plan", "configure"):
        command = integration_actions.choices[action]
        command.add_argument("--endpoint", required=True)
        command.add_argument(
            "--auth", choices=("none", "api_key_header"), default="none"
        )
        command.add_argument("--auth-header", default="X-API-Key")
        command.add_argument("--header", action="append", default=[])
        command.add_argument("--additional-allowed-host", action="append", default=[])
    rotate = integration_actions.choices["rotate-credential"]
    rotate.add_argument("--api-key")
    for resource, help_text in {
        "credential": "manage Control Plane credentials",
        "provider": "manage provider connections",
        "deployment": "manage model deployments",
        "handoff": "manage handoff destinations",
    }.items():
        managed = resources.add_parser(resource, help=help_text)
        managed_actions = {
            "credential": ("list", "show", "create", "rotate", "revoke"),
            "provider": ("list", "show", "create", "configure", "enable", "disable"),
            "deployment": ("list", "show", "create", "configure", "enable", "disable"),
            "handoff": ("list", "show", "create", "configure", "enable", "disable"),
        }[resource]
        managed.add_argument("action", choices=managed_actions)
        managed.add_argument("resource_id", nargs="?")
        managed.add_argument("--json", dest="payload")
        if resource == "credential":
            managed.add_argument("--name")
    return root


def fail(message: str, code: int) -> int:
    print(f"agentctl: {message}", file=sys.stderr)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        settings = Settings.load(
            arguments.api_url, arguments.state_dir, arguments.control_plane_url
        )
        if arguments.resource == "integration":
            run_integration(
                settings,
                arguments.action,
                arguments.tenant_slug,
                getattr(arguments, "key", None),
                kind=getattr(arguments, "kind", "http"),
                endpoint=getattr(arguments, "endpoint", None),
                auth=getattr(arguments, "auth", "none"),
                auth_header=getattr(arguments, "auth_header", "X-API-Key"),
                headers=getattr(arguments, "header", None),
                additional_allowed_hosts=getattr(
                    arguments, "additional_allowed_host", None
                ),
                api_key=getattr(arguments, "api_key", None),
            )
            return 0
        if arguments.resource == "did":
            run_did(
                settings,
                arguments.action,
                arguments.tenant_slug,
                getattr(arguments, "phone_number", None),
            )
            return 0
        if arguments.resource == "system-prompt":
            run_system_prompt(
                settings,
                arguments.action,
                revision_number=getattr(arguments, "revision_number", None),
            )
            return 0
        if arguments.resource == "runtime":
            run_platform_runtime(
                settings,
                arguments.action,
                component=getattr(arguments, "component", None),
                revision_number=getattr(arguments, "revision_number", None),
            )
            return 0
        if arguments.resource == "profile":
            run_profile(
                settings,
                arguments.action,
                getattr(arguments, "profile_key", None),
                revision_number=getattr(arguments, "revision_number", None),
            )
            return 0
        if arguments.resource in {"credential", "provider", "deployment", "handoff"}:
            run_managed(
                settings,
                arguments.resource,
                arguments.action,
                arguments.resource_id,
                arguments.payload,
                getattr(arguments, "name", None),
            )
            return 0
        if arguments.resource in {"status", "pull", "plan", "push", "publish"}:
            if arguments.workspace_scope == "platform":
                selection = WorkspaceSelection("platform")
            elif arguments.workspace_scope == "tenant":
                selection = WorkspaceSelection("tenant", arguments.tenant_slug)
            else:
                selection = WorkspaceSelection("all")
            run_workspace(settings, arguments.resource, selection)
            return 0
        if arguments.tenant_action == "create":
            run_tenant_create(
                settings,
                arguments.slug,
                arguments.display_name,
                arguments.business_type,
                arguments.status,
            )
            return 0
        if arguments.tenant_action == "show":
            run_tenant_show(settings, arguments.slug)
            return 0
        response = fetch_tenants(settings)
    except SettingsError as error:
        return fail(f"configuration error: {error}", 2)
    except CommandError as error:
        return fail(str(error), error.exit_code)
    except httpx.TransportError as error:
        return fail(f"connection failed: {error}", 3)
    except Exception as error:  # noqa: BLE001 - CLI boundary hides expected tracebacks
        return fail(f"unexpected client failure: {error}", 1)
    if response.status_code >= 400:
        try:
            detail = loads(response.content).get("detail", "backend error")
            message = detail if isinstance(detail, str) else dumps(detail)
        except UnicodeDecodeError, ValueError:
            message = response.content.decode(errors="replace")
        return fail(f"Backend API error ({response.status_code}): {message[:500]}", 5)
    if not isinstance(response.parsed, list):
        return fail("unexpected client failure: invalid Backend response", 1)
    for tenant in response.parsed:
        print(f"{tenant.slug}\t{tenant.id}\t{tenant.status.value}")
    return 0
