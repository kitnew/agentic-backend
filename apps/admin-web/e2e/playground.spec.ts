import { expect, test } from "@playwright/test";

const tenantId = "11111111-1111-4111-8111-111111111111";
const callId = "22222222-2222-4222-8222-222222222222";

test("tenant Playground completes a mocked browser voice call", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const microphone = { stop() {} } as MediaStreamTrack;
    Object.defineProperty(navigator, "mediaDevices", {
      value: {
        getUserMedia: async () => ({ getAudioTracks: () => [microphone] }),
      },
    });
    window.__playgroundVoiceTest = async (_session, _track, events) => {
      events.onAgentPresent(true);
      return {
        agentPresent: true,
        setMuted: async (muted) => {
          document.body.dataset.voiceMuted = String(muted);
        },
        disconnect: async () => {
          document.body.dataset.voiceDisconnected = "true";
          events.onDisconnected();
        },
      };
    };
  });
  await page.route("**/admin/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/admin/v1/tenants")
      return route.fulfill({
        json: [
          {
            id: tenantId,
            slug: "debug-hotel",
            display_name: "Debug Hotel",
            business_type: "hotel",
            status: "active",
            active_release_id: "config",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
      });
    if (path === "/admin/v1/voice/test-sessions" && request.method() === "POST")
      return route.fulfill({
        status: 201,
        json: {
          call_session_id: callId,
          room_name: `call_${callId}`,
          livekit_url: "ws://livekit.test",
          participant_identity: "manual-test-browser",
          participant_token: "short-lived-token",
        },
      });
    if (path === `/admin/v1/voice/test-sessions/${callId}`)
      return route.fulfill({
        json: {
          call_session_id: callId,
          status: "ended",
          started_at: "2026-01-01T00:00:00Z",
          connected_at: "2026-01-01T00:00:01Z",
          ended_at: "2026-01-01T00:01:00Z",
          failure_reason: null,
        },
      });
    return route.fulfill({
      status: 404,
      json: { detail: `Unhandled ${path}` },
    });
  });

  await page.goto("/");
  await page.getByRole("link", { name: "Debug Hotel" }).click();
  await page.getByRole("link", { name: "Playground" }).click();
  await page.getByRole("button", { name: "Start test call" }).click();
  await expect(page.getByRole("status")).toContainText("Connected");
  await page.getByRole("button", { name: "Mute" }).click();
  await expect(page.locator("body")).toHaveAttribute(
    "data-voice-muted",
    "true",
  );
  await page.getByRole("button", { name: "Unmute" }).click();
  await expect(page.locator("body")).toHaveAttribute(
    "data-voice-muted",
    "false",
  );
  await page.getByRole("button", { name: "End call" }).click();
  await expect(page.getByRole("status")).toContainText("Call ended");
  await expect(page.locator("body")).toHaveAttribute(
    "data-voice-disconnected",
    "true",
  );
});
