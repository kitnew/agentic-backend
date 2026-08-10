from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import Any, Literal, cast

import httpx
from admin_client import AuthenticatedClient
from admin_client.generated.api.admintenants import (
    apply_prompt_set_admin_v1_tenants_tenant_id_prompt_set_apply_post,
    get_published_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_published_get,
    plan_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_plan_post,
    plan_prompt_set_admin_v1_tenants_tenant_id_prompt_set_plan_get,
    publish_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_publish_post,
    push_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_push_post,
    show_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_get,
)
from admin_client.generated.models.knowledge_base_plan_response import (
    KnowledgeBasePlanResponse,
)
from admin_client.generated.models.knowledge_base_publish_response import (
    KnowledgeBasePublishResponse,
)
from admin_client.generated.models.knowledge_base_push_response import (
    KnowledgeBasePushResponse,
)
from admin_client.generated.models.knowledge_base_snapshot_response import (
    KnowledgeBaseSnapshotResponse,
)
from admin_client.generated.models.knowledge_base_state_response import (
    KnowledgeBaseStateResponse,
)
from admin_client.generated.models.prompt_set_apply_response import (
    PromptSetApplyResponse,
)
from admin_client.generated.models.prompt_set_plan_response import (
    PromptSetPlanResponse,
)
from admin_client.generated.models.tenant_response import TenantResponse

from control_plane.commands import knowledge, prompt_sets, prompts, tenant_configs
from control_plane.commands.prompts import PromptCommandError
from control_plane.settings import Settings

AuthoringStatus = Literal[
    "unchanged", "modified", "local-only", "draft-conflict", "error"
]


@dataclass(frozen=True)
class DesiredPrompt:
    key: str
    path: Path
    text: str
    profile: bool = False


@dataclass(frozen=True)
class DesiredConfig:
    path: Path
    config: dict[str, Any]


@dataclass(frozen=True)
class DesiredKnowledge:
    path: Path
    documents: dict[str, str]


@dataclass(frozen=True)
class DesiredTenant:
    slug: str
    path: Path
    config: DesiredConfig | None = None
    prompt: DesiredPrompt | None = None
    knowledge: DesiredKnowledge | None = None


@dataclass(frozen=True)
class DesiredState:
    root: Path
    system_prompt: DesiredPrompt | None
    profiles: tuple[DesiredPrompt, ...]
    tenants: tuple[DesiredTenant, ...]


@dataclass(frozen=True)
class SyncIssue:
    resource: str
    message: str
    exit_code: int = 2


@dataclass(frozen=True)
class ResourcePlan:
    section: str
    resource: str
    status: AuthoringStatus | str
    action: str
    details: tuple[str, ...] = ()
    error: str | None = None
    future_runtime_reconciliation: bool = False


@dataclass
class SyncReport:
    action: str
    resources: list[ResourcePlan] = field(default_factory=list)
    issues: list[SyncIssue] = field(default_factory=list)
    succeeded: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: list[SyncIssue] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    files_updated: int = 0
    rollouts: int = 0
    configs_activated: int = 0
    prompt_sets_applied: int = 0

    @property
    def exit_code(self) -> int:
        errors = [*self.issues, *self.failed]
        return max((error.exit_code for error in errors), default=0)


@dataclass(frozen=True)
class _TenantRemote:
    desired: DesiredTenant
    tenant: TenantResponse


@dataclass(frozen=True)
class _PublishTask:
    resource: str
    kind: str
    desired: DesiredPrompt | DesiredConfig | DesiredKnowledge
    tenant: TenantResponse | None
    remote: object


@dataclass(frozen=True)
class _PullWrite:
    resource: str
    kind: str
    desired: DesiredPrompt | DesiredConfig | DesiredKnowledge
    remote: object
    changed: bool


