(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.VoiceProtocol = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  function parseSession(value) {
    if (!value || typeof value.websocket_url !== 'string' ||
        typeof value.session_token !== 'string' || typeof value.call_session_id !== 'string') {
      throw new Error('Invalid voice session response');
    }
    return value;
  }

  function transition(state, event) {
    const next = { ...state };
    if (event.type === 'session_started') next.connection = 'connected';
    if (event.type === 'session_ended') next.connection = 'disconnected';
    if (event.type === 'processing_started') next.processing = true;
    if (event.code === 'processing_busy') next.processing = true;
    if (event.type === 'turn_completed' || event.type === 'error') next.processing = false;
    if (event.conversation_id) next.conversationId = event.conversation_id;
    return next;
  }

  return { parseSession, transition };
});
