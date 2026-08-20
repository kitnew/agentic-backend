import type { TranscriptionSegment } from "livekit-client";

import type { CreateTestVoiceSessionResponse } from "../../../core/api/generated/models";

export type TranscriptEntry = {
  id: string;
  speaker: string;
  text: string;
  final: boolean;
};

export type VoiceEvents = {
  onDisconnected: () => void;
  onAgentPresent: (present: boolean) => void;
  onAgentSpeaking: (speaking: boolean) => void;
  onTranscript: (entry: TranscriptEntry) => void;
};

export type VoiceConnection = {
  agentPresent: boolean;
  setMuted: (muted: boolean) => Promise<void>;
  disconnect: () => Promise<void>;
};

declare global {
  interface Window {
    __playgroundVoiceTest?: (
      session: CreateTestVoiceSessionResponse,
      microphone: MediaStreamTrack,
      events: VoiceEvents,
    ) => Promise<VoiceConnection>;
  }
}

export async function connectVoiceSession(
  session: CreateTestVoiceSessionResponse,
  microphone: MediaStreamTrack,
  events: VoiceEvents,
): Promise<VoiceConnection> {
  if (import.meta.env.MODE === "e2e" && window.__playgroundVoiceTest)
    return window.__playgroundVoiceTest(session, microphone, events);

  const { RemoteAudioTrack, Room, RoomEvent, Track } = await import(
    "livekit-client"
  );
  const room = new Room({ adaptiveStream: true });
  const audioElements = new Set<HTMLMediaElement>();
  const updateAgentPresence = () =>
    events.onAgentPresent(room.remoteParticipants.size > 0);
  room.on(RoomEvent.ParticipantConnected, updateAgentPresence);
  room.on(RoomEvent.ParticipantDisconnected, updateAgentPresence);
  room.on(RoomEvent.ActiveSpeakersChanged, (speakers) =>
    events.onAgentSpeaking(
      speakers.some(
        (participant) =>
          participant.identity !== room.localParticipant.identity,
      ),
    ),
  );
  room.on(RoomEvent.TrackSubscribed, (track) => {
    if (!(track instanceof RemoteAudioTrack)) return;
    const element = track.attach();
    element.autoplay = true;
    audioElements.add(element);
    document.body.append(element);
  });
  room.on(RoomEvent.TrackUnsubscribed, (track) => {
    if (!(track instanceof RemoteAudioTrack)) return;
    for (const element of track.detach()) {
      audioElements.delete(element);
      element.remove();
    }
  });
  room.on(RoomEvent.TranscriptionReceived, (segments, participant) => {
    for (const segment of segments as TranscriptionSegment[])
      events.onTranscript({
        id: segment.id,
        speaker:
          participant?.identity === session.participant_identity
            ? "You"
            : participant?.name || "Agent",
        text: segment.text,
        final: segment.final,
      });
  });
  room.on(RoomEvent.Disconnected, events.onDisconnected);

  try {
    await room.connect(session.livekit_url, session.participant_token);
    const publication = await room.localParticipant.publishTrack(microphone, {
      source: Track.Source.Microphone,
    });
    updateAgentPresence();
    return {
      agentPresent: room.remoteParticipants.size > 0,
      setMuted: async (muted) => {
        await (muted ? publication.mute() : publication.unmute());
      },
      disconnect: async () => {
        await room.disconnect(true);
        for (const element of audioElements) element.remove();
        audioElements.clear();
      },
    };
  } catch (error) {
    await room.disconnect(true);
    microphone.stop();
    throw error;
  }
}
