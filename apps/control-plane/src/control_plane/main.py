import sys
from argparse import ArgumentParser
from collections.abc import Sequence
from json import dumps, loads

import httpx

from control_plane import __version__
from control_plane.commands.prompts import (
    PromptCommandError,
    run_profile,
    run_system_prompt,
    run_tenant_prompt,
)
from control_plane.commands.tenants import fetch_tenants
from control_plane.settings import Settings, SettingsError


def parser() -> ArgumentParser:
    root = ArgumentParser(prog="agentctl")
    root.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    root.add_argument("--api-url", help="override AGENTCTL_API_URL")
    root.add_argument("--state-dir", help="override AGENTCTL_STATE_DIR")
    resources = root.add_subparsers(dest="resource", required=True)
    tenant = resources.add_parser("tenant", help="inspect tenants")
    tenant_actions = tenant.add_subparsers(dest="tenant_action", required=True)
    tenant_actions.add_parser("list", help="list tenants")
    tenant_prompt = tenant_actions.add_parser(
        "prompt", help="manage the tenant-owned TenantPrompt"
    )
    tenant_prompt_actions = tenant_prompt.add_subparsers(
        dest="tenant_prompt_action", required=True
    )
    for action in ("show", "revisions", "plan", "push", "publish"):
        command = tenant_prompt_actions.add_parser(action)
        command.add_argument("tenant_slug")
    tenant_prompt_pull = tenant_prompt_actions.add_parser("pull")
    tenant_prompt_pull.add_argument("tenant_slug")
    tenant_prompt_pull.add_argument("--force", action="store_true")

    system = resources.add_parser(
        "system-prompt", help="manage the canonical SystemPrompt"
    )
    system_actions = system.add_subparsers(dest="action", required=True)
    for action in ("show", "revisions", "plan", "push", "publish"):
        system_actions.add_parser(action)
    system_pull = system_actions.add_parser("pull")
    system_pull.add_argument("--force", action="store_true")

    profile = resources.add_parser("profile", help="manage ProfilePrompts")
    profile_actions = profile.add_subparsers(dest="action", required=True)
    profile_actions.add_parser("list")
    for action in ("create", "show", "revisions", "plan", "push", "publish"):
        command = profile_actions.add_parser(action)
        command.add_argument("profile_key")
    profile_pull = profile_actions.add_parser("pull")
    profile_pull.add_argument("profile_key")
    profile_pull.add_argument("--force", action="store_true")
    return root


def response_detail(content: bytes) -> str:
    try:
        payload = loads(content)
        detail = (
            payload.get("detail", payload) if isinstance(payload, dict) else payload
        )
        text = detail if isinstance(detail, str) else dumps(detail, ensure_ascii=False)
    except UnicodeDecodeError, ValueError:
        text = content.decode(errors="replace")
    return text.strip()[:500] or "empty response"


def fail(message: str, code: int) -> int:
    print(f"agentctl: {message}", file=sys.stderr)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        settings = Settings.load(arguments.api_url, arguments.state_dir)
        if arguments.resource == "system-prompt":
            run_system_prompt(
                settings,
                arguments.action,
                force=getattr(arguments, "force", False),
            )
            return 0
        if arguments.resource == "profile":
            run_profile(
                settings,
                arguments.action,
                getattr(arguments, "profile_key", None),
                force=getattr(arguments, "force", False),
            )
            return 0
        if arguments.resource == "tenant" and arguments.tenant_action == "prompt":
            run_tenant_prompt(
                settings,
                arguments.tenant_prompt_action,
                arguments.tenant_slug,
                force=getattr(arguments, "force", False),
            )
            return 0
        response = fetch_tenants(settings)
    except SettingsError as error:
        return fail(f"configuration error: {error}", 2)
    except PromptCommandError as error:
        return fail(str(error), error.exit_code)
    except httpx.TransportError as error:
        return fail(f"connection failed: {error}", 3)
    except Exception as error:  # noqa: BLE001 - CLI boundary hides expected tracebacks
        return fail(f"unexpected client failure: {error}", 1)

    if response.status_code in {401, 403}:
        return fail(
            f"authentication/authorization failed ({response.status_code})",
            4,
        )
    if response.status_code >= 400:
        return fail(
            f"Backend API error ({response.status_code}): "
            f"{response_detail(response.content)}",
            5,
        )
    if not isinstance(response.parsed, list):
        return fail("unexpected client failure: invalid Backend response", 1)

    if not response.parsed:
        print("No tenants.")
    for tenant in response.parsed:
        print(f"{tenant.slug}\t{tenant.id}\t{tenant.status.value}")
    return 0
