"""
Behavioral regression tests verifying TONI frontend voice lifecycle, teardown, and resource cleanup.

Ensures that:
1. Fallback acknowledgement ("init_ack" status: "fallback") completely tears down voice session,
   stops microphone tracks, closes audio contexts, and resets UI while preserving chat history.
2. Upstream failure ("error": "upstream_receiver_failed") tears down voice and microphone cleanly.
3. WebSocket error and closure trigger complete voice session teardown.
4. Microphone permission denial tears down voice session and resets UI to default.
5. Delayed microphone permission resolution after toggle-off or restart does not reactivate capture
   or create orphaned audio resources.
6. Both readiness orders (mic ready first vs live WebSocket ready first) correctly show connecting
   status and only present listening readiness when BOTH are ready.
7. Successful retry after a failure ignores stale socket and audio callbacks from the old session.
8. Audio processing and sending is gated on both mic and live WebSocket readiness.
9. Playback AudioContext is closed and cleared on teardown, and old playback callbacks are invalidated.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import pytest

INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "static" / "index.html"


def _run_voice_js_in_node(js_test_code: str) -> dict:
    """
    Executes a test script inside Node.js with mock DOM, WebSocket, and Web Audio APIs,
    evaluating the real JavaScript from static/index.html under browser global semantics (window === globalThis).
    """
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("node is not available on PATH")

    index_html_json = json.dumps(str(INDEX_HTML_PATH))

    harness = f"""
const fs = require('fs');
const vm = require('vm');

// Model browser global semantics (window === globalThis === self)
globalThis.window = globalThis;
globalThis.self = globalThis;

// --- DOM and Web API Mocks ---
const elements = {{}};
const getOrCreateElement = (id) => {{
  if (!elements[id]) {{
    const classListSet = new Set();
    elements[id] = {{
      id,
      className: '',
      style: {{}},
      dataset: {{}},
      classList: {{
        add: (...cls) => cls.forEach(c => classListSet.add(c)),
        remove: (...cls) => cls.forEach(c => classListSet.delete(c)),
        contains: (c) => classListSet.has(c)
      }},
      children: [],
      appendChild(child) {{
        this.children.push(child);
      }},
      querySelectorAll() {{ return []; }},
      querySelector(sel) {{
        return {{
          className: '',
          innerText: '',
          textContent: '',
          style: {{}},
          querySelector() {{ return null; }}
        }};
      }},
      scrollTo() {{}},
      innerHTML: '',
      innerText: '',
      textContent: '',
      value: '',
      addEventListener() {{}},
      removeEventListener() {{}}
    }};
  }}
  return elements[id];
}};

const document = {{
  createElement(tag) {{
    const classListSet = new Set();
    return {{
      tagName: tag.toUpperCase(),
      className: '',
      style: {{}},
      dataset: {{}},
      setAttribute() {{}},
      getAttribute() {{ return ''; }},
      children: [],
      appendChild(c) {{ this.children.push(c); }},
      replaceWith() {{}},
      querySelectorAll() {{ return []; }},
      querySelector(sel) {{
        return {{
          className: '',
          innerText: '',
          textContent: '',
          style: {{}}
        }};
      }},
      classList: {{
        add: (...cls) => cls.forEach(c => classListSet.add(c)),
        remove: (...cls) => cls.forEach(c => classListSet.delete(c)),
        contains: (c) => classListSet.has(c)
      }},
      textContent: '',
      innerText: '',
      innerHTML: '',
      addEventListener() {{}},
      removeEventListener() {{}}
    }};
  }},
  getElementById: getOrCreateElement,
  querySelectorAll() {{ return []; }},
  addEventListener() {{}}
}};

globalThis.document = document;
globalThis.location = {{ search: '', protocol: 'http:', host: 'localhost:8000' }};
globalThis.atob = (b64) => Buffer.from(b64, 'base64').toString('binary');
globalThis.btoa = (str) => Buffer.from(str, 'binary').toString('base64');
globalThis.addEventListener = () => {{}};
globalThis.removeEventListener = () => {{}};

// --- Mock WebSocket ---
const mockSockets = [];
class MockWebSocket {{
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url) {{
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.sentMessages = [];
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    this.onclose = null;
    mockSockets.push(this);
  }}

  send(data) {{
    this.sentMessages.push(typeof data === 'string' ? JSON.parse(data) : data);
  }}

  close() {{
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose({{ type: 'close' }});
  }}

  simulateOpen() {{
    this.readyState = MockWebSocket.OPEN;
    if (this.onopen) this.onopen({{ type: 'open' }});
  }}

  simulateMessage(msg) {{
    if (this.onmessage) this.onmessage({{ data: JSON.stringify(msg) }});
  }}

  simulateError(err) {{
    if (this.onerror) this.onerror(err || {{ type: 'error' }});
  }}
}}
globalThis.WebSocket = MockWebSocket;

