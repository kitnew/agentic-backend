(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.LiveKitDebug = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  class LiveKitController {
    constructor({ sdk, fetchFn, audioContainer, onState, onTranscript, onTelemetry, onSession, onError }) {
      this.sdk = sdk;
      this.fetchFn = fetchFn || fetch;
      this.audioContainer = audioContainer;
      this.onState = onState || (() => {});
      this.onTranscript = onTranscript || (() => {});
      this.onTelemetry = onTelemetry || (() => {});
      this.onSession = onSession || (() => {});
      this.onError = onError || (() => {});
      this.room = null;
      this.starting = false;
      this.stopping = false;
      this.muted = false;
      this.acceptUserInterim = true;
    }

    async start({ tenantId, conversationId }) {
      if (this.starting || this.stopping || this.room) return false;
      this.starting = true;
      this.acceptUserInterim = true;
      this.onState({ connection: 'connecting' });
      try {
        const response = await this.fetchFn('/debug/livekit-session', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(compact({ tenant_id: tenantId, conversation_id: conversationId })),
        });
        const session = await response.json();
        if (!response.ok) throw new Error(readError(session, `Session HTTP ${response.status}`));
        const token = session.participant_token;
        this.onSession({ ...session, participant_token: '[redacted]' });

        const room = new this.sdk.Room({ adaptiveStream: true, dynacast: true });
        this.room = room;
        this._bind(room);
        await room.connect(session.livekit_url, token);
        await room.localParticipant.setMicrophoneEnabled(true);
        this.muted = false;
        this.onState({
          connection: 'connected',
          participantIdentity: room.localParticipant.identity,
          microphone: 'enabled',
        });
        return true;
      } catch (error) {
        await this.stop();
        this.onError(error);
        return false;
      } finally {
        this.starting = false;
      }
    }

    async stop() {
      const room = this.room;
      this.room = null;
      if (!room) return;
      this.stopping = true;
      try {
        await room.disconnect(true);
      } finally {
        this.stopping = false;
        if (this.audioContainer) this.audioContainer.replaceChildren();
        this.onState({ connection: 'disconnected', microphone: 'disabled' });
      }
    }

    async toggleMute() {
      if (!this.room) return false;
      const publication = this.room.localParticipant.getTrackPublication(
        this.sdk.Track.Source.Microphone
      );
      if (!publication?.track) return false;
      this.muted = !this.muted;
      if (this.muted) await publication.track.mute();
      else await publication.track.unmute();
      this.onState({ microphone: this.muted ? 'muted' : 'enabled' });
      return this.muted;
    }

    _bind(room) {
      room.on(this.sdk.RoomEvent.TrackSubscribed, (track) => {
        if (track.kind !== this.sdk.Track.Kind.Audio) return;
        const element = track.attach();
        element.autoplay = true;
        if (this.audioContainer) this.audioContainer.append(element);
      });
      room.on(this.sdk.RoomEvent.TrackUnsubscribed, (track) => {
        for (const element of track.detach()) element.remove();
      });
      room.on(this.sdk.RoomEvent.ActiveSpeakersChanged, (speakers) => {
        const local = speakers.some((participant) => participant.identity === room.localParticipant.identity);
        this.onState({ user: local ? 'speaking' : 'silent' });
      });
      room.on(this.sdk.RoomEvent.ParticipantAttributesChanged, (_changed, participant) => {
        const agentState = participant.attributes?.['lk.agent.state'];
        if (agentState) this.onState({ agent: agentState });
      });
      room.on(this.sdk.RoomEvent.ParticipantConnected, (participant) => {
        const agentState = participant.attributes?.['lk.agent.state'];
        if (agentState) this.onState({ agent: agentState });
      });
      room.on(this.sdk.RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
        if (topic !== 'voice.telemetry') return;
        try {
          const event = JSON.parse(new TextDecoder().decode(payload));
          if (event.event === 'user_speech_started') this.acceptUserInterim = true;
          this.onTelemetry(event);
        } catch (error) {
          this.onError(new Error(`Invalid telemetry: ${error.message}`));
        }
      });
      room.on(this.sdk.RoomEvent.Disconnected, () => {
        this.room = null;
        if (this.audioContainer) this.audioContainer.replaceChildren();
        this.onState({ connection: 'disconnected', microphone: 'disabled' });
      });
      room.registerTextStreamHandler('lk.transcription', async (reader, participant) => {
        const text = await reader.readAll();
        const final = reader.info?.attributes?.['lk.transcription_final'] === true ||
          reader.info?.attributes?.['lk.transcription_final'] === 'true';
        const role = participant.identity === room.localParticipant.identity ? 'user' : 'assistant';
        if (role === 'user' && !final && (
          !this.acceptUserInterim || !/[\p{L}\p{N}]/u.test(text)
        )) return;
        if (role === 'user' && final) this.acceptUserInterim = false;
        this.onTranscript({
          role,
          text,
          final,
          segmentId: reader.info?.attributes?.['lk.segment_id'] || reader.info?.id,
        });
      });
    }
  }

  function compact(value) {
    return Object.fromEntries(Object.entries(value).filter(([, item]) => item));
  }

  function readError(value, fallback) {
    return value?.detail || value?.error || fallback;
  }

  return { LiveKitController };
});
