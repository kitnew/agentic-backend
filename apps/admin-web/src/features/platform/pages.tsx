import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { PageHeader } from "../../components/page-states";
import { ControlPlaneStructuredEditor } from "../../core/configuration/control-plane";

const platformComponents = [
  ["runtime.llm.defaults", "LLM Defaults"],
  ["runtime.stt.defaults", "STT Defaults"],
  ["runtime.tts.defaults", "TTS Defaults"],
  ["runtime.cascade.execution.defaults", "Cascade Defaults"],
  ["runtime.realtime.execution.defaults", "Realtime Defaults"],
] as const;

export function PlatformOverviewPage() {
  return (
    <>
      <PageHeader
        title="Platform"
        detail="Control Plane configuration and Backend operational status are managed separately."
      />
      <div className="grid gap-3 md:grid-cols-2">
        <Link className="rounded border p-4" to={"/platform/runtime" as never}>
          Runtime
          <span className="mt-1 block text-sm text-muted">
            Five independent CP components
          </span>
        </Link>
        <Link
          className="rounded border p-4"
          to={"/platform/system-prompt" as never}
        >
          Prompts
          <span className="mt-1 block text-sm text-muted">
            System and profile-scoped prompts
          </span>
        </Link>
        <Link
          className="rounded border p-4"
          to={"/platform/providers" as never}
        >
          Providers
          <span className="mt-1 block text-sm text-muted">
            Credentials, connections, deployments
          </span>
        </Link>
        <Link
          className="rounded border p-4"
          to={"/platform/telephony" as never}
        >
          Telephony
          <span className="mt-1 block text-sm text-muted">
            Backend operational topology
          </span>
        </Link>
      </div>
    </>
  );
}

export function PlatformRuntimePage() {
  return (
    <div className="space-y-10">
      {platformComponents.map(([kind, title]) => (
        <section key={kind}>
          <h2 className="mb-3 text-lg font-semibold">{title}</h2>
          <ControlPlaneStructuredEditor
            kind={kind}
            scope={{ type: "platform" }}
            title={title}
          />
        </section>
      ))}
    </div>
  );
}

export function PlatformSystemPromptPage() {
  return (
    <ControlPlaneStructuredEditor
      kind="prompt.system"
      scope={{ type: "platform" }}
      title="System Prompt"
      initialValue={{ content: "" }}
    />
  );
}

export function PlatformProfilePromptPage() {
  const [profileKey, setProfileKey] = useState("");
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        Profile scopes are created by Control Plane when a profile component is
        first saved. Enter an existing key to edit it or a new key to create it.
      </p>
      <label className="block text-sm">
        Profile key
        <input
          className="mt-1 block w-full rounded border p-2"
          value={profileKey}
          onChange={(event) => setProfileKey(event.target.value)}
        />
      </label>
      {profileKey && (
        <ControlPlaneStructuredEditor
          key={profileKey}
          kind="prompt.profile"
          scope={{ type: "profile", id: profileKey }}
          title={`Profile Prompt: ${profileKey}`}
          initialValue={{ content: "" }}
        />
      )}
    </div>
  );
}