// --- Mock Web Audio ---
const mockAudioContexts = [];
const mockAudioNodes = [];
let resumeHook = null;

class MockAudioNode {{
  constructor(ctx) {{
    this.context = ctx;
    this.gain = {{ value: 1 }};
    this.onaudioprocess = null;
    this.onended = null;
    this.buffer = null;
    this.connectedTo = [];
    this.isStarted = false;
    this.startTime = null;
    this.isStopped = false;
    this.isDisconnected = false;
    mockAudioNodes.push(this);
  }}
  connect(dest) {{
    this.connectedTo.push(dest);
  }}
  disconnect() {{
    this.isDisconnected = true;
  }}
  start(time) {{
    this.isStarted = true;
    this.startTime = time;
  }}
  stop() {{
    this.isStopped = true;
  }}
}}

class MockAudioContext {{
  constructor(opts = {{}}) {{
    this.sampleRate = opts.sampleRate || 24000;
    this.state = 'suspended';
    this.currentTime = 0;
    this.destination = new MockAudioNode(this);
    this.isClosed = false;
    mockAudioContexts.push(this);
  }}

  async resume() {{
    if (resumeHook) {{
      return resumeHook(this);
    }}
    this.state = 'running';
  }}

  async close() {{
    this.state = 'closed';
    this.isClosed = true;
  }}

  createMediaStreamSource(stream) {{
    return new MockAudioNode(this);
  }}

  createScriptProcessor(bufferSize, inChannels, outChannels) {{
    return new MockAudioNode(this);
  }}

  createGain() {{
    return new MockAudioNode(this);
  }}

  createBufferSource() {{
    return new MockAudioNode(this);
  }}

  createBuffer(channels, length, sampleRate) {{
    return {{
      duration: length / sampleRate,
      length,
      sampleRate,
      getChannelData: () => new Float32Array(length)
    }};
  }}
}}
globalThis.AudioContext = MockAudioContext;
globalThis.webkitAudioContext = MockAudioContext;

// --- Mock MediaStream & MediaDevices ---
const mockTracks = [];
class MockMediaTrack {{
  constructor(kind = 'audio') {{
    this.kind = kind;
    this.enabled = true;
    this.stopped = false;
    mockTracks.push(this);
  }}
  stop() {{
    this.stopped = true;
  }}
}}

class MockMediaStream {{
  constructor() {{
    this.tracks = [new MockMediaTrack('audio')];
  }}
  getTracks() {{
    return this.tracks;
  }}
}}

let getUserMediaHook = null;

const navigator = {{
  mediaDevices: {{
    getUserMedia: (constraints) => {{
      if (getUserMediaHook) {{
        return getUserMediaHook(constraints);
      }}
      return Promise.resolve(new MockMediaStream());
    }}
  }}
}};
Object.defineProperty(globalThis, 'navigator', {{
  value: navigator,
  configurable: true,
  writable: true
}});

// Mock URLSearchParams
class MockURLSearchParams {{
  constructor(search) {{}}
  get() {{ return null; }}
}}
globalThis.URLSearchParams = MockURLSearchParams;

// --- Evaluate static/index.html Application Script in Browser Global Context ---
const htmlContent = fs.readFileSync({index_html_json}, 'utf-8');
const scriptStart = htmlContent.lastIndexOf('<script>');
const scriptEnd = htmlContent.lastIndexOf('</script>');
const appScript = htmlContent.slice(scriptStart + 8, scriptEnd);
vm.runInThisContext(appScript);

