const $ = (id) => document.getElementById(id);
const state = { call: null, room: null, audioTrack: null, poll: null, audioContext: null, analyser: null, meterFrame: null };

function adminHeaders() {
  const token = $("admin-token").value.trim();
  if (!token) throw new Error("Enter the admin token first.");
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, { ...options, headers: { ...adminHeaders(), ...options.headers } });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.detail?.message || body?.detail || `${response.status} ${response.statusText}`);
  return body;
}

function setStatus(value) { $("status").textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2); }
function copyTenant(id) { ["prompt-tenant-id", "config-tenant-id", "call-tenant-id"].forEach((field) => { $(field).value = id; }); }

async function createTenant() {
  const tenant = await api("/admin/v1/tenants", { method: "POST", body: JSON.stringify({ slug: $("tenant-slug").value.trim(), display_name: $("tenant-name").value.trim(), business_type: $("business-type").value.trim() }) });
  copyTenant(tenant.id);
  $("tenant-result").textContent = `Created: ${tenant.id}`;
  setStatus(tenant);
}

async function createPrompt() {
  const tenantId = $("prompt-tenant-id").value.trim();
  const publish = async (path, body) => {
    const draft = await api(path, { method: "POST", body: JSON.stringify(body) });
    return api(`${path}/${draft.id}/publish`, { method: "POST" });
  };
  const system = await publish("/admin/v1/platform/prompts/system/drafts", { key: `debug_${tenantId.replaceAll("-", "")}`, text: $("system-instructions").value });
  const profile = await publish("/admin/v1/platform/prompts/profiles/drafts", { key: "hotel_assistant", text: "" });
  const tenant = await publish(`/admin/v1/tenants/${tenantId}/tenant-prompt/drafts`, { text: $("tenant-instructions").value });
  const documents = { documents: [{ key: "knowledge", media_type: "text/markdown", content: $("knowledge").value }] };
  const knowledgePlan = await api(`/admin/v1/tenants/${tenantId}/knowledge-base/plan`, { method: "POST", body: JSON.stringify(documents) });
  await api(`/admin/v1/tenants/${tenantId}/knowledge-base/push`, { method: "POST", headers: { "If-Match": `"${knowledgePlan.base_version}"` }, body: JSON.stringify(documents) });
  const knowledge = await api(`/admin/v1/tenants/${tenantId}/knowledge-base/publish`, { method: "POST" });
  const draft = await api(`/admin/v1/tenants/${tenantId}/prompt-set/drafts`, { method: "POST", body: JSON.stringify({ system_prompt_revision_id: system.id, profile_prompt_revision_id: profile.id, tenant_prompt_revision_id: tenant.id, knowledge_base_revision_id: knowledge.published.revision.id }) });
  const published = await api(`/admin/v1/tenants/${tenantId}/prompt-set/drafts/${draft.id}/publish`, { method: "POST" });
  $("prompt-revision-id").value = published.id;
  $("prompt-result").textContent = `Published: ${published.id}`;
  setStatus(published);
}

async function createConfig() {
  const tenantId = $("config-tenant-id").value.trim();
  const config = await api(`/admin/v1/tenants/${tenantId}/config/drafts`, { method: "POST", body: JSON.stringify({ config: { schema_version: 4, business: { name: $("tenant-name").value.trim(), type: $("business-type").value.trim() }, contact: {}, localization: { default_locale: $("locale").value.trim(), timezone: $("timezone").value.trim() }, agent: { display_name: $("agent-name").value.trim(), greeting: $("greeting").value.trim(), profile: "hotel_assistant" }, conversation: { scope: "property_only" }, capabilities: {} } }) });
  const published = await api(`/admin/v1/tenants/${tenantId}/config/drafts/${config.id}/publish`, { method: "POST" });
  $("config-result").textContent = `Published: ${published.id}`;
  setStatus(published);
}

async function refreshCall() {
  if (!state.call) return;
  const lifecycle = await api(`/admin/v1/voice/test-sessions/${state.call.call_session_id}`);
  setStatus(lifecycle);
  if (["completed", "failed"].includes(lifecycle.status)) clearInterval(state.poll);
}

