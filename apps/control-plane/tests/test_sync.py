from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from admin_client.generated.models.tenant_response import TenantResponse
from control_plane import main as cli
from control_plane.commands import sync
from control_plane.settings import Settings


def settings(path: Path) -> Settings:
    return Settings("https://backend.example", "secret", path)


def test_state_dir_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    monkeypatch.delenv("AGENTCTL_STATE_DIR", raising=False)
    assert Settings.load().state_dir == Path("control-plane")

    environment = tmp_path / "environment"
    monkeypatch.setenv("AGENTCTL_STATE_DIR", str(environment))
    assert Settings.load().state_dir == environment
    assert Settings.load(state_dir=str(tmp_path / "explicit")).state_dir == (
        tmp_path / "explicit"
    )


def test_sync_cli_tree_and_force(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    seen: list[tuple[str, bool]] = []

    def run(settings: Settings, action: str, *, force: bool = False) -> int:
        seen.append((action, force))
        return 0

    monkeypatch.setattr(cli, "run_sync", run)

    for action in ("plan", "push", "publish"):
        assert cli.main(["sync", action]) == 0
    assert cli.main(["sync", "pull", "--force"]) == 0
    assert seen == [
        ("plan", False),
        ("push", False),
        ("publish", False),
        ("pull", True),
    ]


def test_discovery_managed_presence_absence_and_sorting(tmp_path: Path) -> None:
    (tmp_path / "platform" / "profiles").mkdir(parents=True)
    (tmp_path / "platform" / "system_prompt.md").write_text("system")
    (tmp_path / "platform" / "profiles" / "zulu.md").write_text("z")
    (tmp_path / "platform" / "profiles" / "alpha.md").write_text("a")
    (tmp_path / "platform" / "profiles" / "default.md").write_text("profile")
    (tmp_path / "platform" / "profiles" / "README.txt").write_text("ignored")

    beta = tmp_path / "tenants" / "beta-hotel"
    alpha = tmp_path / "tenants" / "alpha-hotel"
    beta.mkdir(parents=True)
    alpha.mkdir(parents=True)
    (alpha / "tenant_prompt.md").write_text("tenant")
    (alpha / "knowledge").mkdir()

    desired, issues = sync.discover_desired_state(tmp_path)

    assert not issues
    assert desired.system_prompt is not None
    assert [profile.key for profile in desired.profiles] == [
        "alpha",
        "default",
        "zulu",
    ]
    assert all(profile.profile for profile in desired.profiles)
    assert [tenant.slug for tenant in desired.tenants] == [
        "alpha-hotel",
        "beta-hotel",
    ]
    managed, unmanaged = desired.tenants
    assert managed.config is None
    assert managed.prompt is not None
    assert managed.knowledge is not None
    assert managed.knowledge.documents == {}
    assert unmanaged.config is None
    assert unmanaged.prompt is None
    assert unmanaged.knowledge is None


def test_missing_platform_files_are_unmanaged(tmp_path: Path) -> None:
    desired, issues = sync.discover_desired_state(tmp_path)
    assert not issues
    assert desired.system_prompt is None
    assert desired.profiles == ()
    assert desired.tenants == ()


@pytest.mark.parametrize(
    ("relative", "message"),
    [
        ("platform/profiles/Bad.md", "profile filename"),
        ("tenants/Bad_Tenant", "tenant slug"),
    ],
)
def test_discovery_rejects_invalid_paths(
    tmp_path: Path, relative: str, message: str
) -> None:
    path = tmp_path / relative
    if path.suffix:
        path.parent.mkdir(parents=True)
        path.write_text("bad")
    else:
        path.mkdir(parents=True)
    _, issues = sync.discover_desired_state(tmp_path)
    assert any(message in issue.message for issue in issues)


def test_discovery_rejects_managed_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text("secret")
    managed = tmp_path / "platform" / "system_prompt.md"
    managed.parent.mkdir(parents=True)
    managed.symlink_to(target)
    desired, issues = sync.discover_desired_state(tmp_path)
    assert desired.system_prompt is None
    assert any("real file" in issue.message for issue in issues)


def test_plan_uses_only_locally_managed_profiles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    local = sync.DesiredPrompt("hotel", tmp_path / "hotel.md", "local", profile=True)
    desired = sync.DesiredState(tmp_path, None, (local,), ())
    seen: list[str] = []
    monkeypatch.setattr(sync, "discover_desired_state", lambda path: (desired, []))
    monkeypatch.setattr(sync.prompts, "_client", lambda settings: nullcontext(object()))
    monkeypatch.setattr(
        sync, "_remote_profiles", lambda client, report: {"hotel", "remote-only"}
    )
    monkeypatch.setattr(
        sync,
        "_plan_platform_prompt",
        lambda client, prompt, exists, report: seen.append(prompt.key),
    )
    monkeypatch.setattr(sync, "_resolve_tenants", lambda client, state, report: [])

    sync.build_plan(settings(tmp_path))
    assert seen == ["hotel"]


def test_push_order_and_never_pushes_prompt_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    system = sync.DesiredPrompt("default", tmp_path / "system.md", "system")
    profile = sync.DesiredPrompt(
        "hotel", tmp_path / "hotel.md", "profile", profile=True
    )
    config = sync.DesiredConfig(tmp_path / "tenant.yaml", {"schema_version": 3})
    prompt = sync.DesiredPrompt("alpha-hotel", tmp_path / "prompt.md", "prompt")
    kb = sync.DesiredKnowledge(tmp_path / "knowledge", {})
    tenant = sync.DesiredTenant("alpha-hotel", tmp_path, config, prompt, kb)
    desired = sync.DesiredState(tmp_path, system, (profile,), (tenant,))
    remote = sync._TenantRemote(tenant, cast(TenantResponse, object()))
    seen: list[str] = []
    monkeypatch.setattr(sync, "discover_desired_state", lambda path: (desired, []))
    monkeypatch.setattr(sync.prompts, "_client", lambda settings: nullcontext(object()))
    monkeypatch.setattr(sync, "_remote_profiles", lambda client, report: {"hotel"})
    monkeypatch.setattr(
        sync, "_resolve_tenants", lambda client, state, report: [remote]
    )
    monkeypatch.setattr(
        sync,
        "_push_platform",
        lambda client, item, exists, report: seen.append(item.key),
    )
    monkeypatch.setattr(
        sync, "_push_config", lambda client, item, report: seen.append("config")
    )
    monkeypatch.setattr(
        sync,
        "_push_tenant_prompt",
        lambda client, item, report: seen.append("tenant-prompt"),
    )
    monkeypatch.setattr(
        sync,
        "_push_knowledge",
        lambda client, item, report: seen.append("knowledge"),
    )

    sync.push(settings(tmp_path))
    assert seen == ["default", "hotel", "config", "tenant-prompt", "knowledge"]


def test_publish_preflight_blocks_every_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    desired = sync.DesiredState(tmp_path, None, (), ())
    touched: list[str] = []
    monkeypatch.setattr(sync, "discover_desired_state", lambda path: (desired, []))
    monkeypatch.setattr(sync.prompts, "_client", lambda settings: nullcontext(object()))

    def preflight(
        client: object,
        state: object,
        report: sync.SyncReport,
        tasks: list[object],
        tenants: list[object],
    ) -> None:
        report.issues.append(sync.SyncIssue("TenantConfig", "invalid"))
        tasks.append(
            sync._PublishTask(
                "SystemPrompt default",
                "platform",
                sync.DesiredPrompt("default", tmp_path / "system.md", "text"),
                None,
                object(),
            )
        )

    monkeypatch.setattr(sync, "_publish_preflight", preflight)
    monkeypatch.setattr(
        sync,
        "_execute_publish_task",
        lambda client, task, report: touched.append("published"),
    )

    report = sync.publish(settings(tmp_path))
    assert report.exit_code != 0
    assert touched == []


def test_pull_conflict_preflight_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prompt = sync.DesiredPrompt("default", tmp_path / "system.md", "local")
    desired = sync.DesiredState(tmp_path, prompt, (), ())
    touched: list[str] = []
    monkeypatch.setattr(sync, "discover_desired_state", lambda path: (desired, []))
    monkeypatch.setattr(sync.prompts, "_client", lambda settings: nullcontext(object()))
    monkeypatch.setattr(sync, "_remote_profiles", lambda client, report: set())
    monkeypatch.setattr(
        sync,
        "_preflight_pull_prompt",
        lambda client, item, exists, report, writes: writes.append(
            sync._PullWrite("SystemPrompt default", "prompt", item, "remote", True)
        ),
    )
    monkeypatch.setattr(sync, "_resolve_tenants", lambda client, state, report: [])
    monkeypatch.setattr(sync, "_write_pull", lambda item: touched.append(item.resource))

    report = sync.pull(settings(tmp_path), force=False)
    assert report.exit_code == 2
    assert touched == []


def test_pull_force_writes_only_managed_resources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prompt = sync.DesiredPrompt("default", tmp_path / "system.md", "local")
    desired = sync.DesiredState(tmp_path, prompt, (), ())
    touched: list[str] = []
    monkeypatch.setattr(sync, "discover_desired_state", lambda path: (desired, []))
    monkeypatch.setattr(sync.prompts, "_client", lambda settings: nullcontext(object()))
    monkeypatch.setattr(
        sync, "_remote_profiles", lambda client, report: {"remote-only"}
    )
    monkeypatch.setattr(
        sync,
        "_preflight_pull_prompt",
        lambda client, item, exists, report, writes: writes.append(
            sync._PullWrite("SystemPrompt default", "prompt", item, "remote", True)
        ),
    )
    monkeypatch.setattr(sync, "_resolve_tenants", lambda client, state, report: [])
    monkeypatch.setattr(sync, "_write_pull", lambda item: touched.append(item.resource))

    report = sync.pull(settings(tmp_path), force=True)
    assert report.exit_code == 0
    assert touched == ["SystemPrompt default"]


def test_push_partial_failure_is_structured_and_continues() -> None:
    report = sync.SyncReport("push")
    sync._attempt(report, "SystemPrompt default", lambda: True)
    sync._attempt(
        report,
        "ProfilePrompt hotel",
        lambda: (_ for _ in ()).throw(
            sync.PromptCommandError("remote draft changed; run plan and retry")
        ),
    )
    sync._attempt(report, "alpha-hotel TenantPrompt", lambda: False)

    assert report.succeeded == ["SystemPrompt default"]
    assert report.unchanged == ["alpha-hotel TenantPrompt"]
    assert report.failed[0].message == (
        "remote resource changed; run sync plan and retry"
    )


def test_publish_dependency_order_and_backend_prompt_set_apply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tenant = sync.DesiredTenant("alpha-hotel", tmp_path)
    remote = sync._TenantRemote(
        tenant,
        cast(
            TenantResponse,
            SimpleNamespace(slug="alpha-hotel", id="tenant-id"),
        ),
    )
    desired = sync.DesiredState(tmp_path, None, (), (tenant,))
    task_desired = sync.DesiredPrompt("default", tmp_path / "prompt.md", "text")
    tasks = [
        sync._PublishTask(
            "SystemPrompt default", "platform", task_desired, None, object()
        ),
        sync._PublishTask(
            "ProfilePrompt hotel", "platform", task_desired, None, object()
        ),
        sync._PublishTask(
            "alpha-hotel TenantConfig", "config", task_desired, remote.tenant, object()
        ),
        sync._PublishTask(
            "alpha-hotel TenantPrompt",
            "tenant-prompt",
            task_desired,
            remote.tenant,
            object(),
        ),
        sync._PublishTask(
            "alpha-hotel KnowledgeBase",
            "knowledge",
            task_desired,
            remote.tenant,
            object(),
        ),
    ]
    seen: list[str] = []
    monkeypatch.setattr(sync, "discover_desired_state", lambda path: (desired, []))
    monkeypatch.setattr(sync.prompts, "_client", lambda settings: nullcontext(object()))

    def preflight(
        client: object,
        state: object,
        report: sync.SyncReport,
        output: list[sync._PublishTask],
        tenants: list[sync._TenantRemote],
    ) -> None:
        output.extend(tasks)
        tenants.append(remote)

    def execute(
        client: object, task: sync._PublishTask, report: sync.SyncReport
    ) -> None:
        seen.append(task.resource)
        report.succeeded.append(task.resource)

    monkeypatch.setattr(sync, "_publish_preflight", preflight)
    monkeypatch.setattr(sync, "_execute_publish_task", execute)
    monkeypatch.setattr(
        sync,
        "_prompt_set_plan",
        lambda client, tenant: (
            seen.append("alpha-hotel PromptSet plan")
            or SimpleNamespace(status=SimpleNamespace(value="modified"))
        ),
    )
    monkeypatch.setattr(
        sync.apply_prompt_set_admin_v1_tenants_tenant_id_prompt_set_apply_post,
        "sync_detailed",
        lambda tenant_id, client: (
            seen.append("alpha-hotel PromptSet apply") or object()
        ),
    )
    monkeypatch.setattr(
        sync.prompt_sets,
        "_expect",
        lambda response, expected: SimpleNamespace(changed=True),
    )

    report = sync.publish(settings(tmp_path))
    assert report.exit_code == 0
    assert seen == [
        "SystemPrompt default",
        "ProfilePrompt hotel",
        "alpha-hotel TenantConfig",
        "alpha-hotel TenantPrompt",
        "alpha-hotel KnowledgeBase",
        "alpha-hotel PromptSet plan",
        "alpha-hotel PromptSet apply",
    ]
    assert report.prompt_sets_applied == 1


def test_publish_partial_failure_marks_dependent_prompt_set_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tenant = sync.DesiredTenant("alpha-hotel", tmp_path)
    remote_tenant = cast(
        TenantResponse,
        SimpleNamespace(slug="alpha-hotel", id="tenant-id"),
    )
    remote = sync._TenantRemote(tenant, remote_tenant)
    desired = sync.DesiredState(tmp_path, None, (), (tenant,))
    prompt = sync.DesiredPrompt("alpha-hotel", tmp_path / "prompt.md", "text")
    tasks = [
        sync._PublishTask(
            "alpha-hotel TenantConfig", "config", prompt, remote_tenant, object()
        ),
        sync._PublishTask(
            "alpha-hotel TenantPrompt",
            "tenant-prompt",
            prompt,
            remote_tenant,
            object(),
        ),
        sync._PublishTask(
            "alpha-hotel KnowledgeBase",
            "knowledge",
            prompt,
            remote_tenant,
            object(),
        ),
    ]
    monkeypatch.setattr(sync, "discover_desired_state", lambda path: (desired, []))
    monkeypatch.setattr(sync.prompts, "_client", lambda settings: nullcontext(object()))

    def preflight(
        client: object,
        state: object,
        report: sync.SyncReport,
        output: list[sync._PublishTask],
        tenants: list[sync._TenantRemote],
    ) -> None:
        output.extend(tasks)
        tenants.append(remote)

    def execute(
        client: object, task: sync._PublishTask, report: sync.SyncReport
    ) -> None:
        if task.kind == "tenant-prompt":
            raise sync.PromptCommandError("remote conflict")
        report.succeeded.append(task.resource)

    monkeypatch.setattr(sync, "_publish_preflight", preflight)
    monkeypatch.setattr(sync, "_execute_publish_task", execute)

    report = sync.publish(settings(tmp_path))
    assert report.succeeded == [
        "alpha-hotel TenantConfig",
        "alpha-hotel KnowledgeBase",
    ]
    assert [failure.resource for failure in report.failed] == [
        "alpha-hotel TenantPrompt"
    ]
    assert report.pending == ["alpha-hotel PromptSet"]


def test_plan_renderer_distinguishes_authoring_and_runtime_drift(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = sync.SyncReport(
        "plan",
        resources=[
            sync.ResourcePlan(
                "Platform", "SystemPrompt default", "modified", "update draft"
            ),
            sync.ResourcePlan(
                "Tenant: alpha-hotel",
                "alpha-hotel PromptSet",
                "unchanged",
                "reconciliation required after artifact publication",
                future_runtime_reconciliation=True,
            ),
        ],
    )
    sync._render_plan(report)
    output = capsys.readouterr().out
    assert "authoring changes: 1" in output
    assert "runtime reconciliations: 1" in output