// --- Test Execution ---
(async () => {{
  try {{
    {js_test_code}
    process.exit(0);
  }} catch (err) {{
    console.error(err);
    process.exit(1);
  }}
}})();
"""

    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", encoding="utf-8", delete=False) as tf:
        tf.write(harness)
        temp_path = Path(tf.name)

    try:
        res = subprocess.run(
            [node_bin, str(temp_path)],
            capture_output=True,
            text=True,
            cwd=str(INDEX_HTML_PATH.parent.parent),
            timeout=10,
        )
        if res.returncode != 0:
            pytest.fail(f"Node script execution failed (code {res.returncode}):\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass

    stdout_lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
    for line in reversed(stdout_lines):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue

    pytest.fail(f"Could not parse JSON output from Node test:\nOutput was:\n{res.stdout}\nSTDERR:\n{res.stderr}")


def test_fallback_acknowledgement_tears_down_voice_and_mic():
    """
    When init_ack arrives with status 'fallback', voice session must be completely
    torn down, mic tracks stopped, audio contexts closed, socket closed, UI reset to
    default, and conversational history/preferences preserved.
    """
    js = """
    // Seed existing conversation and preferences
    window.chatState.conversation_history.push({ role: 'user', content: 'I like subtle mysteries' });
    window.chatState.tone = 'witty';
    window.chatState.pacing = 'deliberate';

    // Start voice session
    const togglePromise = window.toggleSingleBrainVoice();

    // Verify initial connecting state
    const connectingState = window.getVoiceState();
    const btnLabelEl = document.getElementById('voice-btn-label');
    const connectingBtnText = btnLabelEl.innerText;

    // Await toggle (getUserMedia resolves)
    await togglePromise;

    const currentSocket = mockSockets[mockSockets.length - 1];
    currentSocket.simulateOpen();

    // Verify media track is active before server ack
    const activeTrack = mockTracks[mockTracks.length - 1];
    const trackStoppedBeforeAck = activeTrack.stopped;

    // Simulate init_ack fallback from server
    currentSocket.simulateMessage({
      type: 'init_ack',
      status: 'fallback',
      live_model: 'gemini-2.5-flash'
    });

    const stateAfterFallback = window.getVoiceState();
    const liveWsAfter = window.getLiveWs();
    const micStreamAfter = window.getMicMediaStream();
    const recordCtxAfter = window.getAudioRecordContext();
    const playbackCtxAfter = window.getActiveAudioPlaybackContext();
    const statusBar = document.getElementById('voice-status-bar');

    console.log(JSON.stringify({
      connectingBtnText,
      trackStoppedBeforeAck,
      trackStoppedAfterFallback: activeTrack.stopped,
      voiceActive: stateAfterFallback.voiceActive,
      isListening: stateAfterFallback.isListening,
      liveWsReady: stateAfterFallback.liveWsReady,
      micReady: stateAfterFallback.micReady,
      dialogue_mode: stateAfterFallback.dialogue_mode,
      liveWsIsNull: liveWsAfter === null,
      micStreamIsNull: micStreamAfter === null,
      recordCtxIsNull: recordCtxAfter === null,
      playbackCtxIsNull: playbackCtxAfter === null,
      statusBarHidden: statusBar.classList.contains('hidden'),
      btnLabel: btnLabelEl.innerText,
      historyLength: window.chatState.conversation_history.length,
      preservedTone: window.chatState.tone,
      preservedPacing: window.chatState.pacing
    }));
    """
    result = _run_voice_js_in_node(js)

    assert result["connectingBtnText"] == "Connecting..."
    assert result["trackStoppedBeforeAck"] is False
    assert result["trackStoppedAfterFallback"] is True
    assert result["voiceActive"] is False
    assert result["isListening"] is False
    assert result["liveWsReady"] is False
    assert result["micReady"] is False
    assert result["dialogue_mode"] == "text"
    assert result["liveWsIsNull"] is True
    assert result["micStreamIsNull"] is True
    assert result["recordCtxIsNull"] is True
    assert result["playbackCtxIsNull"] is True
    assert result["statusBarHidden"] is True
    assert result["btnLabel"] == "Talk to TONI"
    assert result["historyLength"] >= 1
    assert result["preservedTone"] == "witty"
    assert result["preservedPacing"] == "deliberate"


def test_upstream_receiver_failed_tears_down_voice_and_mic():
    """
    When the server sends an error message (e.g. upstream_receiver_failed),
    the frontend must stop microphone capture, release audio contexts, close the
    socket, and reset voice UI to default.
    """
    js = """
    await window.toggleSingleBrainVoice();
    const currentSocket = mockSockets[mockSockets.length - 1];
    currentSocket.simulateOpen();
    currentSocket.simulateMessage({ type: 'init_ack', status: 'ready' });

    const stateWhileListening = window.getVoiceState();
    const activeTrack = mockTracks[mockTracks.length - 1];

    // Simulate upstream_receiver_failed error from backend
    currentSocket.simulateMessage({
      type: 'error',
      error: 'upstream_receiver_failed'
    });

    const stateAfterError = window.getVoiceState();
    const liveWsAfter = window.getLiveWs();
    const micStreamAfter = window.getMicMediaStream();
    const recordCtxAfter = window.getAudioRecordContext();
    const playbackCtxAfter = window.getActiveAudioPlaybackContext();
    const btnLabel = document.getElementById('voice-btn-label').innerText;
    const statusBarHidden = document.getElementById('voice-status-bar').classList.contains('hidden');

    console.log(JSON.stringify({
      wasListening: stateWhileListening.isListening,
      voiceActive: stateAfterError.voiceActive,
      isListening: stateAfterError.isListening,
      liveWsReady: stateAfterError.liveWsReady,
      micReady: stateAfterError.micReady,
      dialogue_mode: stateAfterError.dialogue_mode,
      trackStopped: activeTrack.stopped,
      liveWsIsNull: liveWsAfter === null,
      micStreamIsNull: micStreamAfter === null,
      recordCtxIsNull: recordCtxAfter === null,
      playbackCtxIsNull: playbackCtxAfter === null,
      btnLabel,
      statusBarHidden
    }));
    """
    result = _run_voice_js_in_node(js)

    assert result["wasListening"] is True
    assert result["voiceActive"] is False
    assert result["isListening"] is False
    assert result["liveWsReady"] is False
    assert result["micReady"] is False
    assert result["dialogue_mode"] == "text"
    assert result["trackStopped"] is True
    assert result["liveWsIsNull"] is True
    assert result["micStreamIsNull"] is True
    assert result["recordCtxIsNull"] is True
    assert result["playbackCtxIsNull"] is True
    assert result["btnLabel"] == "Talk to TONI"
    assert result["statusBarHidden"] is True


def test_socket_error_and_closure_teardown():
    """
    WebSocket errors or abrupt closures must trigger clean teardown of
    microphone capture, playback context, and UI state.
    """
    js = """
    // Case 1: WebSocket error
    await window.toggleSingleBrainVoice();
    let socket = mockSockets[mockSockets.length - 1];
    let track = mockTracks[mockTracks.length - 1];

    socket.simulateError(new Error('Socket transport error'));

    const stateAfterError = window.getVoiceState();
    const trackStoppedAfterError = track.stopped;

    // Case 2: Abrupt WebSocket closure
    await window.toggleSingleBrainVoice();
    socket = mockSockets[mockSockets.length - 1];
    track = mockTracks[mockTracks.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    socket.close();

    const stateAfterClose = window.getVoiceState();
    const trackStoppedAfterClose = track.stopped;

    console.log(JSON.stringify({
      errorVoiceActive: stateAfterError.voiceActive,
      errorTrackStopped: trackStoppedAfterError,
      closeVoiceActive: stateAfterClose.voiceActive,
      closeTrackStopped: trackStoppedAfterClose
    }));
    """
    result = _run_voice_js_in_node(js)

    assert result["errorVoiceActive"] is False
    assert result["errorTrackStopped"] is True
    assert result["closeVoiceActive"] is False
    assert result["closeTrackStopped"] is True


def test_microphone_permission_denial_teardown():
    """
    When getUserMedia rejects (e.g. user denied mic access), voice session
    must be torn down cleanly, socket closed, and UI reset.
    """
    js = """
    getUserMediaHook = () => Promise.reject(new Error('NotAllowedError: Permission denied'));

    await window.toggleSingleBrainVoice();

    const state = window.getVoiceState();
    const liveWs = window.getLiveWs();
    const btnLabel = document.getElementById('voice-btn-label').innerText;
    const statusBarHidden = document.getElementById('voice-status-bar').classList.contains('hidden');

    console.log(JSON.stringify({
      voiceActive: state.voiceActive,
      isListening: state.isListening,
      dialogue_mode: state.dialogue_mode,
      liveWsIsNull: liveWs === null,
      btnLabel,
      statusBarHidden
    }));
    """
    result = _run_voice_js_in_node(js)

    assert result["voiceActive"] is False
    assert result["isListening"] is False
    assert result["dialogue_mode"] == "text"
    assert result["liveWsIsNull"] is True
    assert result["btnLabel"] == "Talk to TONI"
    assert result["statusBarHidden"] is True


def test_delayed_microphone_permission_does_not_reactivate_capture():
    """
    If user starts voice session, then toggles off or restarts before getUserMedia resolves:
    When getUserMedia finally resolves, the acquired stream must be immediately stopped and
    never assigned to module-level state, preventing rogue microphone capture.
    """
    js = """
    let resolveMediaPromise = null;
    getUserMediaHook = () => new Promise((resolve) => {
      resolveMediaPromise = resolve;
    });

    // Start voice session (gen 1)
    const voicePromise = window.toggleSingleBrainVoice();

    // User immediately toggles voice off before permission resolves
    window.teardownVoiceSession();

    const stateAfterTeardown = window.getVoiceState();

    // Now simulated permission finally resolves
    const lateStream = new MockMediaStream();
    const lateTrack = lateStream.getTracks()[0];
    resolveMediaPromise(lateStream);

    await voicePromise;

    const stateAfterLateResolution = window.getVoiceState();
    const micStream = window.getMicMediaStream();
    const recordCtx = window.getAudioRecordContext();

    console.log(JSON.stringify({
      teardownActive: stateAfterTeardown.voiceActive,
      lateActive: stateAfterLateResolution.voiceActive,
      lateTrackStopped: lateTrack.stopped,
      micStreamIsNull: micStream === null,
      recordCtxIsNull: recordCtx === null
    }));
    """
    result = _run_voice_js_in_node(js)

    assert result["teardownActive"] is False
    assert result["lateActive"] is False
    assert result["lateTrackStopped"] is True
    assert result["micStreamIsNull"] is True
    assert result["recordCtxIsNull"] is True


def test_readiness_ordering_both_paths():
    """
    Verifies that listening readiness is ONLY presented when BOTH the live WebSocket
    and the microphone are ready, regardless of which one completes first.

    Path A: Microphone ready first, live WebSocket init_ack ready second.
    Path B: Live WebSocket init_ack ready first, microphone ready second.
    """
    js = """
    // --- Path A: Mic resolves first, Socket ready second ---
    let resolveMediaA = null;
    getUserMediaHook = () => new Promise((resolve) => { resolveMediaA = resolve; });

    const togglePromiseA = window.toggleSingleBrainVoice();
    const socketA = mockSockets[mockSockets.length - 1];

    // Resolve mic first
    const streamA = new MockMediaStream();
    resolveMediaA(streamA);
    await togglePromiseA;

    const stateA1 = window.getVoiceState();
    const statusTextA1 = document.getElementById('voice-status-text').innerText;

    // Now socket init_ack resolves
    socketA.simulateOpen();
    socketA.simulateMessage({ type: 'init_ack', status: 'ready' });

    const stateA2 = window.getVoiceState();
    const statusTextA2 = document.getElementById('voice-status-text').innerText;

    // Teardown before Path B
    window.teardownVoiceSession();

    // --- Path B: Socket ready first, Mic resolves second ---
    let resolveMediaB = null;
    getUserMediaHook = () => new Promise((resolve) => { resolveMediaB = resolve; });

    const togglePromiseB = window.toggleSingleBrainVoice();
    const socketB = mockSockets[mockSockets.length - 1];

    // Socket connects and acknowledges ready before mic resolves
    socketB.simulateOpen();
    socketB.simulateMessage({ type: 'init_ack', status: 'ready' });

    const stateB1 = window.getVoiceState();
    const statusTextB1 = document.getElementById('voice-status-text').innerText;

    // Now mic finally resolves
    const streamB = new MockMediaStream();
    resolveMediaB(streamB);
    await togglePromiseB;

    const stateB2 = window.getVoiceState();
    const statusTextB2 = document.getElementById('voice-status-text').innerText;

    console.log(JSON.stringify({
      // Path A checks
      pathA_micOnly_listening: stateA1.isListening,
      pathA_micOnly_liveWsReady: stateA1.liveWsReady,
      pathA_micOnly_micReady: stateA1.micReady,
      pathA_micOnly_statusText: statusTextA1,
      pathA_bothReady_listening: stateA2.isListening,
      pathA_bothReady_statusText: statusTextA2,

      // Path B checks
      pathB_wsOnly_listening: stateB1.isListening,
      pathB_wsOnly_liveWsReady: stateB1.liveWsReady,
      pathB_wsOnly_micReady: stateB1.micReady,
      pathB_wsOnly_statusText: statusTextB1,
      pathB_bothReady_listening: stateB2.isListening,
      pathB_bothReady_statusText: statusTextB2
    }));
    """
    result = _run_voice_js_in_node(js)

    # Path A: Mic first
    assert result["pathA_micOnly_listening"] is False
    assert result["pathA_micOnly_micReady"] is True
    assert result["pathA_micOnly_liveWsReady"] is False
    assert "Connecting" in result["pathA_micOnly_statusText"]
    assert result["pathA_bothReady_listening"] is True
    assert result["pathA_bothReady_statusText"] == "Listening..."

    # Path B: WebSocket first
    assert result["pathB_wsOnly_listening"] is False
    assert result["pathB_wsOnly_liveWsReady"] is True
    assert result["pathB_wsOnly_micReady"] is False
    assert "microphone" in result["pathB_wsOnly_statusText"].lower()
    assert result["pathB_bothReady_listening"] is True
    assert result["pathB_bothReady_statusText"] == "Listening..."


def test_successful_retry_and_stale_callbacks_ignored():
    """
    Ensures that when a session fails (e.g. fallback or socket error), and the user retries,
    callbacks, messages, or errors from the old socket or old audio nodes are completely
    ignored and never perturb the new active session.
    """
    js = """
    // Session 1: Started and fails with fallback
    await window.toggleSingleBrainVoice();
    const socket1 = mockSockets[mockSockets.length - 1];
    socket1.simulateOpen();
    socket1.simulateMessage({ type: 'init_ack', status: 'fallback' });

    const genAfterFail = window.getVoiceState().voiceSessionGeneration;

    // User retries: Session 2 succeeds
    await window.toggleSingleBrainVoice();
    const socket2 = mockSockets[mockSockets.length - 1];
    socket2.simulateOpen();
    socket2.simulateMessage({ type: 'init_ack', status: 'ready' });

    const stateActive = window.getVoiceState();

    // Now fire late events on the OLD socket1
    socket1.simulateMessage({ type: 'error', error: 'late_upstream_failure' });
    socket1.simulateError(new Error('late error'));
    socket1.close();

    const stateAfterOldSocketEvents = window.getVoiceState();

    console.log(JSON.stringify({
      genAfterFail,
      session2Active: stateActive.voiceActive,
      session2Listening: stateActive.isListening,
      session2Gen: stateActive.voiceSessionGeneration,
      stillActiveAfterOldEvents: stateAfterOldSocketEvents.voiceActive,
      stillListeningAfterOldEvents: stateAfterOldSocketEvents.isListening,
      currentGenUnchanged: stateAfterOldSocketEvents.voiceSessionGeneration === stateActive.voiceSessionGeneration
    }));
    """
    result = _run_voice_js_in_node(js)

    assert result["session2Active"] is True
    assert result["session2Listening"] is True
    assert result["stillActiveAfterOldEvents"] is True
    assert result["stillListeningAfterOldEvents"] is True
    assert result["currentGenUnchanged"] is True


def test_microphone_processing_gated_on_both_readiness():
    """
    Verifies that onaudioprocess strictly gates audio sending so that no audio
    packets are transmitted over WebSocket until BOTH mic and server are ready.
    """
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();

    const processor = window.getAudioWorkletOrProcessor();
    const fakeAudioEvent = {
      inputBuffer: {
        getChannelData: () => new Float32Array(4096)
      }
    };

    // Before init_ack ready: call onaudioprocess
    processor.onaudioprocess(fakeAudioEvent);
    const audioMessagesBeforeReady = socket.sentMessages.filter(m => m.type === 'audio').length;

    // Server acknowledges ready
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    // After ready: call onaudioprocess
    processor.onaudioprocess(fakeAudioEvent);
    const audioMessagesAfterReady = socket.sentMessages.filter(m => m.type === 'audio').length;

    console.log(JSON.stringify({
      audioMessagesBeforeReady,
      audioMessagesAfterReady
    }));
    """
    result = _run_voice_js_in_node(js)

    assert result["audioMessagesBeforeReady"] == 0
    assert result["audioMessagesAfterReady"] == 1


def test_playback_context_closed_and_callbacks_invalidated():
    """
    Verifies that playback AudioContext is closed on teardown, and any delayed source.onended
    callbacks from a previous generation do not transition UI state or modify playback time.
    """
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    // Simulate incoming audio chunk (starts playback node)
    socket.simulateMessage({
      type: 'audio',
      data: Buffer.from(new Uint8Array(4800)).toString('base64')
    });

    const playbackCtx = window.getAudioPlaybackContext();
    const activeNodes = mockAudioNodes.filter(n => n.buffer !== null);
    const lastNode = activeNodes[activeNodes.length - 1];

    // Capture old onended callback
    const oldOnEnded = lastNode.onended;

    // Teardown voice session
    window.teardownVoiceSession();

    const playbackCtxClosed = playbackCtx.isClosed;

    // Simulate old onended firing late after teardown
    if (oldOnEnded) {
      oldOnEnded();
    }

    const voiceStateAfterLateEnded = window.getVoiceState();
    const btnLabel = document.getElementById('voice-btn-label').innerText;

    console.log(JSON.stringify({
      playbackCtxClosed,
      voiceActive: voiceStateAfterLateEnded.voiceActive,
      isListening: voiceStateAfterLateEnded.isListening,
      btnLabel
    }));
    """
    result = _run_voice_js_in_node(js)

    assert result["playbackCtxClosed"] is True
    assert result["voiceActive"] is False
    assert result["isListening"] is False
    assert result["btnLabel"] == "Talk to TONI"


def test_actual_playback_under_browser_global_semantics():
    """
    Verifies that under browser-equivalent global semantics (window === globalThis):
    1. Production getAudioPlaybackContext is preserved as a factory function and not overwritten by an accessor.
    2. Incoming audio over WebSocket creates a playback AudioContext and starts a buffer source node.
    3. UI transitions to responding state while playing and returns to listening when ended.
    """
    js = """
    const isWindowGlobalThis = (window === globalThis);
    const isSelfGlobalThis = (self === globalThis);
    const isProductionFnPreserved = (typeof window.getAudioPlaybackContext === 'function') &&
      (window.getAudioPlaybackContext.toString().includes('AudioCtx'));

    // Before incoming audio: no playback context exists yet
    const activeCtxBeforeAudio = window.getActiveAudioPlaybackContext();

    // Start voice session and acknowledge ready
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    // Simulate incoming audio chunk (PCM16 base64)
    const samplePcm16 = new Int16Array(2400); // 0.1s chunk at 24kHz
    for (let i = 0; i < samplePcm16.length; i++) samplePcm16[i] = Math.sin(i / 10) * 10000;
    const base64Audio = Buffer.from(samplePcm16.buffer).toString('base64');

    socket.simulateMessage({
      type: 'audio',
      data: base64Audio
    });

    // Incoming audio chunk must have invoked production getAudioPlaybackContext()
    const activeCtxAfterAudio = window.getActiveAudioPlaybackContext();
    const isCtxCreated = (activeCtxAfterAudio !== null && activeCtxAfterAudio.state === 'running');

    // Buffer source must be created and started
    const startedSources = mockAudioNodes.filter(n => n.buffer !== null && n.isStarted);
    const startedSourceCount = startedSources.length;
    const isToniSpeakingDuring = window.getVoiceState().isToniSpeaking;
    const btnLabelDuring = document.getElementById('voice-btn-label').innerText;
    const statusTextDuring = document.getElementById('voice-status-text').innerText;

    // Simulate playback completing via onended
    if (startedSources.length > 0 && startedSources[0].onended) {
      startedSources[0].onended();
    }

    const isToniSpeakingAfter = window.getVoiceState().isToniSpeaking;
    const isListeningAfter = window.getVoiceState().isListening;
    const statusTextAfter = document.getElementById('voice-status-text').innerText;

    console.log(JSON.stringify({
      isWindowGlobalThis,
      isSelfGlobalThis,
      isProductionFnPreserved,
      activeCtxBeforeIsNull: activeCtxBeforeAudio === null,
      isCtxCreated,
      startedSourceCount,
      isToniSpeakingDuring,
      btnLabelDuring,
      statusTextDuring,
      isToniSpeakingAfter,
      isListeningAfter,
      statusTextAfter
    }));
    """
    result = _run_voice_js_in_node(js)

    assert result["isWindowGlobalThis"] is True
    assert result["isSelfGlobalThis"] is True
    assert result["isProductionFnPreserved"] is True
    assert result["activeCtxBeforeIsNull"] is True
    assert result["isCtxCreated"] is True
    assert result["startedSourceCount"] == 1
    assert result["isToniSpeakingDuring"] is True
    assert result["btnLabelDuring"] == "TONI is responding..."
    assert result["statusTextDuring"] == "TONI is responding..."
    assert result["isToniSpeakingAfter"] is False
    assert result["isListeningAfter"] is True
    assert result["statusTextAfter"] == "Listening..."


def test_cancellation_while_recording_context_resume_unresolved():
    """
    Verifies that pending microphone setup resources are tracked by voice-session ownership,
    and cancelling teardownVoiceSession immediately stops acquired media tracks and closes
    the recording context, even while AudioContext.resume() is awaiting completion and never resolves.
    """
    js = """
    // AudioContext.resume() returns a Promise that never resolves
    let resumePromiseNeverResolves = new Promise(() => {});
    resumeHook = (ctx) => resumePromiseNeverResolves;

    // Start voice session (gen 1)
    const voicePromise = window.toggleSingleBrainVoice();
    // Allow getUserMedia and AudioContext creation to complete
    await new Promise(r => setTimeout(r, 25));

    // Inspect pending setup state while resume remains pending
    const pendingSetups = window.getPendingMicSetups();
    const hasPendingGen1 = pendingSetups.has(1);
    const pending1 = pendingSetups.get(1);

    const stream1 = pending1 ? pending1.stream : null;
    const track1 = stream1 ? stream1.getTracks()[0] : null;
    const recordCtx1 = pending1 ? pending1.recordContext : null;

    const track1StoppedBefore = track1 ? track1.stopped : null;
    const recordCtx1ClosedBefore = recordCtx1 ? recordCtx1.isClosed : null;

    // While resume() is still awaiting completion, user cancels or teardown is triggered
    window.teardownVoiceSession(1);

    // Verify cancellation immediately stopped acquired tracks and closed context
    const track1StoppedAfter = track1 ? track1.stopped : null;
    const recordCtx1ClosedAfter = recordCtx1 ? recordCtx1.isClosed : null;
    const hasPendingGen1After = pendingSetups.has(1);
    const voiceState = window.getVoiceState();

    console.log(JSON.stringify({
      hasPendingGen1,
      track1StoppedBefore,
      recordCtx1ClosedBefore,
      track1StoppedAfter,
      recordCtx1ClosedAfter,
      hasPendingGen1After,
      voiceActive: voiceState.voiceActive,
      micReady: voiceState.micReady
    }));
    """
    result = _run_voice_js_in_node(js)

    assert result["hasPendingGen1"] is True
    assert result["track1StoppedBefore"] is False
    assert result["recordCtx1ClosedBefore"] is False
    assert result["track1StoppedAfter"] is True
    assert result["recordCtx1ClosedAfter"] is True
    assert result["hasPendingGen1After"] is False
    assert result["voiceActive"] is False
    assert result["micReady"] is False


def test_successful_retry_followed_by_old_resume_resolving_or_rejecting():
    """
    Verifies that when a session's resume hangs and is cancelled, a subsequent retry session
    starts successfully, and late resolution or rejection of the old resume does not affect
    the newer session's microphone tracks, audio context, or readiness state.
    """
    js = """
    // Step 1: Session 1 has a slow/pending resume
    let resolveOldResume1 = null;
    let rejectOldResume1 = null;

    resumeHook = (ctx) => {
      return new Promise((resolve, reject) => {
        resolveOldResume1 = () => { ctx.state = 'running'; resolve(); };
        rejectOldResume1 = (err) => reject(err);
      });
    };

    const voicePromise1 = window.toggleSingleBrainVoice();
    await new Promise(r => setTimeout(r, 25));

    const pendingSetups = window.getPendingMicSetups();
    const pending1 = pendingSetups.get(1);
    const track1 = pending1 ? pending1.stream.getTracks()[0] : null;
    const recordCtx1 = pending1 ? pending1.recordContext : null;

    // Cancel Session 1 while resume() is still pending
    window.teardownVoiceSession(1);
    const track1StoppedOnCancel = track1 ? track1.stopped : null;
    const recordCtx1ClosedOnCancel = recordCtx1 ? recordCtx1.isClosed : null;

    // Step 2: User retries -> Session 2 starts (generation 2) with normal resume
    resumeHook = null;
    await window.toggleSingleBrainVoice();
    await new Promise(r => setTimeout(r, 25));

    const socket2 = mockSockets[mockSockets.length - 1];
    socket2.simulateOpen();
    socket2.simulateMessage({ type: 'init_ack', status: 'ready' });

    const state2Before = window.getVoiceState();
    const micStream2 = window.getMicMediaStream();
    const track2 = micStream2 ? micStream2.getTracks()[0] : null;
    const recordCtx2 = window.getAudioRecordContext();

    const session2ActiveBefore = state2Before.voiceActive;
    const session2ListeningBefore = state2Before.isListening;
    const track2StoppedBefore = track2 ? track2.stopped : null;
    const recordCtx2ClosedBefore = recordCtx2 ? recordCtx2.isClosed : null;

    // Step 3A: Old Session 1's resume now resolves late!
    resolveOldResume1();
    await new Promise(r => setTimeout(r, 25));

    const state2AfterResolve = window.getVoiceState();
    const track2StoppedAfterResolve = track2 ? track2.stopped : null;
    const recordCtx2ClosedAfterResolve = recordCtx2 ? recordCtx2.isClosed : null;
    const micStream2AfterResolve = window.getMicMediaStream();

    // Step 3B: Test another retry cycle where old resume rejects late
    let rejectOldResume3 = null;
    resumeHook = (ctx) => {
      return new Promise((resolve, reject) => {
        rejectOldResume3 = (err) => reject(err);
      });
    };

    // Cleanly tear down session 2
    window.teardownVoiceSession();

    // Start Session 3 (gen 3) with pending resume
    const voicePromise3 = window.toggleSingleBrainVoice();
    await new Promise(r => setTimeout(r, 25));

    // Cancel Session 3
    window.teardownVoiceSession();

    // Start Session 4 (gen 4) retry with immediate resume
    resumeHook = null;
    await window.toggleSingleBrainVoice();
    await new Promise(r => setTimeout(r, 25));

    const socket4 = mockSockets[mockSockets.length - 1];
    socket4.simulateOpen();
    socket4.simulateMessage({ type: 'init_ack', status: 'ready' });

    const state4Before = window.getVoiceState();
    const micStream4 = window.getMicMediaStream();
    const track4 = micStream4 ? micStream4.getTracks()[0] : null;

    // Old Session 3's resume now rejects late
    let lateRejectionError = null;
    try {
      rejectOldResume3(new Error('Old session audio device error'));
      await new Promise(r => setTimeout(r, 25));
    } catch (e) {
      lateRejectionError = e.message;
    }

    const state4AfterReject = window.getVoiceState();
    const track4StoppedAfterReject = track4 ? track4.stopped : null;

    console.log(JSON.stringify({
      track1StoppedOnCancel,
      recordCtx1ClosedOnCancel,
      session2ActiveBefore,
      session2ListeningBefore,
      track2StoppedBefore,
      recordCtx2ClosedBefore,
      session2ActiveAfterResolve: state2AfterResolve.voiceActive,
      session2ListeningAfterResolve: state2AfterResolve.isListening,
      track2StoppedAfterResolve,
      recordCtx2ClosedAfterResolve,
      micStream2Preserved: micStream2AfterResolve === micStream2,
      state4ActiveBefore: state4Before.voiceActive,
      state4ListeningBefore: state4Before.isListening,
      state4ActiveAfterReject: state4AfterReject.voiceActive,
      state4ListeningAfterReject: state4AfterReject.isListening,
      track4StoppedAfterReject,
      lateRejectionError
    }));
    """
    result = _run_voice_js_in_node(js)

    assert result["track1StoppedOnCancel"] is True
    assert result["recordCtx1ClosedOnCancel"] is True
    assert result["session2ActiveBefore"] is True
    assert result["session2ListeningBefore"] is True
    assert result["track2StoppedBefore"] is False
    assert result["recordCtx2ClosedBefore"] is False
    assert result["session2ActiveAfterResolve"] is True
    assert result["session2ListeningAfterResolve"] is True
    assert result["track2StoppedAfterResolve"] is False
    assert result["recordCtx2ClosedAfterResolve"] is False
    assert result["micStream2Preserved"] is True
    assert result["state4ActiveBefore"] is True
    assert result["state4ListeningBefore"] is True
    assert result["state4ActiveAfterReject"] is True
    assert result["state4ListeningAfterReject"] is True
    assert result["track4StoppedAfterReject"] is False
    assert result["lateRejectionError"] is None