async function createCall() {
  state.call = await api("/admin/v1/voice/test-sessions", { method: "POST", body: JSON.stringify({ tenant_id: $("call-tenant-id").value.trim() }) });
  $("call-result").textContent = `Call: ${state.call.call_session_id}, room: ${state.call.room_name}`;
  $("connect").disabled = false;
  await refreshCall();
}

async function checkMicrophone() {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser does not expose microphone access.");
  const probe = await navigator.mediaDevices.getUserMedia({ audio: true });
  probe.getTracks().forEach((track) => track.stop());
  const devices = (await navigator.mediaDevices.enumerateDevices()).filter((device) => device.kind === "audioinput");
  const select = $("mic-device");
  select.replaceChildren(new Option("Default microphone", ""));
  devices.forEach((device, index) => select.add(new Option(device.label || `Microphone ${index + 1}`, device.deviceId)));
  $("mic-state").textContent = devices.length ? `${devices.length} microphone(s) available. Select one and connect.` : "No microphone found.";
}

function startMeter() {
  state.audioContext = new AudioContext();
  state.analyser = state.audioContext.createAnalyser();
  state.analyser.fftSize = 1024;
  const source = state.audioContext.createMediaStreamSource(new MediaStream([state.audioTrack.mediaStreamTrack]));
  source.connect(state.analyser);
  const samples = new Uint8Array(state.analyser.fftSize);
  const update = () => {
    state.analyser.getByteTimeDomainData(samples);
    const rms = Math.sqrt(samples.reduce((sum, value) => sum + ((value - 128) / 128) ** 2, 0) / samples.length);
    const level = Math.min(1, rms * 4);
    $("mic-meter").value = level;
    $("mic-state").textContent = level > 0.04 ? "Voice detected" : "Microphone active, currently quiet";
    state.meterFrame = requestAnimationFrame(update);
  };
  state.audioContext.resume();
  update();
}

async function stopMeter() {
  if (state.meterFrame !== null) cancelAnimationFrame(state.meterFrame);
  state.meterFrame = null;
  state.analyser = null;
  if (state.audioContext) await state.audioContext.close();
  state.audioContext = null;
  $("mic-meter").value = 0;
  $("mic-state").textContent = "Microphone disconnected.";
}

async function connect() {
  const livekit = window.LivekitClient;
  if (!livekit) throw new Error("LiveKit browser SDK did not load. Check internet access to jsDelivr.");
  const room = new livekit.Room();
  room.on(livekit.RoomEvent.TrackSubscribed, (track) => { if (track.kind === livekit.Track.Kind.Audio) document.body.append(track.attach()); });
  room.on(livekit.RoomEvent.Disconnected, () => { stopMeter().catch(() => {}); $("connect").disabled = false; $("disconnect").disabled = true; });
  await room.connect(state.call.livekit_url, state.call.participant_token);
  const deviceId = $("mic-device").value;
  state.audioTrack = await livekit.createLocalAudioTrack(deviceId ? { deviceId } : undefined);
  await room.localParticipant.publishTrack(state.audioTrack);
  state.room = room;
  startMeter();
  $("connect").disabled = true;
  $("disconnect").disabled = false;
  clearInterval(state.poll);
  state.poll = setInterval(() => refreshCall().catch((error) => setStatus(error.message)), 2000);
  await refreshCall();
}

async function disconnect() {
  clearInterval(state.poll);
  await stopMeter();
  state.audioTrack?.stop();
  state.room?.disconnect();
  state.audioTrack = null;
  state.room = null;
  $("connect").disabled = false;
  $("disconnect").disabled = true;
  await refreshCall();
}

function run(action) { action().catch((error) => setStatus(error.message)); }
function selectTab(tab) { document.querySelectorAll('[role="tab"]').forEach((item) => { const selected = item === tab; item.setAttribute("aria-selected", selected); $(item.getAttribute("aria-controls")).hidden = !selected; }); }
document.querySelectorAll('[role="tab"]').forEach((tab) => { tab.onclick = () => selectTab(tab); });
$("create-tenant").onclick = () => run(createTenant);
$("create-prompt").onclick = () => run(createPrompt);
$("create-config").onclick = () => run(createConfig);
$("create-call").onclick = () => run(createCall);
$("check-mic").onclick = () => run(checkMicrophone);
$("connect").onclick = () => run(connect);
$("disconnect").onclick = () => run(disconnect);
