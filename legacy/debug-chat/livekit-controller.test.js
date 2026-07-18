const test = require('node:test');
const assert = require('node:assert/strict');
const { LiveKitController } = require('./livekit-controller');

class FakeRoom {
  constructor() {
    this.handlers = {};
    this.textHandlers = {};
    this.publication = {
      track: {
        mute: async () => { this.muted = true; },
        unmute: async () => { this.muted = false; },
      },
    };
    this.localParticipant = {
      identity: 'browser-call',
      setMicrophoneEnabled: async () => { this.microphonePublishes = (this.microphonePublishes || 0) + 1; },
      getTrackPublication: () => this.publication,
    };
  }
  on(event, handler) { this.handlers[event] = handler; return this; }
  registerTextStreamHandler(topic, handler) { this.textHandlers[topic] = handler; }
  async connect(url, token) { this.connected = { url, token }; }
  disconnect(stopTracks) { this.disconnected = stopTracks; }
}

const sdk = {
  Room: FakeRoom,
  RoomEvent: {
    TrackSubscribed: 'track', TrackUnsubscribed: 'untrack', ActiveSpeakersChanged: 'speakers',
    ParticipantAttributesChanged: 'attributes', DataReceived: 'data', Disconnected: 'disconnected',
    ParticipantConnected: 'participantConnected',
  },
  Track: { Source: { Microphone: 'microphone' }, Kind: { Audio: 'audio' } },
};

function response() {
  return {
    ok: true,
    json: async () => ({
      runtime: 'livekit', call_session_id: 'call', conversation_id: 'conversation',
      room_name: 'voice-call', livekit_url: 'ws://localhost:7880', participant_token: 'secret-token',
    }),
  };
}

test('start is single-flight, redacts token, publishes one microphone, and cleans up', async () => {
  const sessions = [];
  const audio = { append() {}, replaceChildren() { this.cleared = true; } };
  const controller = new LiveKitController({
    sdk, fetchFn: async () => response(), audioContainer: audio, onSession: value => sessions.push(value),
  });
  assert.equal(await controller.start({ tenantId: 'demo_restaurant' }), true);
  const room = controller.room;
  assert.equal(await controller.start({ tenantId: 'demo_restaurant' }), false);
  assert.equal(room.microphonePublishes, 1);
  assert.equal(sessions[0].participant_token, '[redacted]');
  await controller.stop();
  assert.equal(room.disconnected, true);
  assert.equal(audio.cleared, true);
});

test('attaches remote audio, handles transcripts and errors without exposing token', async () => {
  const attached = [];
  const transcripts = [];
  const errors = [];
  const controller = new LiveKitController({
    sdk, fetchFn: async () => response(), audioContainer: { append: item => attached.push(item), replaceChildren() {} },
    onTranscript: value => transcripts.push(value), onError: error => errors.push(error.message),
  });
  await controller.start({ tenantId: 'demo_restaurant' });
  controller.room.handlers.track({ kind: 'audio', attach: () => ({ autoplay: false }) });
  assert.equal(attached[0].autoplay, true);
  await controller.room.textHandlers['lk.transcription'](
    { readAll: async () => 'Ahoj', info: { attributes: { 'lk.transcription_final': true } } },
    { identity: 'browser-call' },
  );
  assert.deepEqual(transcripts[0], { role: 'user', text: 'Ahoj', final: true, segmentId: undefined });
  controller.room.handlers.data(new TextEncoder().encode('{bad'), null, null, 'voice.telemetry');
  assert.match(errors[0], /Invalid telemetry/);
  assert.doesNotMatch(JSON.stringify({ transcripts, errors }), /secret-token/);
  await controller.stop();
});

test('ignores late user interim after final until speech resumes', async () => {
  const transcripts = [];
  const controller = new LiveKitController({
    sdk, fetchFn: async () => response(), onTranscript: value => transcripts.push(value),
  });
  await controller.start({ tenantId: 'demo_restaurant' });
  const transcribe = text => controller.room.textHandlers['lk.transcription'](
    { readAll: async () => text, info: { attributes: {} } },
    { identity: 'browser-call' },
  );

  await controller.room.textHandlers['lk.transcription'](
    { readAll: async () => 'Ahoj', info: { attributes: { 'lk.transcription_final': true } } },
    { identity: 'browser-call' },
  );
  await transcribe('Nie.');
  controller.room.handlers.data(
    new TextEncoder().encode('{"event":"user_speech_started"}'), null, null, 'voice.telemetry'
  );
  await transcribe('.');
  await transcribe('Nová veta');

  assert.deepEqual(transcripts.map(item => item.text), ['Ahoj', 'Nová veta']);
  await controller.stop();
});
