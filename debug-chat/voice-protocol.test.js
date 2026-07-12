const test = require('node:test');
const assert = require('node:assert/strict');
const { parseSession, transition, CallController } = require('./voice-protocol');

test('parseSession accepts the signed session fields', () => {
  const value = { websocket_url: 'ws://localhost:8001/ws', session_token: 'secret', call_session_id: 'call' };
  assert.equal(parseSession(value), value);
});

test('call controller gates frames, resumes after playback, and releases resources', async () => {
  const sent = []; let onEvent; let captureClosed = false; let socketClosed = false;
  const controller = new CallController({
    createSession: async body => ({ websocket_url: 'ws://voice', session_token: 'token', call_session_id: body.mode }),
    openSocket: async (_session, event) => { onEvent = event; return { send: value => sent.push(value), close: () => { socketClosed = true; } }; },
    startCapture: async forward => ({ forward, track: { enabled: true }, close: () => { captureClosed = true; } }),
    play: async () => {},
  });
  await controller.start({ tenant_id: 'tenant-1' });
  controller.forward(new Uint8Array([1]));
  await onEvent({ type: 'listening_started', turn_id: 'one' });
  controller.forward(new Uint8Array([2]));
  await onEvent({ type: 'speech_ended' });
  controller.forward(new Uint8Array([3]));
  await onEvent({ type: 'assistant_audio', audio_base64: 'x' });
  assert.equal(sent.filter(value => value instanceof Uint8Array).length, 1);
  assert.equal(JSON.parse(sent.at(-1)).commit_strategy, 'vad');
  controller.end();
  assert.equal(captureClosed && socketClosed, true);
});

test('parseSession rejects incomplete responses', () => {
  assert.throws(() => parseSession({ websocket_url: 'ws://localhost' }));
});

test('transition tracks connection, processing, and conversation', () => {
  let state = transition({}, { type: 'session_started', stt_mode: 'streaming' });
  state = transition(state, { type: 'input_audio_started', turn_id: 't1' });
  state = transition(state, { type: 'transcript_partial', text: 'hel' });
  state = transition(state, { type: 'transcript_completed', text: 'hello' });
  state = transition(state, { type: 'processing_started' });
  state = transition(state, { type: 'turn_completed', conversation_id: 'c1' });
  assert.deepEqual(state, { connection: 'connected', sttMode: 'streaming', phase: 'ready', turnId: 't1', transcript: 'hello', processing: false, conversationId: 'c1' });
});
