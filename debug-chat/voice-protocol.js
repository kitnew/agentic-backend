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
    if (event.type === 'session_started') { next.connection = 'connected'; next.phase = next.mode === 'call' ? 'connecting' : next.phase; }
    if (event.type === 'session_started') next.sttMode = event.stt_mode || 'batch';
    if (event.type === 'listening_started' || event.type === 'listening_resumed') { next.phase = 'listening'; next.turnId = event.turn_id; }
    if (event.type === 'speech_started') next.phase = 'user_speaking';
    if (event.type === 'speech_ended') next.phase = 'finalizing_stt';
    if (event.type === 'input_audio_started') { next.phase = 'recording'; next.turnId = event.turn_id; }
    if (event.type === 'transcript_partial') next.transcript = event.text || '';
    if (event.type === 'transcript_completed') next.transcript = event.text || event.transcript || '';
    if (event.type === 'session_ended') next.connection = 'disconnected';
    if (event.type === 'processing_started') { next.processing = true; next.phase = 'processing'; }
    if (event.type === 'processing_started') next.phase = 'agent_processing';
    if (event.type === 'assistant_playback_started') next.phase = 'assistant_speaking';
    if (event.type === 'assistant_playback_completed' || event.type === 'assistant_playback_failed') next.phase = 'connecting';
    if (event.type === 'call_ended') next.phase = 'idle';
    if (event.code === 'processing_busy') next.processing = true;
    if (event.type === 'turn_completed' || event.type === 'error') { next.processing = false; next.phase = event.type === 'error' ? 'error' : 'ready'; }
    if (event.conversation_id) next.conversationId = event.conversation_id;
    return next;
  }

  class CallController {
    constructor(deps) {
      this.deps = deps;
      this.state = { mode: 'call', phase: 'idle', connection: 'disconnected', processing: false };
      this.socket = this.capture = this.playback = null;
      this.playbackTimer = null;
    }

    async start(values) {
      if (this.state.phase !== 'idle' && this.state.phase !== 'error') return;
      this.state.phase = 'connecting';
      const session = parseSession(await this.deps.createSession({ ...values, mode: 'call' }));
      this.state.callSessionId = session.call_session_id;
      this.socket = await this.deps.openSocket(session, event => this.handle(event), () => this.disconnected());
      this.capture = await this.deps.startCapture(chunk => this.forward(chunk));
      this.startTurn();
    }

    startTurn() {
      if (!this.socket) return;
      this.state.phase = 'connecting';
      this.socket.send(JSON.stringify({ type: 'input_audio_start', mode: 'call', commit_strategy: 'vad',
        content_type: 'audio/pcm', sample_rate: 16000, channels: 1 }));
    }

    forward(chunk) {
      if (this.socket && (this.state.phase === 'listening' || this.state.phase === 'user_speaking')) this.socket.send(chunk);
    }

    async handle(event) {
      this.state = transition(this.state, event);
      if (event.type === 'assistant_audio') await this.play(event);
      if (event.type === 'turn_ignored' || (event.type === 'turn_completed' && !this.playback)) this.startTurn();
      if (this.deps.onState) this.deps.onState(this.state, event);
    }

    async play(event) {
      this.state = transition(this.state, { type: 'assistant_playback_started' });
      try {
        this.playback = await Promise.race([
          this.deps.play(event),
          new Promise((_, reject) => { this.playbackTimer = setTimeout(() => reject(new Error('playback timeout')), 120000); }),
        ]);
        this.state = transition(this.state, { type: 'assistant_playback_completed' });
      } catch (_) {
        this.state = transition(this.state, { type: 'assistant_playback_failed' });
      } finally {
        clearTimeout(this.playbackTimer); this.playbackTimer = this.playback = null; this.startTurn();
      }
    }

    mute(value) { if (this.capture && this.capture.track) this.capture.track.enabled = !value; }

    disconnected() { this.cleanup(); this.state = { ...this.state, phase: 'error', connection: 'disconnected' }; }

    end() {
      if (this.socket) {
        if (this.state.turnId && ['listening', 'user_speaking'].includes(this.state.phase))
          this.socket.send(JSON.stringify({ type: 'input_audio_cancel', turn_id: this.state.turnId }));
        this.socket.send(JSON.stringify({ type: 'session_end' }));
      }
      this.cleanup(); this.state = transition(this.state, { type: 'call_ended' });
    }

    cleanup() {
      clearTimeout(this.playbackTimer);
      if (this.playback && this.playback.stop) this.playback.stop();
      if (this.capture && this.capture.close) this.capture.close();
      if (this.socket && this.socket.close) this.socket.close();
      this.playback = this.capture = this.socket = null;
    }
  }

  return { parseSession, transition, CallController };
});
