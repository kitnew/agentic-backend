import sys
from argparse import ArgumentParser
from collections.abc import Sequence
from json import dumps, loads

import httpx

from control_plane import __version__
from control_plane.commands.components import run_tenant_components
from control_plane.commands.errors import CommandError
from control_plane.commands.integrations import run_integration
from control_plane.commands.platform import (
    run_platform_runtime,
    run_profile,
    run_sync,
    run_system_prompt,
)
from control_plane.commands.tenants import (
    fetch_tenants,
    run_tenant_create,
    run_tenant_show,
)
from control_plane.settings import Settings, SettingsError


def parser() -> ArgumentParser:
    root = ArgumentParser(prog="agentctl")
    root.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    root.add_argument("--api-url", help="override AGENTCTL_API_URL")
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
    create.add_argument("--status", choices=("active", "suspended", "archived"), default="active")
    config = actions.add_parser("config", help="manage tenant component drafts from tenant.yaml")
    config_actions = config.add_subparsers(dest="tenant_config_action", required=True)
    for action in ("show", "push", "publish"):
        config_actions.add_parser(action).add_argument("tenant_slug")
    system = resources.add_parser("system-prompt", help="manage the platform System Prompt")
    system_actions = system.add_subparsers(dest="action", required=True)
    for action in ("show", "revisions", "plan", "push", "publish"):
        system_actions.add_parser(action)
    pull = system_actions.add_parser("pull")
    pull.add_argument("--force", action="store_true")
    runtime = resources.add_parser("runtime", help="manage the platform Runtime policy")
    runtime_actions = runtime.add_subparsers(dest="action", required=True)
    for action in ("show", "revisions", "plan", "push", "publish"):
        runtime_actions.add_parser(action)
    pull = runtime_actions.add_parser("pull")
    pull.add_argument("--force", action="store_true")
    profile = resources.add_parser("profile", help="manage platform Profile Prompts")
    profile_actions = profile.add_subparsers(dest="action", required=True)
    profile_actions.add_parser("list")
    for action in ("create", "show", "revisions", "plan", "push", "publish"):
        command = profile_actions.add_parser(action)
        command.add_argument("profile_key")
    pull = profile_actions.add_parser("pull")
    pull.add_argument("profile_key")
    pull.add_argument("--force", action="store_true")
    sync = resources.add_parser("sync", help="reconcile Git-managed component authoring")
    sync_actions = sync.add_subparsers(dest="action", required=True)
    for action in ("plan", "push", "publish"):
        sync_actions.add_parser(action)
    sync_pull = sync_actions.add_parser("pull")
    sync_pull.add_argument("--force", action="store_true")
    integration = resources.add_parser("integration", help="manage tenant integration connection metadata")
    integration_actions = integration.add_subparsers(dest="action", required=True)
    integration_actions.add_parser("list").add_argument("tenant_slug")
    for action in ("show", "delete"):
        command = integration_actions.add_parser(action)
        command.add_argument("tenant_slug")
        command.add_argument("key")
    create_connection = integration_actions.add_parser("create")
    create_connection.add_argument("tenant_slug")
    create_connection.add_argument("key")
    create_connection.add_argument("--provider", choices=("managed_webhook", "google_sheets"), required=True)
    create_connection.add_argument("--config-json", default="{}")
    configure = integration_actions.add_parser("configure")
    configure.add_argument("tenant_slug")
    configure.add_argument("key")
    configure.add_argument("--config-json", required=True)
    for action in ("set-secret", "rotate-secret", "test", "enable", "disable"):
        command = integration_actions.add_parser(action)
        command.add_argument("tenant_slug")
        command.add_argument("key")
    return root


def fail(message: str, code: int) -> int:
    print(f"agentctl: {message}", file=sys.stderr)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        settings = Settings.load(arguments.api_url, arguments.state_dir)
        if arguments.resource == "integration":
            run_integration(settings, arguments.action, arguments.tenant_slug, getattr(arguments, "key", None), provider=getattr(arguments, "provider", None), config_json=getattr(arguments, "config_json", None))
            return 0
        if arguments.resource == "system-prompt":
            run_system_prompt(settings, arguments.action, force=getattr(arguments, "force", False))
            return 0
        if arguments.resource == "runtime":
            run_platform_runtime(settings, arguments.action, force=getattr(arguments, "force", False))
            return 0
        if arguments.resource == "profile":
            run_profile(settings, arguments.action, getattr(arguments, "profile_key", None), force=getattr(arguments, "force", False))
            return 0
        if arguments.resource == "sync":
            run_sync(settings, arguments.action, force=getattr(arguments, "force", False))
            return 0
        if arguments.tenant_action == "create":
            run_tenant_create(settings, arguments.slug, arguments.display_name, arguments.business_type, arguments.status)
            return 0
        if arguments.tenant_action == "show":
            run_tenant_show(settings, arguments.slug)
            return 0
        if arguments.tenant_action == "config":
            run_tenant_components(settings, arguments.tenant_config_action, arguments.tenant_slug)
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
        except (UnicodeDecodeError, ValueError):
            message = response.content.decode(errors="replace")
        return fail(f"Backend API error ({response.status_code}): {message[:500]}", 5)
    if not isinstance(response.parsed, list):
        return fail("unexpected client failure: invalid Backend response", 1)
    for tenant in response.parsed:
        print(f"{tenant.slug}\t{tenant.id}\t{tenant.status.value}")
    return 0
