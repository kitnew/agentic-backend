import { useEffect, useRef, useState } from "react";

import { EmptyState, PageHeader } from "../../../components/page-states";
import { Button } from "../../../components/ui/button";
import type { CreateTestVoiceSessionResponse } from "../../../core/api/generated/models";
import { useTenant } from "../../../core/tenant/use-tenant";
import { createTestSession, getTestSession } from "../queries/test-session";
import {
  connectVoiceSession,
  type TranscriptEntry,
  type VoiceConnection,
} from "../voice/livekit-voice";

type FailureKind =
  | "permission-denied"
  | "no-microphone"
  | "session-creation"
  | "connection"
  | "connection-lost";

type CallState =
  | { status: "idle" }
  | { status: "requesting-microphone" }
  | { status: "creating-session" }
  | { status: "connecting"; session: CreateTestVoiceSessionResponse }
  | {
      status: "connected";
      session: CreateTestVoiceSessionResponse;
      connectedAt: number;
      muted: boolean;
      agentPresent: boolean;
      agentSpeaking: boolean;
    }
  | { status: "ending"; session: CreateTestVoiceSessionResponse }
  | {
      status: "ended";
      session: CreateTestVoiceSessionResponse;
      backendPending: boolean;
    }
  | { status: "failed"; kind: FailureKind; message: string };

const statusLabel: Record<CallState["status"], string> = {
  idle: "Ready to start",
  "requesting-microphone": "Requesting microphone",
  "creating-session": "Creating session",
  connecting: "Connecting",
  connected: "Connected",
  ending: "Ending call",
  ended: "Call ended",
  failed: "Call failed",
};

function microphoneFailure(
  error: unknown,
): Pick<CallState & { status: "failed" }, "kind" | "message"> {
  if (error instanceof DOMException && error.name === "NotAllowedError")
    return {
      kind: "permission-denied",
      message: "Microphone access was denied. Allow access and try again.",
    };
  if (
    error instanceof DOMException &&
    ["NotFoundError", "DevicesNotFoundError"].includes(error.name)
  )
    return {
      kind: "no-microphone",
      message: "No usable microphone was found.",
    };
  return {
    kind: "no-microphone",
    message: "The microphone could not be opened.",
  };
}

