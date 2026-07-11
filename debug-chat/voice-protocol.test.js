const test = require('node:test');
const assert = require('node:assert/strict');
const { parseSession, transition } = require('./voice-protocol');

test('parseSession accepts the signed session fields', () => {
  const value = { websocket_url: 'ws://localhost:8001/ws', session_token: 'secret', call_session_id: 'call' };
  assert.equal(parseSession(value), value);
});

test('parseSession rejects incomplete responses', () => {
  assert.throws(() => parseSession({ websocket_url: 'ws://localhost' }));
});

test('transition tracks connection, processing, and conversation', () => {
  let state = transition({}, { type: 'session_started' });
  state = transition(state, { type: 'processing_started' });
  state = transition(state, { type: 'turn_completed', conversation_id: 'c1' });
  assert.deepEqual(state, { connection: 'connected', processing: false, conversationId: 'c1' });
});