def _real_file(path: Path, label: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise PromptCommandError(f"{label} must be a real file: {path}", 2)
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise PromptCommandError(f"cannot read {label} {path}: {error}", 2) from error


def discover_desired_state(state_dir: Path) -> tuple[DesiredState, list[SyncIssue]]:
    issues: list[SyncIssue] = []
    system: DesiredPrompt | None = None
    system_path = prompts.system_prompt_path(state_dir)
    if system_path.exists() or system_path.is_symlink():
        try:
            system = DesiredPrompt(
                prompts.SYSTEM_PROMPT_KEY,
                system_path,
                _real_file(system_path, "canonical SystemPrompt"),
            )
        except PromptCommandError as error:
            issues.append(
                SyncIssue("SystemPrompt default", str(error), error.exit_code)
            )

    profiles: list[DesiredPrompt] = []
    profile_dir = state_dir / "platform" / "profiles"
    if profile_dir.exists() or profile_dir.is_symlink():
        if profile_dir.is_symlink() or not profile_dir.is_dir():
            issues.append(
                SyncIssue(
                    "ProfilePrompts",
                    f"canonical profile path must be a real directory: {profile_dir}",
                )
            )
        else:
            seen: set[str] = set()
            try:
                entries = sorted(profile_dir.iterdir(), key=lambda item: item.name)
            except OSError as error:
                issues.append(SyncIssue("ProfilePrompts", str(error)))
                entries = []
            for path in entries:
                if path.suffix != ".md":
                    continue
                key = path.stem
                resource = f"ProfilePrompt {key}"
                if not prompts.PROFILE_KEY.fullmatch(key):
                    issues.append(
                        SyncIssue(
                            resource,
                            f"profile filename must match ^[a-z][a-z0-9_]*\\.md$: {path.name}",
                        )
                    )
                    continue
                folded = key.casefold()
                if folded in seen:
                    issues.append(SyncIssue(resource, f"case-colliding profile: {key}"))
                    continue
                seen.add(folded)
                try:
                    profiles.append(
                        DesiredPrompt(
                            key,
                            path,
                            _real_file(path, "ProfilePrompt"),
                            profile=True,
                        )
                    )
                except PromptCommandError as error:
                    issues.append(SyncIssue(resource, str(error), error.exit_code))

    tenants: list[DesiredTenant] = []
    tenants_dir = state_dir / "tenants"
    if tenants_dir.exists() or tenants_dir.is_symlink():
        if tenants_dir.is_symlink() or not tenants_dir.is_dir():
            issues.append(
                SyncIssue(
                    "Tenants",
                    f"canonical tenants path must be a real directory: {tenants_dir}",
                )
            )
        else:
            seen_tenants: set[str] = set()
            try:
                entries = sorted(tenants_dir.iterdir(), key=lambda item: item.name)
            except OSError as error:
                issues.append(SyncIssue("Tenants", str(error)))
                entries = []
            for path in entries:
                if not path.is_dir() and not path.is_symlink():
                    continue
                slug = path.name
                resource = f"Tenant {slug}"
                try:
                    prompts.tenant_prompt_path(state_dir, slug)
                except PromptCommandError as error:
                    issues.append(SyncIssue(resource, str(error), error.exit_code))
                    continue
                folded = slug.casefold()
                if folded in seen_tenants:
                    issues.append(
                        SyncIssue(resource, f"case-colliding tenant path: {slug}")
                    )
                    continue
                seen_tenants.add(folded)
                if path.is_symlink():
                    issues.append(
                        SyncIssue(
                            resource, f"tenant path must be a real directory: {path}"
                        )
                    )
                    continue
                config = _discover_config(path / "tenant.yaml", slug, issues)
                prompt = _discover_tenant_prompt(
                    path / "tenant_prompt.md", slug, issues
                )
                managed_knowledge = _discover_knowledge(
                    path / "knowledge", slug, issues
                )
                tenants.append(
                    DesiredTenant(slug, path, config, prompt, managed_knowledge)
                )

    return (
        DesiredState(
            state_dir,
            system,
            tuple(sorted(profiles, key=lambda item: item.key)),
            tuple(sorted(tenants, key=lambda item: item.slug)),
        ),
        issues,
    )


def _discover_config(
    path: Path, slug: str, issues: list[SyncIssue]
) -> DesiredConfig | None:
    if not path.exists() and not path.is_symlink():
        return None
    try:
        text = _real_file(path, "TenantConfig")
        return DesiredConfig(path, tenant_configs.parse_tenant_yaml(text))
    except PromptCommandError as error:
        issues.append(SyncIssue(f"{slug} TenantConfig", str(error), error.exit_code))
        return None


def _discover_tenant_prompt(
    path: Path, slug: str, issues: list[SyncIssue]
) -> DesiredPrompt | None:
    if not path.exists() and not path.is_symlink():
        return None
    try:
        return DesiredPrompt(slug, path, _real_file(path, "TenantPrompt"))
    except PromptCommandError as error:
        issues.append(SyncIssue(f"{slug} TenantPrompt", str(error), error.exit_code))
        return None


def _discover_knowledge(
    path: Path, slug: str, issues: list[SyncIssue]
) -> DesiredKnowledge | None:
    if not path.exists() and not path.is_symlink():
        return None
    try:
        _, documents = knowledge.read_knowledge_documents(path, required=True)
        return DesiredKnowledge(path, documents)
    except PromptCommandError as error:
        issues.append(SyncIssue(f"{slug} KnowledgeBase", str(error), error.exit_code))
        return None


def _prompt_action(status: AuthoringStatus, has_draft: bool) -> str:
    if status == "unchanged":
        return "no changes"
    return "update draft" if has_draft else "create draft"


def _resolve_tenants(
    client: AuthenticatedClient, desired: DesiredState, report: SyncReport
) -> list[_TenantRemote]:
    resolved: list[_TenantRemote] = []
    for tenant in desired.tenants:
        try:
            resolved.append(_TenantRemote(tenant, prompts._tenant(client, tenant.slug)))
        except PromptCommandError as error:
            report.issues.append(
                SyncIssue(f"Tenant {tenant.slug}", str(error), error.exit_code)
            )
            if report.action != "plan":
                report.skipped.extend(_tenant_resource_names(tenant, report.action))
    return resolved


def _tenant_resource_names(tenant: DesiredTenant, action: str) -> list[str]:
    resources = []
    if tenant.config is not None:
        resources.append(f"{tenant.slug} TenantConfig")
    if tenant.prompt is not None:
        resources.append(f"{tenant.slug} TenantPrompt")
    if tenant.knowledge is not None:
        resources.append(f"{tenant.slug} KnowledgeBase")
    if action == "publish":
        resources.append(f"{tenant.slug} PromptSet")
    return resources


def build_plan(settings: Settings) -> SyncReport:
    desired, issues = discover_desired_state(settings.state_dir)
    report = SyncReport("plan", issues=issues)
    with prompts._client(settings) as client:
        profiles = _remote_profiles(client, report) if desired.profiles else set()
        if desired.system_prompt is not None:
            _plan_platform_prompt(client, desired.system_prompt, False, report)
        for profile in desired.profiles:
            if profiles is None:
                break
            _plan_platform_prompt(client, profile, profile.key in profiles, report)
        for remote in _resolve_tenants(client, desired, report):
            _plan_tenant(client, remote, report)
    return report


def _remote_profiles(
    client: AuthenticatedClient, report: SyncReport
) -> set[str] | None:
    try:
        return set(prompts._profiles(client))
    except PromptCommandError as error:
        report.issues.append(SyncIssue("ProfilePrompts", str(error), error.exit_code))
        return None


def _plan_platform_prompt(
    client: AuthenticatedClient,
    desired: DesiredPrompt,
    exists: bool,
    report: SyncReport,
) -> None:
    resource = (
        f"ProfilePrompt {desired.key}" if desired.profile else "SystemPrompt default"
    )
    try:
        target = prompts.PromptTarget(
            "Profile Prompt" if desired.profile else "System Prompt",
            desired.key,
            desired.path,
            desired.profile,
        )
        state = (
            prompts._state(client, target)
            if exists or not target.profile
            else prompts.RemoteState([], None, None)
        )
        status = cast(AuthoringStatus, prompts.plan_status(desired.text, state))
        report.resources.append(
            ResourcePlan(
                "Platform",
                resource,
                status,
                _prompt_action(status, state.draft is not None),
                (
                    "published revision: "
                    + (
                        str(state.published.revision_number)
                        if state.published
                        else "none"
                    ),
                    "draft revision: "
                    + (str(state.draft.revision_number) if state.draft else "none"),
                ),
            )
        )
    except PromptCommandError as error:
        report.resources.append(
            ResourcePlan("Platform", resource, "error", "blocked", error=str(error))
        )
        report.issues.append(SyncIssue(resource, str(error), error.exit_code))


def _plan_tenant(
    client: AuthenticatedClient, remote: _TenantRemote, report: SyncReport
) -> None:
    desired, tenant = remote.desired, remote.tenant
    future = False
    if desired.config is not None:
        resource = f"{desired.slug} TenantConfig"
        try:
            local = tenant_configs._validate(
                client,
                tenant.id,
                desired.config.config,
                tenant_configs.CURRENT_SCHEMA_VERSION,
                local=True,
            )
            config_state = tenant_configs._state(client, tenant.id)
            comparison = tenant_configs._comparison_config(
                client, tenant.id, config_state
            )
            status = cast(
                AuthoringStatus,
                tenant_configs.plan_status(local, comparison, config_state),
            )
            future = future or status != "unchanged" or config_state.draft is not None
            report.resources.append(
                ResourcePlan(
                    f"Tenant: {desired.slug}",
                    resource,
                    status,
                    _prompt_action(status, config_state.draft is not None),
                )
            )
        except PromptCommandError as error:
            _record_plan_error(report, f"Tenant: {desired.slug}", resource, error)
    if desired.prompt is not None:
        resource = f"{desired.slug} TenantPrompt"
        try:
            prompt_state = prompts._tenant_state(client, tenant.id)
            status = cast(
                AuthoringStatus,
                prompts.plan_status(desired.prompt.text, prompt_state),
            )
            future = future or status != "unchanged" or prompt_state.draft is not None
            report.resources.append(
                ResourcePlan(
                    f"Tenant: {desired.slug}",
                    resource,
                    status,
                    _prompt_action(status, prompt_state.draft is not None),
                )
            )
        except PromptCommandError as error:
            _record_plan_error(report, f"Tenant: {desired.slug}", resource, error)
    if desired.knowledge is not None:
        resource = f"{desired.slug} KnowledgeBase"
        try:
            knowledge_plan = _knowledge_plan(client, tenant, desired.knowledge)
            status = knowledge_plan.status.value
            state_response = show_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_get.sync_detailed(
                tenant.id, client=client
            )
            knowledge_state = knowledge._expect(
                state_response, KnowledgeBaseStateResponse
            )
            future = (
                future
                or status != "unchanged"
                or knowledge_state.draft_revision is not None
            )
            report.resources.append(
                ResourcePlan(
                    f"Tenant: {desired.slug}",
                    resource,
                    status,
                    "update draft" if knowledge_plan.update_draft else "no changes",
                    tuple(
                        f"{document.key}.md: {document.status.value}"
                        for document in knowledge_plan.documents
                    ),
                )
            )
        except PromptCommandError as error:
            _record_plan_error(report, f"Tenant: {desired.slug}", resource, error)
    resource = f"{desired.slug} PromptSet"
    try:
        runtime_plan = _prompt_set_plan(client, tenant)
        report.resources.append(
            ResourcePlan(
                f"Tenant: {desired.slug}",
                resource,
                runtime_plan.status.value,
                (
                    "reconciliation required after artifact publication"
                    if future
                    else "no changes"
                    if runtime_plan.status.value == "unchanged"
                    else "apply Backend PromptSet plan"
                ),
                _prompt_set_details(runtime_plan),
                future_runtime_reconciliation=future,
            )
        )
    except PromptCommandError as error:
        _record_plan_error(report, f"Tenant: {desired.slug}", resource, error)


def _record_plan_error(
    report: SyncReport, section: str, resource: str, error: PromptCommandError
) -> None:
    report.resources.append(
        ResourcePlan(section, resource, "error", "blocked", error=str(error))
    )
    report.issues.append(SyncIssue(resource, str(error), error.exit_code))


def _knowledge_plan(
    client: AuthenticatedClient, tenant: TenantResponse, desired: DesiredKnowledge
) -> KnowledgeBasePlanResponse:
    response = plan_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_plan_post.sync_detailed(
        tenant.id, client=client, body=knowledge._request(desired.documents)
    )
    return knowledge._expect(response, KnowledgeBasePlanResponse)


def _prompt_set_plan(
    client: AuthenticatedClient, tenant: TenantResponse
) -> PromptSetPlanResponse:
    response = (
        plan_prompt_set_admin_v1_tenants_tenant_id_prompt_set_plan_get.sync_detailed(
            tenant.id, client=client
        )
    )
    return prompt_sets._expect(response, PromptSetPlanResponse)


def _prompt_set_details(plan: PromptSetPlanResponse) -> tuple[str, ...]:
    components = plan.components
    details: list[str] = []
    for label, component in (
        ("SystemPrompt", components.system),
        ("ProfilePrompt", components.profile),
        ("TenantPrompt", components.tenant_prompt),
        ("KnowledgeBase", components.knowledge_base),
    ):
        before = (
            "missing"
            if component.active is None
            else prompt_sets._component(component.active)
        )
        after = prompt_sets._component(component.desired)
        details.append(
            f"{label}: {before} -> {after}"
            if component.changed
            else f"{label}: unchanged"
        )
    return tuple(details)


def push(settings: Settings) -> SyncReport:
    desired, issues = discover_desired_state(settings.state_dir)
    report = SyncReport("push", issues=issues)
    if issues:
        report.skipped.extend(_authoring_resource_names(desired))
        return report
    with prompts._client(settings) as client:
        profiles = _remote_profiles(client, report) if desired.profiles else set()
        if profiles is None:
            return report
        if desired.system_prompt is not None:
            _push_platform(client, desired.system_prompt, True, report)
        for profile in desired.profiles:
            _push_platform(client, profile, profile.key in profiles, report)
        resolved = _resolve_tenants(client, desired, report)
        by_slug = {item.desired.slug: item for item in resolved}
        for tenant in desired.tenants:
            if tenant.config is not None and tenant.slug in by_slug:
                _push_config(client, by_slug[tenant.slug], report)
        for tenant in desired.tenants:
            if tenant.prompt is not None and tenant.slug in by_slug:
                _push_tenant_prompt(client, by_slug[tenant.slug], report)
        for tenant in desired.tenants:
            if tenant.knowledge is not None and tenant.slug in by_slug:
                _push_knowledge(client, by_slug[tenant.slug], report)
    return report


def _authoring_resource_names(desired: DesiredState) -> list[str]:
    resources = []
    if desired.system_prompt is not None:
        resources.append("SystemPrompt default")
    resources.extend(f"ProfilePrompt {profile.key}" for profile in desired.profiles)
    for tenant in desired.tenants:
        resources.extend(_tenant_resource_names(tenant, "push"))
    return resources


def _attempt(report: SyncReport, resource: str, operation: Any) -> None:
    try:
        changed = bool(operation())
        (report.succeeded if changed else report.unchanged).append(resource)
    except PromptCommandError as error:
        message = str(error)
        if "changed; run plan" in message or "state changed; run plan" in message:
            message = "remote resource changed; run sync plan and retry"
        report.failed.append(SyncIssue(resource, message, error.exit_code))


def _push_platform(
    client: AuthenticatedClient,
    desired: DesiredPrompt,
    exists: bool,
    report: SyncReport,
) -> None:
    profile = desired.profile
    resource = f"ProfilePrompt {desired.key}" if profile else "SystemPrompt default"

    def operation() -> bool:
        target = prompts.PromptTarget(
            "Profile Prompt" if profile else "System Prompt",
            desired.key,
            desired.path,
            profile,
        )
        state = (
            prompts._state(client, target)
            if exists or not profile
            else prompts.RemoteState([], None, None)
        )
        if prompts.plan_status(desired.text, state) == "unchanged":
            return False
        prompts._push(client, target, state)
        return True

    _attempt(report, resource, operation)


def _push_config(
    client: AuthenticatedClient, remote: _TenantRemote, report: SyncReport
) -> None:
    desired = remote.desired.config
    assert desired is not None
    resource = f"{remote.desired.slug} TenantConfig"

    def operation() -> bool:
        local = tenant_configs._validate(
            client,
            remote.tenant.id,
            desired.config,
            tenant_configs.CURRENT_SCHEMA_VERSION,
            local=True,
        )
        state = tenant_configs._state(client, remote.tenant.id)
        if local == tenant_configs._comparison_config(client, remote.tenant.id, state):
            return False
        tenant_configs._push(client, remote.tenant, desired.path)
        return True

    _attempt(report, resource, operation)


def _push_tenant_prompt(
    client: AuthenticatedClient, remote: _TenantRemote, report: SyncReport
) -> None:
    desired = remote.desired.prompt
    assert desired is not None
    resource = f"{remote.desired.slug} TenantPrompt"

    def operation() -> bool:
        state = prompts._tenant_state(client, remote.tenant.id)
        if prompts.plan_status(desired.text, state) == "unchanged":
            return False
        target = prompts.PromptTarget(
            "Tenant Prompt", remote.desired.slug, desired.path, False
        )
        prompts._push_tenant_prompt(client, remote.tenant, target, state)
        return True

    _attempt(report, resource, operation)


def _push_knowledge(
    client: AuthenticatedClient, remote: _TenantRemote, report: SyncReport
) -> None:
    desired = remote.desired.knowledge
    assert desired is not None
    resource = f"{remote.desired.slug} KnowledgeBase"

    def operation() -> bool:
        plan = _knowledge_plan(client, remote.tenant, desired)
        if plan.status.value == "unchanged":
            return False
        response = push_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_push_post.sync_detailed(
            remote.tenant.id,
            client=client,
            body=knowledge._request(desired.documents),
            if_match=f'"{plan.base_version}"',
        )
        if response.status_code in {
            HTTPStatus.CONFLICT,
            HTTPStatus.PRECONDITION_FAILED,
        }:
            raise PromptCommandError(
                "remote KnowledgeBase draft changed; run sync plan and retry", 5
            )
        result = knowledge._expect(response, KnowledgeBasePushResponse)
        return bool(result.changed)

    _attempt(report, resource, operation)


def publish(settings: Settings) -> SyncReport:
    desired, issues = discover_desired_state(settings.state_dir)
    report = SyncReport("publish", issues=issues)
    if issues:
        report.skipped.extend(
            [
                *_authoring_resource_names(desired),
                *(f"{tenant.slug} PromptSet" for tenant in desired.tenants),
            ]
        )
        return report
    tasks: list[_PublishTask] = []
    tenants: list[_TenantRemote] = []
    with prompts._client(settings) as client:
        _publish_preflight(client, desired, report, tasks, tenants)
        if report.issues:
            report.skipped.extend(task.resource for task in tasks)
            report.skipped.extend(f"{item.desired.slug} PromptSet" for item in tenants)
            return report
        failed_tenants: set[str] = set()
        platform_failed = False
        for index, task in enumerate(tasks):
            try:
                _execute_publish_task(client, task, report)
            except httpx.TransportError:
                report.pending.extend(item.resource for item in tasks[index + 1 :])
                report.pending.extend(
                    f"{item.desired.slug} PromptSet" for item in tenants
                )
                raise
            except PromptCommandError as error:
                report.failed.append(
                    SyncIssue(task.resource, str(error), error.exit_code)
                )
                if task.tenant is None:
                    platform_failed = True
                else:
                    failed_tenants.add(task.tenant.slug)
        for remote in tenants:
            resource = f"{remote.desired.slug} PromptSet"
            if platform_failed or remote.desired.slug in failed_tenants:
                report.pending.append(resource)
                continue
            try:
                plan = _prompt_set_plan(client, remote.tenant)
                if plan.status.value == "unchanged":
                    report.unchanged.append(resource)
                    continue
                response = apply_prompt_set_admin_v1_tenants_tenant_id_prompt_set_apply_post.sync_detailed(
                    remote.tenant.id, client=client
                )
                result = prompt_sets._expect(response, PromptSetApplyResponse)
                if result.changed:
                    report.succeeded.append(resource)
                    report.prompt_sets_applied += 1
                else:
                    report.unchanged.append(resource)
            except PromptCommandError as error:
                report.failed.append(SyncIssue(resource, str(error), error.exit_code))
    return report


def _publish_preflight(
    client: AuthenticatedClient,
    desired: DesiredState,
    report: SyncReport,
    tasks: list[_PublishTask],
    tenants: list[_TenantRemote],
) -> None:
    profiles = _remote_profiles(client, report) if desired.profiles else set()
    if profiles is None:
        return
    if desired.system_prompt is not None:
        _preflight_platform_prompt(client, desired.system_prompt, True, report, tasks)
    for profile in desired.profiles:
        _preflight_platform_prompt(
            client, profile, profile.key in profiles, report, tasks
        )
    platform_changes = bool(tasks)
    tenants.extend(_resolve_tenants(client, desired, report))
    for remote in tenants:
        before = len(tasks)
        _preflight_tenant(client, remote, report, tasks)
        try:
            _prompt_set_plan(client, remote.tenant)
        except PromptCommandError as error:
            if not platform_changes and len(tasks) == before:
                report.issues.append(
                    SyncIssue(
                        f"{remote.desired.slug} PromptSet",
                        str(error),
                        error.exit_code,
                    )
                )


def _preflight_platform_prompt(
    client: AuthenticatedClient,
    desired: DesiredPrompt,
    exists: bool,
    report: SyncReport,
    tasks: list[_PublishTask],
) -> None:
    profile = desired.profile
    resource = f"ProfilePrompt {desired.key}" if profile else "SystemPrompt default"
    if profile and not exists:
        report.issues.append(
            SyncIssue(
                resource, "local state has not been pushed; run agentctl sync push", 5
            )
        )
        return
    try:
        target = prompts.PromptTarget(
            "Profile Prompt" if profile else "System Prompt",
            desired.key,
            desired.path,
            profile,
        )
        state = prompts._state(client, target)
        if state.draft is not None and prompts.content_matches(
            desired.text, state.draft.text
        ):
            tasks.append(
                _PublishTask(resource, "platform", desired, None, (target, state))
            )
        elif (
            state.draft is None
            and state.published is not None
            and prompts.content_matches(desired.text, state.published.text)
        ):
            report.unchanged.append(resource)
        else:
            report.issues.append(
                SyncIssue(
                    resource,
                    "local state does not match the remote draft; run agentctl sync plan and agentctl sync push",
                    5,
                )
            )
    except PromptCommandError as error:
        report.issues.append(SyncIssue(resource, str(error), error.exit_code))


def _preflight_tenant(
    client: AuthenticatedClient,
    remote: _TenantRemote,
    report: SyncReport,
    tasks: list[_PublishTask],
) -> None:
    desired, tenant = remote.desired, remote.tenant
    if desired.config is not None:
        resource = f"{desired.slug} TenantConfig"
        try:
            local = tenant_configs._validate(
                client,
                tenant.id,
                desired.config.config,
                tenant_configs.CURRENT_SCHEMA_VERSION,
                local=True,
            )
            config_state = tenant_configs._state(client, tenant.id)
            comparison = tenant_configs._comparison_config(
                client, tenant.id, config_state
            )
            if config_state.draft is not None and local == comparison:
                tenant_configs._validate_saved_draft(
                    client, tenant.id, config_state.draft.id
                )
                tasks.append(
                    _PublishTask(
                        resource, "config", desired.config, tenant, config_state
                    )
                )
            elif (
                config_state.draft is None
                and config_state.active is not None
                and local == comparison
            ):
                report.unchanged.append(resource)
            else:
                _draft_mismatch(report, resource)
        except PromptCommandError as error:
            report.issues.append(SyncIssue(resource, str(error), error.exit_code))
    if desired.prompt is not None:
        resource = f"{desired.slug} TenantPrompt"
        try:
            prompt_state = prompts._tenant_state(client, tenant.id)
            if prompt_state.draft is not None and prompts.content_matches(
                desired.prompt.text, prompt_state.draft.text
            ):
                tasks.append(
                    _PublishTask(
                        resource,
                        "tenant-prompt",
                        desired.prompt,
                        tenant,
                        prompt_state,
                    )
                )
            elif (
                prompt_state.draft is None
                and prompt_state.published is not None
                and prompts.content_matches(
                    desired.prompt.text, prompt_state.published.text
                )
            ):
                report.unchanged.append(resource)
            else:
                _draft_mismatch(report, resource)
        except PromptCommandError as error:
            report.issues.append(SyncIssue(resource, str(error), error.exit_code))
    if desired.knowledge is not None:
        resource = f"{desired.slug} KnowledgeBase"
        try:
            knowledge_plan = _knowledge_plan(client, tenant, desired.knowledge)
            state_response = show_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_get.sync_detailed(
                tenant.id, client=client
            )
            knowledge_state = knowledge._expect(
                state_response, KnowledgeBaseStateResponse
            )
            if knowledge_plan.status.value != "unchanged":
                _draft_mismatch(report, resource)
            elif knowledge_state.draft_revision is not None:
                tasks.append(
                    _PublishTask(
                        resource,
                        "knowledge",
                        desired.knowledge,
                        tenant,
                        knowledge_state,
                    )
                )
            elif knowledge_state.latest_published_revision is not None:
                report.unchanged.append(resource)
            else:
                _draft_mismatch(report, resource)
        except PromptCommandError as error:
            report.issues.append(SyncIssue(resource, str(error), error.exit_code))


def _draft_mismatch(report: SyncReport, resource: str) -> None:
    report.issues.append(
        SyncIssue(
            resource,
            "local state does not match the remote draft; run agentctl sync plan and agentctl sync push",
            5,
        )
    )


def _execute_publish_task(
    client: AuthenticatedClient, task: _PublishTask, report: SyncReport
) -> None:
    if task.kind == "platform":
        target, prompt_state = cast(
            tuple[prompts.PromptTarget, prompts.RemoteState], task.remote
        )
        prompts._publish(client, target, prompt_state)
        report.rollouts += 1
    elif task.kind == "config":
        assert task.tenant is not None
        tenant_configs._publish(
            client, task.tenant, cast(tenant_configs.ConfigState, task.remote)
        )
        report.configs_activated += 1
    elif task.kind == "tenant-prompt":
        assert task.tenant is not None and isinstance(task.desired, DesiredPrompt)
        target = prompts.PromptTarget(
            "Tenant Prompt", task.tenant.slug, task.desired.path, False
        )
        prompts._publish_tenant_prompt(
            client,
            task.tenant,
            target,
            cast(prompts.RemoteState, task.remote),
        )
    else:
        assert task.tenant is not None
        response = publish_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_publish_post.sync_detailed(
            task.tenant.id, client=client
        )
        knowledge._expect(response, KnowledgeBasePublishResponse)
    report.succeeded.append(task.resource)


def pull(settings: Settings, *, force: bool) -> SyncReport:
    desired, issues = discover_desired_state(settings.state_dir)
    report = SyncReport("pull", issues=issues)
    if issues:
        report.skipped.extend(_authoring_resource_names(desired))
        return report
    writes: list[_PullWrite] = []
    with prompts._client(settings) as client:
        profiles = _remote_profiles(client, report) if desired.profiles else set()
        if profiles is None:
            return report
        if desired.system_prompt is not None:
            _preflight_pull_prompt(client, desired.system_prompt, True, report, writes)
        for profile in desired.profiles:
            _preflight_pull_prompt(
                client, profile, profile.key in profiles, report, writes
            )
        for remote in _resolve_tenants(client, desired, report):
            _preflight_pull_tenant(client, remote, report, writes)
        conflicts = [item for item in writes if item.changed]
        if conflicts and not force:
            report.unchanged.extend(
                item.resource for item in writes if not item.changed
            )
            report.issues.extend(
                SyncIssue(
                    item.resource,
                    "local state differs from remote published state; use --force to overwrite",
                    2,
                )
                for item in conflicts
            )
            return report
        if report.issues:
            return report
        for index, item in enumerate(writes):
            if not item.changed:
                report.unchanged.append(item.resource)
                continue
            try:
                _write_pull(item)
                report.succeeded.append(item.resource)
                report.files_updated += _updated_file_count(item)
            except PromptCommandError as error:
                report.failed.append(
                    SyncIssue(item.resource, str(error), error.exit_code)
                )
                report.pending.extend(
                    pending.resource
                    for pending in writes[index + 1 :]
                    if pending.changed
                )
                break
    return report


def _preflight_pull_prompt(
    client: AuthenticatedClient,
    desired: DesiredPrompt,
    exists: bool,
    report: SyncReport,
    writes: list[_PullWrite],
) -> None:
    profile = desired.profile
    resource = f"ProfilePrompt {desired.key}" if profile else "SystemPrompt default"
    if profile and not exists:
        report.issues.append(SyncIssue(resource, f"unknown profile: {desired.key}", 5))
        return
    try:
        target = prompts.PromptTarget(
            "Profile Prompt" if profile else "System Prompt",
            desired.key,
            desired.path,
            profile,
        )
        state = prompts._state(client, target)
        if state.published is None:
            raise PromptCommandError(f"{resource} has no published revision")
        writes.append(
            _PullWrite(
                resource,
                "prompt",
                desired,
                state.published.text,
                not prompts.content_matches(desired.text, state.published.text),
            )
        )
    except PromptCommandError as error:
        report.issues.append(SyncIssue(resource, str(error), error.exit_code))


def _preflight_pull_tenant(
    client: AuthenticatedClient,
    remote: _TenantRemote,
    report: SyncReport,
    writes: list[_PullWrite],
) -> None:
    desired, tenant = remote.desired, remote.tenant
    if desired.config is not None:
        resource = f"{desired.slug} TenantConfig"
        try:
            config_state = tenant_configs._state(client, tenant.id)
            active = tenant_configs._active_config(config_state)
            writes.append(
                _PullWrite(
                    resource,
                    "config",
                    desired.config,
                    active,
                    tenant_configs.canonical_config(desired.config.config) != active,
                )
            )
        except PromptCommandError as error:
            report.issues.append(SyncIssue(resource, str(error), error.exit_code))
    if desired.prompt is not None:
        resource = f"{desired.slug} TenantPrompt"
        try:
            prompt_state = prompts._tenant_state(client, tenant.id)
            if prompt_state.published is None:
                raise PromptCommandError(f"{resource} has no published revision")
            writes.append(
                _PullWrite(
                    resource,
                    "prompt",
                    desired.prompt,
                    prompt_state.published.text,
                    not prompts.content_matches(
                        desired.prompt.text, prompt_state.published.text
                    ),
                )
            )
        except PromptCommandError as error:
            report.issues.append(SyncIssue(resource, str(error), error.exit_code))
    if desired.knowledge is not None:
        resource = f"{desired.slug} KnowledgeBase"
        try:
            response = get_published_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_published_get.sync_detailed(
                tenant.id, client=client
            )
            snapshot = knowledge._expect(response, KnowledgeBaseSnapshotResponse)
            remote_documents = {
                document.key: document.content for document in snapshot.documents
            }
            same = (
                desired.knowledge.documents.keys() == remote_documents.keys()
                and all(
                    prompts.content_matches(
                        desired.knowledge.documents[key], remote_documents[key]
                    )
                    for key in desired.knowledge.documents
                )
            )
            writes.append(
                _PullWrite(
                    resource,
                    "knowledge",
                    desired.knowledge,
                    snapshot,
                    not same,
                )
            )
        except PromptCommandError as error:
            report.issues.append(SyncIssue(resource, str(error), error.exit_code))


def _write_pull(item: _PullWrite) -> None:
    if item.kind == "prompt":
        assert isinstance(item.desired, DesiredPrompt) and isinstance(item.remote, str)
        try:
            item.desired.path.write_bytes(item.remote.encode("utf-8"))
        except OSError as error:
            raise PromptCommandError(
                f"cannot write canonical prompt file {item.desired.path}: {error}", 2
            ) from error
    elif item.kind == "config":
        assert isinstance(item.desired, DesiredConfig) and isinstance(item.remote, dict)
        tenant_configs._write(
            item.desired.path, tenant_configs.serialize_tenant_yaml(item.remote)
        )
    else:
        assert isinstance(item.desired, DesiredKnowledge)
        assert isinstance(item.remote, KnowledgeBaseSnapshotResponse)
        knowledge._pull(item.desired.path, item.remote, force=True)


def _updated_file_count(item: _PullWrite) -> int:
    if item.kind != "knowledge":
        return 1
    assert isinstance(item.desired, DesiredKnowledge)
    assert isinstance(item.remote, KnowledgeBaseSnapshotResponse)
    remote = {document.key: document.content for document in item.remote.documents}
    return len(item.desired.documents.keys() ^ remote.keys()) + sum(
        key in item.desired.documents
        and not prompts.content_matches(item.desired.documents[key], content)
        for key, content in remote.items()
    )


def run_sync(settings: Settings, action: str, *, force: bool = False) -> int:
    if action == "plan":
        report = build_plan(settings)
        _render_plan(report)
    elif action == "push":
        print("Desired State Push")
        report = push(settings)
        _render_execution(report)
        print("\nNo runtime state was changed.")
    elif action == "publish":
        print("Desired State Publish")
        report = publish(settings)
        _render_execution(report)
    elif action == "pull":
        print("Desired State Pull")
        report = pull(settings, force=force)
        _render_execution(report)
    else:
        raise PromptCommandError(f"unsupported sync action: {action}", 2)
    return report.exit_code


def _render_plan(report: SyncReport) -> None:
    print("Desired State Plan")
    section = ""
    for item in report.resources:
        if item.section != section:
            section = item.section
            print(f"\n{section}")
        print(f"\n{item.resource}\n  status: {item.status}")
        for detail in item.details:
            print(f"  {detail}")
        print(f"  Plan: {item.action}")
        if item.error:
            print(f"  Error: {item.error}")
    if report.issues:
        print("\nBlocking errors:")
        for issue in report.issues:
            print(f"  {issue.resource}: {issue.message}")
    authoring = sum(
        item.status not in {"unchanged", "error"}
        for item in report.resources
        if not item.resource.endswith("PromptSet")
    )
    runtime = sum(
        item.status not in {"unchanged", "error"} or item.future_runtime_reconciliation
        for item in report.resources
        if item.resource.endswith("PromptSet")
    )
    unchanged = sum(item.status == "unchanged" for item in report.resources)
    print(
        "\nSummary:\n"
        f"  managed resources: {len(report.resources)}\n"
        f"  unchanged: {unchanged}\n"
        f"  authoring changes: {authoring}\n"
        f"  runtime reconciliations: {runtime}\n"
        f"  blocking errors: {len(report.issues)}"
    )


def _render_execution(report: SyncReport) -> None:
    if report.succeeded:
        print("\nSucceeded:")
        for resource in report.succeeded:
            print(f"  {resource}")
    if report.unchanged:
        print("\nUnchanged:")
        for resource in report.unchanged:
            print(f"  {resource}")
    failures = [*report.issues, *report.failed]
    if failures:
        print("\nFailed:")
        for issue in failures:
            print(f"  {issue.resource}: {issue.message}")
    if report.skipped:
        print("\nSkipped:")
        for resource in report.skipped:
            print(f"  {resource}")
    if report.pending:
        print("\nPending:")
        for resource in report.pending:
            print(f"  {resource}")
    if report.action == "push":
        print(
            "\nSummary:\n"
            f"  drafts updated: {len(report.succeeded)}\n"
            f"  unchanged: {len(report.unchanged)}\n"
            f"  failed: {len(failures)}"
        )
    elif report.action == "publish":
        artifacts = (
            len(report.succeeded)
            - report.configs_activated
            - report.prompt_sets_applied
        )
        print(
            "\nSummary:\n"
            f"  artifacts published: {artifacts}\n"
            f"  configs activated: {report.configs_activated}\n"
            f"  platform rollouts completed: {report.rollouts}\n"
            f"  PromptSets applied: {report.prompt_sets_applied}\n"
            f"  unchanged: {len(report.unchanged)}\n"
            f"  failed: {len(failures)}"
        )
    else:
        print(
            "\nSummary:\n"
            f"  files updated: {report.files_updated}\n"
            f"  unchanged: {len(report.unchanged)}\n"
            f"  conflicts: {len(failures)}"
        )