function duration(startedAt: number, now: number) {
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(
    seconds % 60,
  ).padStart(2, "0")}`;
}

function errorMessage(error: unknown, fallback: string) {
  return typeof error === "object" &&
    error !== null &&
    "message" in error &&
    typeof error.message === "string"
    ? error.message
    : fallback;
}

async function terminalState(callId: string) {
  try {
    let terminal = false;
    for (let attempt = 0; attempt < 20 && !terminal; attempt += 1) {
      const lifecycle = await getTestSession(callId);
      terminal = lifecycle.status === "ended" || lifecycle.status === "failed";
      if (!terminal)
        await new Promise((resolve) => window.setTimeout(resolve, 500));
    }
    return terminal;
  } catch {
    return false;
  }
}

function Playground({ tenantId }: { tenantId: string }) {
  const [state, setState] = useState<CallState>({ status: "idle" });
  const [now, setNow] = useState(Date.now());
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const connection = useRef<VoiceConnection | null>(null);
  const operation = useRef(false);
  const expectedDisconnect = useRef(false);

  useEffect(() => {
    if (state.status !== "connected") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [state.status]);

  useEffect(
    () => () => {
      expectedDisconnect.current = true;
      void connection.current?.disconnect();
    },
    [],
  );

  async function start() {
    if (operation.current) return;
    operation.current = true;
    expectedDisconnect.current = false;
    setTranscript([]);
    setState({ status: "requesting-microphone" });
    let microphone: MediaStreamTrack;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const [first, ...unused] = stream.getAudioTracks();
      for (const track of unused) track.stop();
      if (!first) throw new DOMException("No microphone", "NotFoundError");
      microphone = first;
    } catch (error) {
      setState({ status: "failed", ...microphoneFailure(error) });
      operation.current = false;
      return;
    }

    setState({ status: "creating-session" });
    let session: CreateTestVoiceSessionResponse;
    try {
      session = await createTestSession(tenantId);
    } catch (error) {
      microphone.stop();
      setState({
        status: "failed",
        kind: "session-creation",
        message: errorMessage(error, "Session creation failed."),
      });
      operation.current = false;
      return;
    }

    setState({ status: "connecting", session });
    try {
      const activeConnection = await connectVoiceSession(session, microphone, {
        onDisconnected: () => {
          connection.current = null;
          if (!expectedDisconnect.current)
            setState({
              status: "failed",
              kind: "connection-lost",
              message: "The LiveKit connection was lost.",
            });
        },
        onAgentPresent: (agentPresent) =>
          setState((current) =>
            current.status === "connected"
              ? { ...current, agentPresent }
              : current,
          ),
        onAgentSpeaking: (agentSpeaking) =>
          setState((current) =>
            current.status === "connected"
              ? { ...current, agentSpeaking }
              : current,
          ),
        onTranscript: (entry) =>
          setTranscript((current) => [
            ...current.filter((item) => item.id !== entry.id),
            entry,
          ]),
      });
      connection.current = activeConnection;
      setNow(Date.now());
      setState({
        status: "connected",
        session,
        connectedAt: Date.now(),
        muted: false,
        agentPresent: activeConnection.agentPresent,
        agentSpeaking: false,
      });
    } catch (error) {
      setState({
        status: "failed",
        kind: "connection",
        message: `LiveKit connection failed: ${errorMessage(error, "Unknown error")}`,
      });
    } finally {
      operation.current = false;
    }
  }

  async function toggleMute() {
    if (state.status !== "connected" || operation.current) return;
    operation.current = true;
    const muted = !state.muted;
    try {
      await connection.current?.setMuted(muted);
      setState((current) =>
        current.status === "connected" ? { ...current, muted } : current,
      );
    } finally {
      operation.current = false;
    }
  }

  async function end() {
    if (state.status !== "connected" || operation.current) return;
    operation.current = true;
    expectedDisconnect.current = true;
    const { session } = state;
    setState({ status: "ending", session });
    try {
      await connection.current?.disconnect();
      connection.current = null;
      setState({
        status: "ended",
        session,
        backendPending: !(await terminalState(session.call_session_id)),
      });
    } catch (error) {
      setState({
        status: "failed",
        kind: "connection",
        message: errorMessage(error, "Call ending failed."),
      });
    } finally {
      operation.current = false;
    }
  }

  const session = "session" in state ? state.session : undefined;
  const busy = [
    "requesting-microphone",
    "creating-session",
    "connecting",
    "ending",
  ].includes(state.status);

  return (
    <>
      <PageHeader
        title="Playground"
        detail="Run the configured tenant agent through the real voice pipeline."
      />
      <div className="mb-4 inline-flex rounded-md border p-1 text-sm">
        <span className="rounded bg-slate-100 px-3 py-1 text-muted">Chat</span>
        <span className="rounded bg-primary px-3 py-1 text-primary-foreground">
          Voice
        </span>
      </div>
      <section className="max-w-2xl rounded-md border bg-panel p-6">
        <h2 className="text-lg font-semibold">Voice test</h2>
        <p className="mt-4 text-sm font-medium" role="status">
          {state.status === "connected" && (
            <span className="mr-2 text-green-600" aria-hidden="true">
              ●
            </span>
          )}
          {statusLabel[state.status]}
        </p>

        {state.status === "connected" && (
          <>
            <p className="mt-4 text-4xl tabular-nums">
              {duration(state.connectedAt, now)}
            </p>
            <p className="mt-2 text-sm text-muted">
              {!state.agentPresent
                ? "Waiting for agent"
                : state.agentSpeaking
                  ? "Agent is speaking"
                  : "Agent is listening"}
            </p>
          </>
        )}

        {state.status === "failed" && (
          <p className="mt-3 text-sm text-red-700" role="alert">
            {state.message}
          </p>
        )}
        {state.status === "ended" && state.backendPending && (
          <p className="mt-3 text-sm text-amber-700">
            Browser audio ended; Backend finalization is still pending.
          </p>
        )}

        <div className="mt-6 flex gap-3">
          {state.status === "connected" ? (
            <>
              <Button variant="outline" onClick={toggleMute}>
                {state.muted ? "Unmute" : "Mute"}
              </Button>
              <Button onClick={end}>End call</Button>
            </>
          ) : (
            <Button disabled={busy} onClick={start}>
              {busy
                ? "Starting…"
                : state.status === "failed"
                  ? "Try again"
                  : "Start test call"}
            </Button>
          )}
        </div>

        <p className="mt-5 text-sm text-muted">
          Microphone access is required. This runs configured capabilities and
          post-call integrations with their normal side effects.
        </p>

        {transcript.length > 0 && (
          <section className="mt-6 border-t pt-4" aria-label="Live transcript">
            <h3 className="font-medium">Transcript</h3>
            <div className="mt-3 space-y-3">
              {transcript.map((entry) => (
                <div key={entry.id}>
                  <p className="text-xs font-semibold text-muted">
                    {entry.speaker}
                  </p>
                  <p className={entry.final ? "text-sm" : "text-sm opacity-70"}>
                    {entry.text}
                  </p>
                </div>
              ))}
            </div>
          </section>
        )}

        {session && (
          <details className="mt-6 border-t pt-4 text-sm">
            <summary className="cursor-pointer font-medium">
              Diagnostics
            </summary>
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 break-all text-muted">
              <dt>Call ID</dt>
              <dd>{session.call_session_id}</dd>
              <dt>Room</dt>
              <dd>{session.room_name}</dd>
              <dt>Connection</dt>
              <dd>{state.status}</dd>
              <dt>Microphone</dt>
              <dd>
                {state.status === "connected" && state.muted
                  ? "muted"
                  : "enabled"}
              </dd>
              <dt>Agent</dt>
              <dd>
                {state.status === "connected" && state.agentPresent
                  ? "present"
                  : "waiting"}
              </dd>
            </dl>
          </details>
        )}
      </section>
    </>
  );
}

export function PlaygroundPage() {
  const { tenantId } = useTenant();
  if (!tenantId)
    return <EmptyState title="Select a tenant to open Playground" />;
  return <Playground tenantId={tenantId} />;
}
