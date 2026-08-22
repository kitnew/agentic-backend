import sys
from argparse import ArgumentParser
from collections.abc import Sequence
from json import dumps, loads

import httpx

from control_plane import __version__
from control_plane.commands.integrations import run_integration
from control_plane.commands.knowledge import run_tenant_knowledge
from control_plane.commands.prompt_sets import run_tenant_prompt_set
from control_plane.commands.prompts import (
    PromptCommandError,
    run_profile,
    run_system_prompt,
    run_tenant_prompt,
)
from control_plane.commands.runtimes import run_platform_runtime, run_tenant_runtime
from control_plane.commands.sync import run_sync
from control_plane.commands.telephony import run_tenant_telephony
from control_plane.commands.tenant_configs import run_tenant_config
from control_plane.commands.tenants import fetch_tenants, run_tenant_create
from control_plane.commands.voice_runtimes import run_tenant_voice_runtime
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
    tenant_create = tenant_actions.add_parser("create", help="create a tenant")
    tenant_create.add_argument("slug")
    tenant_create.add_argument("--display-name", required=True)
    tenant_create.add_argument("--business-type", required=True)
    tenant_create.add_argument(
        "--status",
        choices=("active", "suspended", "archived"),
        default="active",
    )
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
    tenant_runtime = tenant_actions.add_parser(
        "runtime", help="manage the tenant-owned runtime override"
    )
    tenant_runtime_actions = tenant_runtime.add_subparsers(
        dest="tenant_runtime_action", required=True
    )
    for action in ("show", "revisions", "plan", "push", "publish"):
        command = tenant_runtime_actions.add_parser(action)
        command.add_argument("tenant_slug")
    tenant_runtime_pull = tenant_runtime_actions.add_parser("pull")
    tenant_runtime_pull.add_argument("tenant_slug")
    tenant_runtime_pull.add_argument("--force", action="store_true")
    tenant_voice_runtime = tenant_actions.add_parser(
        "voice-runtime", help="inspect and reconcile the derived VoiceRuntime"
    )
    tenant_voice_runtime_actions = tenant_voice_runtime.add_subparsers(
        dest="tenant_voice_runtime_action", required=True
    )
    for action in ("show", "revisions", "plan", "apply"):
        command = tenant_voice_runtime_actions.add_parser(action)
        command.add_argument("tenant_slug")
    tenant_config = tenant_actions.add_parser(
        "config", help="manage the tenant-owned TenantConfig"
    )
    tenant_config_actions = tenant_config.add_subparsers(
        dest="tenant_config_action", required=True
    )
    for action in ("show", "revisions", "plan", "push", "publish"):
        command = tenant_config_actions.add_parser(action)
        command.add_argument("tenant_slug")
    tenant_config_pull = tenant_config_actions.add_parser("pull")
    tenant_config_pull.add_argument("tenant_slug")
    tenant_config_pull.add_argument("--force", action="store_true")
    telephony = tenant_actions.add_parser("telephony", help="manage Tenant Telephony")
    telephony_actions = telephony.add_subparsers(dest="telephony_action", required=True)
    for action in ("show", "status"):
        telephony_actions.add_parser(action).add_argument("tenant_slug")
    set_number = telephony_actions.add_parser("set-number")
    set_number.add_argument("tenant_slug")
    set_number.add_argument("e164_number")
    handoff = telephony_actions.add_parser("handoff")
    handoff_actions = handoff.add_subparsers(dest="handoff_action", required=True)
    handoff_set = handoff_actions.add_parser("set")
    handoff_set.add_argument("tenant_slug")
    handoff_set.add_argument("destination")
    handoff_set.add_argument("e164_number")
    handoff_set.add_argument("--label")
    handoff_remove = handoff_actions.add_parser("remove")
    handoff_remove.add_argument("tenant_slug")
    handoff_remove.add_argument("destination")
    tenant_prompt_set = tenant_actions.add_parser(
        "prompt-set", help="inspect and reconcile the derived PromptSet"
    )
    tenant_prompt_set_actions = tenant_prompt_set.add_subparsers(
        dest="tenant_prompt_set_action", required=True
    )
    for action in ("show", "revisions", "plan", "apply"):
        command = tenant_prompt_set_actions.add_parser(action)
        command.add_argument("tenant_slug")
    tenant_knowledge = tenant_actions.add_parser(
        "knowledge", help="manage the tenant-owned KnowledgeBase"
    )
    tenant_knowledge_actions = tenant_knowledge.add_subparsers(
        dest="tenant_knowledge_action", required=True
    )
    for action in ("show", "revisions", "plan", "push", "publish"):
        command = tenant_knowledge_actions.add_parser(action)
        command.add_argument("tenant_slug")
    tenant_knowledge_pull = tenant_knowledge_actions.add_parser("pull")
    tenant_knowledge_pull.add_argument("tenant_slug")
    tenant_knowledge_pull.add_argument("--force", action="store_true")

    system = resources.add_parser(
        "system-prompt", help="manage the canonical SystemPrompt"
    )
    system_actions = system.add_subparsers(dest="action", required=True)
    for action in ("show", "revisions", "plan", "push", "publish"):
        system_actions.add_parser(action)
    system_pull = system_actions.add_parser("pull")
    system_pull.add_argument("--force", action="store_true")

    runtime = resources.add_parser(
        "runtime", help="manage the canonical Platform Runtime policy"
    )
    runtime_actions = runtime.add_subparsers(dest="action", required=True)
    for action in ("show", "revisions", "plan", "push", "publish"):
        runtime_actions.add_parser(action)
    runtime_pull = runtime_actions.add_parser("pull")
    runtime_pull.add_argument("--force", action="store_true")

    profile = resources.add_parser("profile", help="manage ProfilePrompts")
    profile_actions = profile.add_subparsers(dest="action", required=True)
    profile_actions.add_parser("list")
    for action in ("create", "show", "revisions", "plan", "push", "publish"):
        command = profile_actions.add_parser(action)
        command.add_argument("profile_key")
    profile_pull = profile_actions.add_parser("pull")
    profile_pull.add_argument("profile_key")
    profile_pull.add_argument("--force", action="store_true")
    sync = resources.add_parser("sync", help="reconcile repository desired state")
    sync_actions = sync.add_subparsers(dest="action", required=True)
    for action in ("plan", "push", "publish"):
        sync_actions.add_parser(action)
    sync_pull = sync_actions.add_parser("pull")
    sync_pull.add_argument("--force", action="store_true")
    integration = resources.add_parser(
        "integration", help="manage tenant integration connection metadata"
    )
    integration_actions = integration.add_subparsers(dest="action", required=True)
    integration_list = integration_actions.add_parser("list")
    integration_list.add_argument("tenant_slug")
    for action in ("show", "delete"):
        command = integration_actions.add_parser(action)
        command.add_argument("tenant_slug")
        command.add_argument("key")
    integration_create = integration_actions.add_parser("create")
    integration_create.add_argument("tenant_slug")
    integration_create.add_argument("key")
    integration_create.add_argument(
        "--provider",
        choices=("managed_webhook", "google_sheets"),
        required=True,
    )
    integration_create.add_argument("--config-json", default="{}")
    integration_configure = integration_actions.add_parser("configure")
    integration_configure.add_argument("tenant_slug")
    integration_configure.add_argument("key")
    integration_configure.add_argument("--config-json", required=True)
    for action in ("set-secret", "rotate-secret", "test", "enable", "disable"):
        command = integration_actions.add_parser(action)
        command.add_argument("tenant_slug")
        command.add_argument("key")
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
        if arguments.resource == "sync":
            return run_sync(
                settings,
                arguments.action,
                force=getattr(arguments, "force", False),
            )
        if arguments.resource == "system-prompt":
            run_system_prompt(
                settings,
                arguments.action,
                force=getattr(arguments, "force", False),
            )
            return 0
        if arguments.resource == "runtime":
            run_platform_runtime(
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
        if arguments.resource == "integration":
            run_integration(
                settings,
                arguments.action,
                arguments.tenant_slug,
                getattr(arguments, "key", None),
                provider=getattr(arguments, "provider", None),
                config_json=getattr(arguments, "config_json", None),
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
        if arguments.resource == "tenant" and arguments.tenant_action == "create":
            run_tenant_create(
                settings,
                arguments.slug,
                arguments.display_name,
                arguments.business_type,
                arguments.status,
            )
            return 0
        if arguments.resource == "tenant" and arguments.tenant_action == "config":
            run_tenant_config(
                settings,
                arguments.tenant_config_action,
                arguments.tenant_slug,
                force=getattr(arguments, "force", False),
            )
            return 0
        if arguments.resource == "tenant" and arguments.tenant_action == "telephony":
            action = arguments.telephony_action
            run_tenant_telephony(
                settings,
                f"handoff-{arguments.handoff_action}" if action == "handoff" else action,
                arguments.tenant_slug,
                number=getattr(arguments, "e164_number", None),
                destination=getattr(arguments, "destination", None),
                label=getattr(arguments, "label", None),
            )
            return 0
        if arguments.resource == "tenant" and arguments.tenant_action == "runtime":
            run_tenant_runtime(
                settings,
                arguments.tenant_runtime_action,
                arguments.tenant_slug,
                force=getattr(arguments, "force", False),
            )
            return 0
        if (
            arguments.resource == "tenant"
            and arguments.tenant_action == "voice-runtime"
        ):
            run_tenant_voice_runtime(
                settings,
                arguments.tenant_voice_runtime_action,
                arguments.tenant_slug,
            )
            return 0
        if arguments.resource == "tenant" and arguments.tenant_action == "knowledge":
            run_tenant_knowledge(
                settings,
                arguments.tenant_knowledge_action,
                arguments.tenant_slug,
                force=getattr(arguments, "force", False),
            )
            return 0
        if arguments.resource == "tenant" and arguments.tenant_action == "prompt-set":
            run_tenant_prompt_set(
                settings,
                arguments.tenant_prompt_set_action,
                arguments.tenant_slug,
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
