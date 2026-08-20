import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/app";
import { server } from "./setup";

const voice = vi.hoisted(() => ({ connect: vi.fn() }));
vi.mock("../src/features/playground/voice/livekit-voice", () => ({
  connectVoiceSession: voice.connect,
}));

const tenantId = "11111111-1111-4111-8111-111111111111";
const session = {
  call_session_id: "22222222-2222-4222-8222-222222222222",
  room_name: "call_22222222-2222-4222-8222-222222222222",
  livekit_url: "ws://livekit.test",
  participant_identity: "manual-test-browser",
  participant_token: "short-lived-token",
};

const tenant = {
  id: tenantId,
  slug: "debug-hotel",
  display_name: "Debug Hotel",
  business_type: "hotel",
  status: "active",
  active_config_revision_id: "config",
  active_prompt_set_revision_id: "prompt-set",
  active_voice_runtime_revision_id: "runtime",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, resolve, reject };
}

function microphone() {
  return { stop: vi.fn() } as unknown as MediaStreamTrack;
}

function renderPlayground() {
  window.history.pushState({}, "", `/tenants/${tenantId}/playground`);
  server.use(http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])));
  return render(<App />);
}

function media(trackPromise: Promise<MediaStreamTrack>) {
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => {
        const track = await trackPromise;
        return { getAudioTracks: () => [track] };
      }),
    },
  });
}

afterEach(() => {
  voice.connect.mockReset();
});

describe("Playground voice call", () => {
  it("moves through start, connect, mute, end, and authoritative ended states", async () => {
    const user = userEvent.setup();
    const mic = deferred<MediaStreamTrack>();
    const create = deferred<void>();
    const connected = deferred<{
      agentPresent: boolean;
      setMuted: (muted: boolean) => Promise<void>;
      disconnect: () => Promise<void>;
    }>();
    const setMuted = vi.fn(async () => undefined);
    const disconnect = vi.fn(async () => undefined);
    media(mic.promise);
    server.use(
      http.post("/admin/v1/voice/test-sessions", async () => {
        await create.promise;
        return HttpResponse.json(session, { status: 201 });
      }),
      http.get(`/admin/v1/voice/test-sessions/${session.call_session_id}`, () =>
        HttpResponse.json({
          call_session_id: session.call_session_id,
          status: "ended",
          started_at: "2026-01-01T00:00:00Z",
          connected_at: "2026-01-01T00:00:01Z",
          ended_at: "2026-01-01T00:01:00Z",
          failure_reason: null,
        }),
      ),
    );
    voice.connect.mockReturnValue(connected.promise);
    renderPlayground();

    expect(await screen.findByText("Ready to start")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    expect(screen.getByText("Requesting microphone")).toBeVisible();
    await act(() => mic.resolve(microphone()));
    expect(await screen.findByText("Creating session")).toBeVisible();
    await act(() => create.resolve());
    expect(await screen.findByText("Connecting")).toBeVisible();
    await act(() =>
      connected.resolve({ agentPresent: true, setMuted, disconnect }),
    );
    expect(await screen.findByText("Connected")).toBeVisible();
    expect(screen.getByText("Agent is listening")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Mute" }));
    expect(setMuted).toHaveBeenLastCalledWith(true);
    await user.click(screen.getByRole("button", { name: "Unmute" }));
    expect(setMuted).toHaveBeenLastCalledWith(false);
    await user.click(screen.getByRole("button", { name: "End call" }));
    expect(await screen.findByText("Call ended")).toBeVisible();
    expect(disconnect).toHaveBeenCalledOnce();
    expect(
      screen.getByRole("button", { name: "Start test call" }),
    ).toBeVisible();
  });

  it("shows microphone permission and device failures with retry", async () => {
    const user = userEvent.setup();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi
          .fn()
          .mockRejectedValue(new DOMException("blocked", "NotAllowedError")),
      },
    });
    renderPlayground();
    await user.click(
      await screen.findByRole("button", { name: "Start test call" }),
    );
    expect(
      await screen.findByText(/Microphone access was denied/),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();

    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn(async () => ({ getAudioTracks: () => [] })),
      },
    });
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByText("No usable microphone was found."),
    ).toBeVisible();
  });

  it("distinguishes session, connection, and lost-connection failures", async () => {
    const user = userEvent.setup();
    media(Promise.resolve(microphone()));
    server.use(
      http.post("/admin/v1/voice/test-sessions", () =>
        HttpResponse.json(
          { detail: "tenant runtime unavailable" },
          { status: 409 },
        ),
      ),
    );
    renderPlayground();
    await user.click(
      await screen.findByRole("button", { name: "Start test call" }),
    );
    expect(await screen.findByText("tenant runtime unavailable")).toBeVisible();

    server.use(
      http.post("/admin/v1/voice/test-sessions", () =>
        HttpResponse.json(session, { status: 201 }),
      ),
    );
    voice.connect.mockRejectedValueOnce(new Error("signal refused"));
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByText(/LiveKit connection failed: signal refused/),
    ).toBeVisible();

    let lost!: () => void;
    voice.connect.mockImplementationOnce(
      async (_session, _microphone, events) => {
        lost = events.onDisconnected;
        return {
          agentPresent: false,
          setMuted: async () => undefined,
          disconnect: async () => undefined,
        };
      },
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Connected")).toBeVisible();
    act(() => lost());
    expect(
      await screen.findByText("The LiveKit connection was lost."),
    ).toBeVisible();
  });
});
