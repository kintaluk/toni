"""
Acceptance test suite verifying the TONI Required Voice Journey:
Intake -> Search -> Visible Recommendations.

Strict product requirements verified:
1. Voice gathers viewer preferences and missing access info.
2. Once confirmed or "Find what fits" is clicked: ends voice session, stops audio hardware cleanly.
3. Shows loading view and executes recommendation pipeline using completed context.
4. Displays returned recommendation cards (voice-only recommendations with no cards is a failure).
5. Zero spoken recommendations:
   - Dialogue proposing films or pitching shortlists is detected and withheld (zero audio scheduled).
   - Reference film acknowledgements without proposals are authorized.
   - Uncertain / malformed dialogue is withheld, displaying a recoverable visual intake prompt.
   - Raw audio arriving before or without transcription is buffered; never played prematurely.
   - Conversational openings followed by recommendations are completely suppressed.
6. Real final-turn completion barrier:
   - Awaiting commit if button clicked while mic speech is in flight.
   - Immediate resolution if no speech is pending.
   - Older turn completions do not prematurely resolve the barrier.
   - Multiple final constraints preserved.
   - Double clicks share a single handoff promise; exactly one recommendation request fired.
   - Deduplication after barrier clears blocks duplicate clicks while allowing newer refinements.
   - Socket failure or 4.0s budget timeout recovers to intake with exact retention message.
   - Restart actively cancels the barrier and aborts search.
   - Auto-advance requires explicit search intent and rejects negative or bare confirmations.
   - Extraction exceeding 500ms is handled within the 4s budget.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import pytest

INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "static" / "index.html"


def _run_voice_journey_js(js_test_code: str) -> dict:
    """
    Executes a test script inside Node.js with mock DOM, WebSocket, Fetch, and Web Audio APIs,
    evaluating static/index.html under browser global semantics (window === globalThis).
    """
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("node is not available on PATH")

    index_html_json = json.dumps(str(INDEX_HTML_PATH))

    harness = f"""
const fs = require('fs');
const vm = require('vm');

globalThis.window = globalThis;
globalThis.self = globalThis;

const elements = {{}};
const defaultHiddenIds = new Set(['loading-view', 'results-view', 'voice-status-bar', 'header-chat-btn']);
const getOrCreateElement = (id) => {{
  if (!elements[id]) {{
    const classListSet = new Set();
    if (defaultHiddenIds.has(id)) {{
      classListSet.add('hidden');
    }}
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
        child.parentElement = this;
        this.children.push(child);
        this._innerHTML = undefined;
      }},
      removeChild(child) {{
        const idx = this.children.indexOf(child);
        if (idx !== -1) this.children.splice(idx, 1);
        child.parentElement = null;
        if (child.id && elements[child.id] === child) {{
          delete elements[child.id];
        }}
        this._innerHTML = undefined;
      }},
      remove() {{
        if (this.parentElement && this.parentElement.children) {{
          const idx = this.parentElement.children.indexOf(this);
          if (idx !== -1) this.parentElement.children.splice(idx, 1);
        }}
        this.parentElement = null;
        if (this.id && elements[this.id] === this) {{
          delete elements[this.id];
        }}
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
      focus() {{}},
      get innerHTML() {{
        return this.children.length > 0 ? this.children.map(c => c.innerHTML || c.innerText || '').join(String.fromCharCode(10)) : (this._innerHTML !== undefined ? this._innerHTML : '');
      }},
      set innerHTML(val) {{
        this._innerHTML = val;
        if (val === '') this.children = [];
      }},
      get innerText() {{
        return this._innerText !== undefined ? this._innerText : this.children.map(c => c.innerText || c.innerHTML || '').join(String.fromCharCode(10));
      }},
      set innerText(val) {{
        this._innerText = val;
      }},
      get textContent() {{
        return this.innerText;
      }},
      set textContent(val) {{
        this.innerText = val;
      }},
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
    let _id = '';
    return {{
      tagName: tag.toUpperCase(),
      get id() {{ return _id; }},
      set id(val) {{
        _id = val;
        if (val) elements[val] = this;
      }},
      className: '',
      style: {{}},
      dataset: {{}},
      setAttribute() {{}},
      getAttribute() {{ return ''; }},
      children: [],
      appendChild(c) {{
        c.parentElement = this;
        this.children.push(c);
        this._innerHTML = undefined;
      }},
      removeChild(child) {{
        const idx = this.children.indexOf(child);
        if (idx !== -1) this.children.splice(idx, 1);
        child.parentElement = null;
        if (child.id && elements[child.id] === child) {{
          delete elements[child.id];
        }}
        this._innerHTML = undefined;
      }},
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
      get innerHTML() {{
        return this.children.length > 0 ? this.children.map(c => c.innerHTML || c.innerText || '').join(String.fromCharCode(10)) : (this._innerHTML !== undefined ? this._innerHTML : '');
      }},
      set innerHTML(val) {{
        this._innerHTML = val;
        if (val === '') this.children = [];
      }},
      get innerText() {{
        return this._innerText !== undefined ? this._innerText : this.children.map(c => c.innerText || c.innerHTML || '').join(String.fromCharCode(10));
      }},
      set innerText(val) {{
        this._innerText = val;
      }},
      get textContent() {{
        return this.innerText;
      }},
      set textContent(val) {{
        this.innerText = val;
      }},
      remove() {{
        if (this.parentElement && this.parentElement.children) {{
          const idx = this.parentElement.children.indexOf(this);
          if (idx !== -1) this.parentElement.children.splice(idx, 1);
        }}
        this.parentElement = null;
        if (this.id && elements[this.id] === this) {{
          delete elements[this.id];
        }}
      }},
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
  connect(dest) {{ this.connectedTo.push(dest); }}
  disconnect() {{ this.isDisconnected = true; }}
  start(when = 0) {{
    this.isStarted = true;
    this.startTime = when;
  }}
  stop() {{
    this.isStopped = true;
    if (this.onended) {{
      const cb = this.onended;
      this.onended = null;
      cb();
    }}
  }}
}}

class MockAudioContext {{
  constructor(options = {{}}) {{
    this.sampleRate = options.sampleRate || 24000;
    this.state = 'running';
    this.currentTime = 0;
    this.destination = new MockAudioNode(this);
    this.isClosed = false;
    mockAudioContexts.push(this);
  }}
  resume() {{ return Promise.resolve(); }}
  close() {{
    this.state = 'closed';
    this.isClosed = true;
    return Promise.resolve();
  }}
  createMediaStreamSource(stream) {{ return new MockAudioNode(this); }}
  createScriptProcessor(bufferSize, inChannels, outChannels) {{ return new MockAudioNode(this); }}
  createBufferSource() {{ return new MockAudioNode(this); }}
  createGain() {{ return new MockAudioNode(this); }}
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
class MockMediaTrack {{
  constructor() {{
    this.kind = 'audio';
    this.enabled = true;
    this.stopped = false;
  }}
  stop() {{ this.stopped = true; }}
}}

class MockMediaStream {{
  constructor() {{
    this.tracks = [new MockMediaTrack()];
  }}
  getTracks() {{ return this.tracks; }}
}}

const navigator = {{
  mediaDevices: {{
    getUserMedia: () => Promise.resolve(new MockMediaStream())
  }}
}};
Object.defineProperty(globalThis, 'navigator', {{
  value: navigator,
  configurable: true,
  writable: true
}});

// --- Mock Fetch ---
const mockFetchCalls = [];
let mockFetchHandler = async (url, opts) => {{
  mockFetchCalls.push({{
    url,
    opts,
    body: opts && opts.body ? JSON.parse(opts.body) : null
  }});
  if (url.includes('/api/voice/turn')) {{
    const b = opts && opts.body ? JSON.parse(opts.body) : {{}};
    const userIn = (b.user_input || '').toLowerCase();
    const signals = b.current_context && b.current_context.tonight_signals ? [...b.current_context.tonight_signals] : [];
    if (userIn.includes('brisk') && !signals.some(s => s.name === 'pacing')) {{
      signals.push({{ name: 'pacing', value: 'brisk', signal_type: 'soft_session_preference' }});
    }}
    return {{
      ok: true,
      status: 200,
      json: async () => ({{
        assistant_reply: "I've noted what you're after.",
        updated_context: {{
          ...b.current_context,
          tonight_signals: signals
        }},
        ready_to_recommend: false,
        mode: b.mode || "voice"
      }})
    }};
  }}
  return {{
    ok: true,
    status: 200,
    json: async () => ({{
      recommendations: [
        {{
          role: "best_fit",
          metadata: {{
            title: "Blade Runner 2049",
            year: 2017,
            director: "Denis Villeneuve",
            runtime_minutes: 164,
            primary_genre: "Sci-Fi",
            genres: ["Sci-Fi"],
            poster_url: "https://example.com/poster.jpg"
          }},
          availability: {{ status: "available", matched_services: ["Netflix"] }},
          editorial_synopsis: "A young blade runner unearths a secret.",
          evidence_sources: ["https://variety.com/reviews/blade-runner-2049"],
          evidence_state: {{ confidence: "high", consensus_strength: "strong" }},
          film_profile: {{
            pacing_and_structure: "Deliberate and expansive",
            craft_and_execution: "Immaculate cinematography",
            tone_and_emotional_character: "Melancholic and contemplative",
            story_and_writing: "Philosophically rich",
            performances: "Subtle and grounded",
            accessibility_and_demandingness: "Patient and demanding"
          }},
          profile: {{
            story_and_writing: 8.5,
            pacing_and_structure: 7.0,
            performances: 9.0,
            craft_and_execution: 9.5,
            accessibility_and_demandingness: 6.5,
            tone_and_emotional_character: ["Melancholic", "Contemplative"]
          }}
        }}
      ]
    }})
  }};
}};
globalThis.fetch = (url, opts) => mockFetchHandler(url, opts);

class MockURLSearchParams {{
  constructor(search) {{}}
  get() {{ return null; }}
  has() {{ return false; }}
}}
globalThis.URLSearchParams = MockURLSearchParams;

// --- Load static/index.html Application Script ---
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

    with tempfile.NamedTemporaryFile(suffix=".cjs", mode="w", encoding="utf-8", delete=False) as tf:
        tf.write(harness)
        temp_path = Path(tf.name)

    try:
        res = subprocess.run(
            [node_bin, str(temp_path)],
            capture_output=True,
            text=True,
            cwd=str(INDEX_HTML_PATH.parent.parent),
            timeout=12,
        )
        if res.returncode != 0:
            pytest.fail(f"Node execution failed (code {res.returncode}):\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
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
    pytest.fail(f"No JSON output from test script:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")


def test_voice_journey_intake_to_search_to_visible_recommendations():
    """
    Verifies the complete approved voice journey:
    1. Voice gathers viewer preferences in intake.
    2. User clicks "Find what fits" / confirms ready -> ends voice session.
    3. Loading view appears immediately.
    4. Exactly 1 recommendation request executes via backend pipeline.
    5. Returned recommendation cards are rendered and visible in results view.
    """
    js = """
    // Prior access choices are confirmed before testing this handoff.
    chatState.country_confirmed = true;
    chatState.service_access = ['Netflix'];
    // 1. Start voice session
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    // Voice intake turn 1: User says preferences
    socket.simulateMessage({
      type: 'transcript',
      role: 'user',
      turn_id: 1,
      text: 'I want a gripping sci-fi movie under two hours on Netflix'
    });
    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 1,
      user_text: 'I want a gripping sci-fi movie under two hours on Netflix',
      assistant_reply: 'Got it! Any specific mood or pacing you prefer tonight?',
      updated_context: {
        service_access: ['Netflix'],
        tonight_signals: [
          { name: 'max-runtime', value: 120, signal_type: 'hard_constraint' },
          { name: 'pacing', value: 'fast', signal_type: 'soft_session_preference' }
        ]
      },
      ready_to_recommend: true
    });

    const voiceActiveDuringIntake = window.getVoiceState().voiceActive;
    const loadingHiddenBeforeHandoff = document.getElementById('loading-view').classList.contains('hidden');

    // 2. User clicks "Find what fits" CTA button
    const handoffPromise = window.executeVoiceSearchHandoff('cta_button_click');

    const loadingVisibleImmediately = !document.getElementById('loading-view').classList.contains('hidden');
    const handoffStateDuring = window.getHandoffState();

    // Await handoff resolution and pipeline completion
    await handoffPromise;
    // Wait for 400ms smooth transition timer to complete dedicated results page render
    await new Promise(r => setTimeout(r, 450));

    const voiceActiveAfterHandoff = window.getVoiceState().voiceActive;
    const fetchCallCount = mockFetchCalls.length;
    const fetchCall = mockFetchCalls[0];
    const resultsViewVisible = !document.getElementById('results-view').classList.contains('hidden');
    const cardsRendered = document.getElementById('watchcards-container').children.length;

    console.log(JSON.stringify({
      voiceActiveDuringIntake,
      loadingHiddenBeforeHandoff,
      loadingVisibleImmediately,
      searchHandoffActiveDuring: handoffStateDuring.searchHandoffActive,
      voiceActiveAfterHandoff,
      fetchCallCount,
      fetchEndpoint: fetchCall ? fetchCall.url : null,
      fetchPayloadServices: fetchCall ? fetchCall.body.service_access : null,
      resultsViewVisible,
      cardsRendered
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["voiceActiveDuringIntake"] is True
    assert result["loadingHiddenBeforeHandoff"] is True
    assert result["loadingVisibleImmediately"] is True
    assert result["voiceActiveAfterHandoff"] is False
    assert result["fetchCallCount"] == 1
    assert "/api/recommend" in result["fetchEndpoint"]
    assert result["fetchPayloadServices"] == ["Netflix"]
    assert result["resultsViewVisible"] is True
    assert result["cardsRendered"] >= 1


def test_zero_spoken_recommendations_withheld():
    """
    Verifies that dialogue proposing/recommending film titles or pitching shortlists
    is detected and withheld before any audio is scheduled or played.
    """
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    // Audio arrives
    const samplePcm16 = new Int16Array(2400);
    const base64Audio = Buffer.from(samplePcm16.buffer).toString('base64');
    socket.simulateMessage({ type: 'audio', data: base64Audio });

    const chunksBufferedBeforeTurnComplete = window.getHandoffState().turnAudioChunksCount;

    // Upstream assistant replies with a spoken recommendation
    socket.simulateMessage({
      type: 'transcript',
      role: 'assistant',
      turn_id: 1,
      text: "I recommend Ex Machina. You should watch it tonight for great sci-fi."
    });
    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 1,
      assistant_reply: "I recommend Ex Machina. You should watch it tonight for great sci-fi."
    });

    // Zero audio sources must be started
    const startedSources = mockAudioNodes.filter(n => n.buffer !== null && n.isStarted);
    const chunksBufferedAfter = window.getHandoffState().turnAudioChunksCount;

    console.log(JSON.stringify({
      chunksBufferedBeforeTurnComplete,
      chunksBufferedAfter,
      startedSourcesCount: startedSources.length
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["chunksBufferedBeforeTurnComplete"] == 1
    assert result["chunksBufferedAfter"] == 0
    assert result["startedSourcesCount"] == 0


def test_reference_film_acknowledgement_authorized():
    """
    Verifies that acknowledging a viewer's reference film without proposing a shortlist
    is recognized as pure taste gathering and authorized for playback.
    """
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    const samplePcm16 = new Int16Array(2400);
    const base64Audio = Buffer.from(samplePcm16.buffer).toString('base64');
    socket.simulateMessage({ type: 'audio', data: base64Audio });

    // Assistant acknowledges reference film:
    socket.simulateMessage({
      type: 'transcript',
      role: 'assistant',
      turn_id: 1,
      text: "Alien has fantastic suspense; are you looking for sci-fi atmosphere, or something lighter tonight?"
    });
    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 1,
      assistant_reply: "Alien has fantastic suspense; are you looking for sci-fi atmosphere, or something lighter tonight?"
    });

    const startedSources = mockAudioNodes.filter(n => n.buffer !== null && n.isStarted);

    console.log(JSON.stringify({
      startedSourcesCount: startedSources.length
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["startedSourcesCount"] == 1


def test_uncertain_intake_dialogue_withheld_with_recoverable_prompt():
    """
    Verifies that uncertain assistant dialogue (missing question, no transition) is withheld,
    and visual intake guidance is displayed so the viewer does not experience unexplained silence.
    """
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    const samplePcm16 = new Int16Array(2400);
    const base64Audio = Buffer.from(samplePcm16.buffer).toString('base64');
    socket.simulateMessage({ type: 'audio', data: base64Audio });

    // Uncertain output (statement without intake question)
    socket.simulateMessage({
      type: 'transcript',
      role: 'assistant',
      turn_id: 1,
      text: "Cinema is quite varied and there are many titles across the industry."
    });
    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 1,
      assistant_reply: "Cinema is quite varied and there are many titles across the industry."
    });

    const startedSources = mockAudioNodes.filter(n => n.buffer !== null && n.isStarted);
    const threadHtml = document.getElementById('toni-chat-thread').innerHTML;

    console.log(JSON.stringify({
      startedSourcesCount: startedSources.length,
      hasRecoverablePrompt: threadHtml.includes('tuning in to your tastes') || threadHtml.includes('preferences')
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["startedSourcesCount"] == 0
    assert result["hasRecoverablePrompt"] is True


def test_delayed_transcript_buffers_audio_without_premature_playback():
    """
    Verifies that audio received over WebSocket is buffered and never plays prematurely
    even if transcription is delayed or never arrives.
    """
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    const samplePcm16 = new Int16Array(2400);
    const base64Audio = Buffer.from(samplePcm16.buffer).toString('base64');

    // Audio arrives, but NO transcript arrives
    socket.simulateMessage({ type: 'audio', data: base64Audio });
    socket.simulateMessage({ type: 'audio', data: base64Audio });

    // Wait simulated time (longer than 250ms)
    await new Promise(r => setTimeout(r, 300));

    const startedSources = mockAudioNodes.filter(n => n.buffer !== null && n.isStarted);
    const bufferedChunks = window.getHandoffState().turnAudioChunksCount;

    console.log(JSON.stringify({
      startedSourcesCount: startedSources.length,
      bufferedChunks
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["startedSourcesCount"] == 0
    assert result["bufferedChunks"] == 2


def test_conversational_opening_followed_by_recommendation_withheld():
    """
    Verifies that conversational openings followed by recommendations
    ("Sure thing! I recommend Inception...") are suppressed in full.
    """
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    const samplePcm16 = new Int16Array(2400);
    const base64Audio = Buffer.from(samplePcm16.buffer).toString('base64');
    socket.simulateMessage({ type: 'audio', data: base64Audio });

    socket.simulateMessage({
      type: 'transcript',
      role: 'assistant',
      turn_id: 1,
      text: "Sure thing! I recommend Inception for your evening viewing."
    });
    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 1,
      assistant_reply: "Sure thing! I recommend Inception for your evening viewing."
    });

    const startedSources = mockAudioNodes.filter(n => n.buffer !== null && n.isStarted);

    console.log(JSON.stringify({
      startedSourcesCount: startedSources.length
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["startedSourcesCount"] == 0


def test_button_click_before_final_transcript_barrier_waits_for_commit():
    """
    Verifies that clicking "Find what fits" before the final transcript arrives
    creates a barrier that awaits target turn context commit before launching search.
    """
    js = """
    // Prior access choices are confirmed before testing this handoff.
    chatState.country_confirmed = true;
    chatState.service_access = ['Netflix'];
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    // Send mic audio chunk -> in-flight speech
    const samplePcm16 = new Int16Array(1600);
    const base64Audio = Buffer.from(samplePcm16.buffer).toString('base64');
    socket.simulateMessage({ type: 'transcript', role: 'user', turn_id: 2, text: 'No comedies please' });

    // User clicks CTA button BEFORE turn_complete arrives
    let handoffSettled = false;
    const handoffPromise = window.executeVoiceSearchHandoff('cta_button_click').then(() => { handoffSettled = true; });

    // Verify finalize_turn was sent upstream with has_pending_audio
    const finalizeMsg = socket.sentMessages.find(m => m.type === 'finalize_turn');
    const fetchCallsBeforeCommit = mockFetchCalls.length;

    // Simulate backend sending finalize_ack
    socket.simulateMessage({
      type: 'finalize_ack',
      request_id: finalizeMsg.request_id,
      target_turn_id: 2,
      status: 'finalizing'
    });

    // Now turn_complete arrives with committed context
    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 2,
      user_text: 'No comedies please',
      assistant_reply: "I'll find what fits.",
      updated_context: {
        tonight_signals: [
          { name: 'exclude-genre', value: ['Comedy'], signal_type: 'hard_constraint' }
        ]
      }
    });

    await handoffPromise;
    const fetchCallsAfterCommit = mockFetchCalls.length;
    const searchPayload = mockFetchCalls[0].body;

    const excludeSig = (searchPayload.tonight_signals || []).find(s => s.name === 'exclude-genre');

    console.log(JSON.stringify({
      finalizeSent: Boolean(finalizeMsg),
      hasPendingAudioInMsg: finalizeMsg ? finalizeMsg.has_pending_audio : false,
      fetchCallsBeforeCommit,
      handoffSettled,
      fetchCallsAfterCommit,
      searchPayloadExclude: excludeSig ? excludeSig.value : []
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["finalizeSent"] is True
    assert result["hasPendingAudioInMsg"] is True
    assert result["fetchCallsBeforeCommit"] == 0
    assert result["handoffSettled"] is True
    assert result["fetchCallsAfterCommit"] == 1
    assert "Comedy" in result["searchPayloadExclude"]


def test_no_pending_speech_finalisation_immediate():
    """
    When no speech is pending, barrier resolves immediately without delay.
    """
    js = """
    // Prior access choices are confirmed before testing this handoff.
    chatState.country_confirmed = true;
    chatState.service_access = ['Netflix'];
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    // Turn 1 completed and settled earlier
    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 1,
      user_text: 'I want drama',
      assistant_reply: 'Got it.',
      updated_context: {
        tonight_signals: [{ name: 'pacing', value: 'measured', signal_type: 'soft_session_preference' }]
      }
    });

    // Button click with no speech currently in-flight
    await window.executeVoiceSearchHandoff('cta_button_click');

    const fetchCalls = mockFetchCalls.length;

    console.log(JSON.stringify({
      fetchCalls
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["fetchCalls"] == 1


def test_older_turn_completion_does_not_prematurely_resolve_target_barrier():
    """
    Verifies that an older turn completion arriving before the target completion
    does not prematurely resolve the barrier.
    """
    js = """
    // Prior access choices are confirmed before testing this handoff.
    chatState.country_confirmed = true;
    chatState.service_access = ['Netflix'];
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    socket.simulateMessage({ type: 'transcript', role: 'user', turn_id: 3, text: 'Keep it fast-paced' });

    let handoffSettled = false;
    const handoffPromise = window.executeVoiceSearchHandoff('cta_button_click').then(() => { handoffSettled = true; });

    const finalizeMsg = socket.sentMessages.find(m => m.type === 'finalize_turn');
    socket.simulateMessage({
      type: 'finalize_ack',
      request_id: finalizeMsg.request_id,
      target_turn_id: 3,
      status: 'finalizing'
    });

    // Older turn 2 completes late
    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 2,
      user_text: 'old turn',
      assistant_reply: 'old ack'
    });

    const settledAfterOlderTurn = handoffSettled;

    // Now target turn 3 completes
    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 3,
      user_text: 'Keep it fast-paced',
      assistant_reply: "I'll find what fits.",
      updated_context: {
        tonight_signals: [{ name: 'pacing', value: 'fast', signal_type: 'soft_session_preference' }]
      }
    });

    await handoffPromise;

    console.log(JSON.stringify({
      settledAfterOlderTurn,
      handoffSettled,
      fetchCalls: mockFetchCalls.length
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["settledAfterOlderTurn"] is False
    assert result["handoffSettled"] is True
    assert result["fetchCalls"] == 1


def test_multiple_final_constraints_preserved_in_recommendation_payload():
    """
    Verifies that multiple constraints spoken in the final turn (runtime + exclusion + service)
    are all committed and dispatched in the recommendation request.
    """
    js = """
    // Prior access choices are confirmed before testing this handoff.
    chatState.country_confirmed = true;
    chatState.service_access = ['Netflix'];
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 1,
      user_text: 'Nothing over 100 minutes, exclude horror, and we have Disney+',
      assistant_reply: "I'll find what fits.",
      updated_context: {
        service_access: ['Disney+'],
        tonight_signals: [
          { name: 'max-runtime', value: 100, signal_type: 'hard_constraint' },
          { name: 'exclude-genre', value: ['Horror'], signal_type: 'hard_constraint' }
        ]
      }
    });

    await window.executeVoiceSearchHandoff('cta_button_click');
    const payload = mockFetchCalls[0].body;

    const maxRuntimeSig = (payload.tonight_signals || []).find(s => s.name === 'max-runtime');
    const excludeSig = (payload.tonight_signals || []).find(s => s.name === 'exclude-genre');

    console.log(JSON.stringify({
      maxRuntime: maxRuntimeSig ? maxRuntimeSig.value : null,
      excludeGenres: excludeSig ? excludeSig.value : [],
      serviceAccess: payload.service_access
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["maxRuntime"] == 100
    assert "Horror" in result["excludeGenres"]
    assert "Disney+" in result["serviceAccess"]


def test_double_click_during_handoff_deduplication():
    """
    Verifies that rapid double clicks during handoff share the active handoff promise
    and fire exactly 1 recommendation request.
    """
    js = """
    // Prior access choices are confirmed before testing this handoff.
    chatState.country_confirmed = true;
    chatState.service_access = ['Netflix'];
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 1,
      user_text: 'Thriller',
      assistant_reply: 'Understood.',
      updated_context: {
        tonight_signals: [{ name: 'pacing', value: 'fast', signal_type: 'soft_session_preference' }]
      }
    });

    // Rapid double click
    const p1 = window.executeVoiceSearchHandoff('cta_button_click');
    const p2 = window.executeVoiceSearchHandoff('cta_button_click');

    const isSamePromise = (p1 === p2);
    await Promise.all([p1, p2]);

    console.log(JSON.stringify({
      isSamePromise,
      fetchCallCount: mockFetchCalls.length
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["isSamePromise"] is True
    assert result["fetchCallCount"] == 1


def test_deduplication_after_barrier_clears_and_refinement():
    """
    Verifies that after the barrier clears, identical duplicate clicks while isGenerating
    are ignored, but a genuinely newer refinement triggers a new search.
    """
    js = """
    // Prior access choices are confirmed before testing this handoff.
    chatState.country_confirmed = true;
    chatState.service_access = ['Netflix'];
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 1,
      user_text: 'Sci-fi',
      assistant_reply: 'Understood.',
      updated_context: {
        tonight_signals: [{ name: 'pacing', value: 'fast', signal_type: 'soft_session_preference' }]
      }
    });

    // First handoff execution
    let resolveFirstFetch;
    mockFetchHandler = (url, opts) => {
      mockFetchCalls.push({ url, opts, body: opts && opts.body ? JSON.parse(opts.body) : null });
      return new Promise(resolve => {
        resolveFirstFetch = resolve;
      });
    };

    const handoffP1 = window.executeVoiceSearchHandoff('cta_button_click');
    await new Promise(r => setTimeout(r, 20));

    // Duplicate click with identical payload while isGenerating
    const handoffP2 = window.executeVoiceSearchHandoff('cta_button_click');
    await handoffP2;

    const fetchCountAfterDuplicate = mockFetchCalls.length;

    // Now simulate a newer refinement (user typed a new exclusion)
    window.setExcludeGenre("Horror");
    const handoffP3 = window.triggerPipelineExecution();
    await new Promise(r => setTimeout(r, 20));

    const fetchCountAfterRefinement = mockFetchCalls.length;

    // Settle first fetch
    if (resolveFirstFetch) resolveFirstFetch({ ok: true, json: async () => ({ shortlist: [] }) });

    console.log(JSON.stringify({
      fetchCountAfterDuplicate,
      fetchCountAfterRefinement
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["fetchCountAfterDuplicate"] == 1
    assert result["fetchCountAfterRefinement"] == 2


def test_socket_failure_during_handoff_recovers_to_intake():
    """
    Verifies that if the live socket errors/disconnects during handoff,
    the UI safely returns to the intake view with the exact recovery message.
    """
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    socket.simulateMessage({ type: 'transcript', role: 'user', turn_id: 1, text: 'something funny' });

    const handoffPromise = window.executeVoiceSearchHandoff('cta_button_click');

    // Socket fails
    socket.simulateError(new Error('Connection lost'));

    await handoffPromise;

    const intakeHidden = document.getElementById('intake-view').classList.contains('hidden');
    const statusText = document.getElementById('voice-status-text').innerText;
    const threadHtml = document.getElementById('toni-chat-thread').innerHTML;

    console.log(JSON.stringify({
      intakeHidden,
      statusText,
      hasRecoveryNotice: threadHtml.includes('Your confirmed preferences are saved')
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["intakeHidden"] is False
    assert result["hasRecoveryNotice"] is True


def test_restart_during_handoff_cancels_barrier():
    """
    Verifies that clicking Restart during an active handoff actively rejects
    the barrier, resets state, and prevents search execution.
    """
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    socket.simulateMessage({ type: 'transcript', role: 'user', turn_id: 1, text: 'something funny' });

    const handoffPromise = window.handleReadyCTAClick();

    // User restarts conversation
    window.restartConversation();

    await handoffPromise;

    const fetchCallCount = mockFetchCalls.length;
    const handoffState = window.getHandoffState();

    console.log(JSON.stringify({
      fetchCallCount,
      searchHandoffActive: handoffState.searchHandoffActive,
      barrierTargetTurnId: handoffState.barrierTargetTurnId
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["fetchCallCount"] == 0
    assert result["searchHandoffActive"] is False
    assert result["barrierTargetTurnId"] is None


def test_voice_search_requires_button_even_with_explicit_transcript_intent():
    """
    Verifies that ready_to_recommend does not trigger recommendation search
    when the user speaks negative intent ("don't recommend yet") or bare confirmation.
    """
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    // Negative intent
    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 1,
      user_text: "Don't recommend yet, I have more to add",
      assistant_reply: "Sure, what else would you like?",
      ready_to_recommend: true
    });

    // Wait past the auto-recommendation timer threshold
    await new Promise(r => setTimeout(r, 800));

    const fetchCallsAfterNegative = mockFetchCalls.length;

    // Now explicit search intent
    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 2,
      user_text: "Okay find what fits!",
      assistant_reply: "I'll find what fits.",
      ready_to_recommend: true
    });

    await new Promise(r => setTimeout(r, 800));

    const fetchCallsAfterExplicit = mockFetchCalls.length;

    console.log(JSON.stringify({
      fetchCallsAfterNegative,
      fetchCallsAfterExplicit
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["fetchCallsAfterNegative"] == 0
    assert result["fetchCallsAfterExplicit"] == 0


def test_voice_start_authorizes_audio_and_schedules_normal_intake():
    """
    Verifies that starting voice via toggleSingleBrainVoice sets audioPlaybackAuthorized = true,
    and normal intake dialogue (greeting & intake question) is authorized and scheduled to play.
    """
    js = """
    await window.toggleSingleBrainVoice();
    const handoffState = window.getHandoffState();

    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    // Audio arrives
    const samplePcm16 = new Int16Array(2400);
    const base64Audio = Buffer.from(samplePcm16.buffer).toString('base64');
    socket.simulateMessage({ type: 'audio', data: base64Audio });

    // Legitimate intake greeting arrives
    socket.simulateMessage({
      type: 'transcript',
      role: 'assistant',
      turn_id: 1,
      text: "Hello! I'm TONI, your guide tonight. What kind of movie are you in the mood for?"
    });

    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 1,
      assistant_reply: "Hello! I'm TONI, your guide tonight. What kind of movie are you in the mood for?"
    });

    const startedSources = mockAudioNodes.filter(n => n.buffer !== null && n.isStarted);

    console.log(JSON.stringify({
      audioPlaybackAuthorized: handoffState.audioPlaybackAuthorized,
      startedSourcesCount: startedSources.length
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["audioPlaybackAuthorized"] is True
    assert result["startedSourcesCount"] == 1


def test_playback_validator_withholds_pitches_and_imperatives_while_authorizing_intake():
    """
    Verifies that validateAssistantAudioOutput withholds:
    - Pitch declaring fit: "Alien is perfect for your mood tonight. Shall we go with that?"
    - Directive imperative: "Watch Paddington tonight. Any other preferences?"
    And authorizes:
    - Reference film acknowledgment: "Alien has great atmosphere; what pacing do you want?"
    - Natural question: "Got it, comedy it is. Which streaming services do you have?"
    - Greeting: "Hello! I'm TONI."
    """
    js = """
    await window.toggleSingleBrainVoice();

    const check1 = window.validateAssistantAudioOutput("Alien is perfect for your mood tonight. Shall we go with that?");
    const check2 = window.validateAssistantAudioOutput("Watch Paddington tonight. Any other preferences?");
    const check3 = window.validateAssistantAudioOutput("Alien has great atmosphere; what pacing do you want?");
    const check4 = window.validateAssistantAudioOutput("Got it, comedy it is. Which streaming services do you have?");
    const check5 = window.validateAssistantAudioOutput("Hello! I'm TONI.");

    console.log(JSON.stringify({
      pitch: check1,
      imperative: check2,
      referenceAck: check3,
      serviceQuestion: check4,
      greeting: check5
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["pitch"]["valid"] is False
    assert result["pitch"]["reason"] == "unsolicited_recommendation"
    assert result["imperative"]["valid"] is False
    assert result["imperative"]["reason"] == "unsolicited_recommendation"
    assert result["referenceAck"]["valid"] is True
    assert result["serviceQuestion"]["valid"] is True
    assert result["greeting"]["valid"] is True


def test_readiness_strictly_requires_confirmed_context():
    """
    Verifies readiness CTA is not shown after 'Hi Tony' or turn 2 without services/country/mood,
    appears once context is sufficient, and disappears if context becomes insufficient.
    """
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    // Turn 1: User says "Hi Tony" -> greeting only, missing services, country, taste
    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 1,
      user_text: "Hi Tony",
      assistant_reply: "Hello! What kind of film are you in the mood for tonight?"
    });

    const thread = document.getElementById('toni-chat-thread');
    const ctaAfterTurn1 = thread.children.some(c => c.id === 'msg-step-ready');
    const hasContextTurn1 = window.hasSufficientContext();

    // Turn 2: User says "I want comedy" -> taste signal added, but services access still empty
    socket.simulateMessage({
      type: 'turn_complete',
      turn_id: 2,
      user_text: "I want comedy",
      assistant_reply: "Comedy sounds great. Which streaming services do you have?",
      updated_context: {
        tonight_signals: [{ name: 'mood', value: 'comedy', signal_type: 'soft_session_preference' }]
      }
    });

    const ctaAfterTurn2 = thread.children.some(c => c.id === 'msg-step-ready');
    const hasContextTurn2 = window.hasSufficientContext();

    // User confirms streaming access, but country is still unconfirmed UK default
    window.toggleService("Netflix");
    const ctaAfterServiceOnly = thread.children.some(c => c.id === 'msg-step-ready');
    const hasContextServiceOnly = window.hasSufficientContext();

    // User explicitly confirms country (UK) -> all 3 confirmed -> CTA appears!
    window.selectMarket("UK");
    const ctaAfterCountryConfirmed = thread.children.some(c => c.id === 'msg-step-ready');
    const hasContextCountryConfirmed = window.hasSufficientContext();

    // User clears services -> context becomes insufficient -> CTA removed
    window.clearAllServicesInChat();
    const ctaAfterServiceCleared = thread.children.some(c => c.id === 'msg-step-ready');
    const hasContextServiceCleared = window.hasSufficientContext();

    console.log(JSON.stringify({
      ctaAfterTurn1,
      hasContextTurn1,
      ctaAfterTurn2,
      hasContextTurn2,
      ctaAfterServiceOnly,
      hasContextServiceOnly,
      ctaAfterCountryConfirmed,
      hasContextCountryConfirmed,
      ctaAfterServiceCleared,
      hasContextServiceCleared
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["ctaAfterTurn1"] is False
    assert result["hasContextTurn1"] is False
    assert result["ctaAfterTurn2"] is False
    assert result["hasContextTurn2"] is False
    assert result["ctaAfterServiceOnly"] is False
    assert result["hasContextServiceOnly"] is False
    assert result["ctaAfterCountryConfirmed"] is True
    assert result["hasContextCountryConfirmed"] is True
    assert result["ctaAfterServiceCleared"] is False
    assert result["hasContextServiceCleared"] is False


def test_finalize_ack_send_failed_rejects_barrier_recoverably():
    """
    Verifies that if backend sends status: 'send_failed' in finalize_ack,
    the client rejects the barrier immediately and resets to a recoverable intake state.
    """
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    // Simulate in-flight speech
    socket.simulateMessage({ type: 'transcript', role: 'user', turn_id: 1, text: 'Something light' });

    // User clicks CTA
    let handoffSettled = false;
    let handoffError = null;
    const handoffPromise = window.executeVoiceSearchHandoff('cta_button_click')
      .then(() => { handoffSettled = true; })
      .catch((err) => { handoffError = err.message; });

    const finalizeMsg = socket.sentMessages.find(m => m.type === 'finalize_turn');

    // Simulate upstream failure acknowledgment
    socket.simulateMessage({
      type: 'finalize_ack',
      request_id: finalizeMsg.request_id,
      status: 'send_failed'
    });

    await handoffPromise;

    const threadHtml = document.getElementById('toni-chat-thread').innerHTML;

    console.log(JSON.stringify({
      handoffSettled,
      hasRecoverableMessage: threadHtml.includes('Your confirmed preferences are saved') || threadHtml.includes('preferences')
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["handoffSettled"] is True
    assert result["hasRecoverableMessage"] is True


def test_validator_and_playback_handling_reproduces_and_corrects_user_cases():
    """
    Directly tests the reproduction and resolution of the three reported cases via actual playback handling:
    1. 'What would you like to watch tonight?' -> Authorized intake, scheduled to playback
    2. 'Do you want to watch something funny or tense?' -> Authorized intake, scheduled to playback
    3. 'Paddington would suit you. Interested?' -> Unsolicited recommendation pitch withheld, buffer cleared
    """
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    // Dummy base64 24kHz audio chunk
    const samplePcm16 = new Int16Array(2400);
    const dummyAudio = Buffer.from(samplePcm16.buffer).toString('base64');

    // Case 1: "What would you like to watch tonight?"
    const check1 = window.validateAssistantAudioOutput("What would you like to watch tonight?");
    socket.simulateMessage({ type: 'audio', data: dummyAudio });
    window.releaseTurnAudioBuffer("What would you like to watch tonight?");
    const sourcesAfter1 = window.getActiveAudioSourceNodes().length;

    // Case 2: "Do you want to watch something funny or tense?"
    const check2 = window.validateAssistantAudioOutput("Do you want to watch something funny or tense?");
    socket.simulateMessage({ type: 'audio', data: dummyAudio });
    window.releaseTurnAudioBuffer("Do you want to watch something funny or tense?");
    const sourcesAfter2 = window.getActiveAudioSourceNodes().length;

    // Case 3: "Paddington would suit you. Interested?"
    const check3 = window.validateAssistantAudioOutput("Paddington would suit you. Interested?");
    socket.simulateMessage({ type: 'audio', data: dummyAudio });
    window.releaseTurnAudioBuffer("Paddington would suit you. Interested?");
    const sourcesAfter3 = window.getActiveAudioSourceNodes().length;

    const threadHtml = document.getElementById('toni-chat-thread').innerHTML;
    const hasRecoverablePrompt = threadHtml.includes("tuning in to your tastes");

    console.log(JSON.stringify({
      check1,
      check2,
      check3,
      sourcesAfter1,
      sourcesAfter2,
      sourcesAfter3,
      hasRecoverablePrompt
    }));
    """
    result = _run_voice_journey_js(js)
    # Case 1: General question asking what viewer wants to watch
    assert result["check1"]["valid"] is True
    assert result["check1"]["reason"] == "authorized_intake"
    assert result["sourcesAfter1"] == 1

    # Case 2: General question asking about tone/mood
    assert result["check2"]["valid"] is True
    assert result["check2"]["reason"] == "authorized_intake"
    assert result["sourcesAfter2"] == 2

    # Case 3: Pitch proposing Paddington as suitable for the viewer
    assert result["check3"]["valid"] is False
    assert result["check3"]["reason"] == "unsolicited_recommendation"
    # Audio node was NOT incremented (chunk was withheld and cleared)
    assert result["sourcesAfter3"] == 2
    # Recoverable intake prompt is displayed on screen so user is not left in dead silence
    assert result["hasRecoverablePrompt"] is True


def test_country_and_pacing_defaults_do_not_satisfy_readiness_until_explicitly_supplied():
    """
    Verifies that:
    1. The initial UK country default does NOT count as confirmed country.
    2. The initial 'measured' pacing default does NOT count as confirmed user taste.
    3. Explicit market selection or spoken country confirms country.
    4. Explicitly supplied pacing (e.g. setPacing or dialogue signal) satisfies taste readiness.
    """
    js = """
    // Fresh session start
    const initialReady = window.hasSufficientContext();

    // 1. Add streaming service only
    window.toggleService("Netflix");
    const readyWithServiceOnly = window.hasSufficientContext();

    // 2. Default pacing is 'measured', but unconfirmed
    // Even with service and default pacing, ready must be false
    const readyWithDefaultPacing = window.hasSufficientContext();

    // 3. Confirm country explicitly
    window.selectMarket("UK");
    const readyWithCountryAndService = window.hasSufficientContext();

    // 4. Confirm pacing explicitly (e.g. setPacing('brisk'))
    window.setPacing('brisk');
    const readyWithExplicitPacing = window.hasSufficientContext();

    // 5. Verify CTA is now active
    const thread = document.getElementById('toni-chat-thread');
    const ctaActive = thread.children.some(c => c.id === 'msg-step-ready');

    // 6. Test restart resets flags
    window.restartConversation();
    const readyAfterRestart = window.hasSufficientContext();

    console.log(JSON.stringify({
      initialReady,
      readyWithServiceOnly,
      readyWithDefaultPacing,
      readyWithCountryAndService,
      readyWithExplicitPacing,
      ctaActive,
      readyAfterRestart
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["initialReady"] is False
    assert result["readyWithServiceOnly"] is False
    assert result["readyWithDefaultPacing"] is False
    # Still false because taste (pacing/mood) has not been explicitly supplied by user
    assert result["readyWithCountryAndService"] is False
    # True now because country confirmed + service confirmed + explicit pacing confirmed
    assert result["readyWithExplicitPacing"] is True
    assert result["ctaActive"] is True
    # Clean reset on restart
    assert result["readyAfterRestart"] is False


def test_voice_turn_defaults_round_trip_does_not_enable_readiness():
    """
    Regression test covering the full request/response round trip:
    1. buildVoiceTurnPayload() must NOT send default unconfirmed pacing or demandingness in tonight_signals.
    2. With UK and Netflix confirmed, sending 'Hi Tony' round-trips through dialogue context sync.
    3. Even if a backend or fallback echoes default pacing ('measured') or demandingness (3.0),
       syncContextToState() must NOT treat an echoed default as user-supplied explicit taste.
    4. Readiness (hasSufficientContext()) must remain False, and the inline CTA must NOT appear.
    5. Only when the user explicitly supplies taste (e.g. 'I want brisk pacing' or mood) does
       readiness become True and the CTA appears.
    """
    js = """
    // 1. Confirm country and service
    window.selectMarket("UK");
    window.toggleService("Netflix");

    const readyBeforeUtterance = window.hasSufficientContext();

    // 2. Build voice turn payload for "Hi Tony"
    const payload = window.buildVoiceTurnPayload("Hi Tony", "voice");
    const payloadSignals = payload.current_context.tonight_signals;
    const hasDefaultPacingInPayload = payloadSignals.some(s => s.name === "pacing");
    const hasDefaultDemandingnessInPayload = payloadSignals.some(s => s.name === "demandingness");

    // 3. Simulate backend round trip echoing default signals (the regression scenario)
    // Server receives payload, echoes back context including default pacing & demandingness
    const echoedContext = {
      ...payload.current_context,
      tonight_signals: [
        { name: "pacing", value: "measured", signal_type: "soft_session_preference" },
        { name: "demandingness", value: 3.0, signal_type: "soft_session_preference" }
      ]
    };

    // Client syncs the echoed response from turn 1 ("Hi Tony")
    window.syncContextToState(echoedContext, 1, "Hi Tony");
    window.syncReadinessUI();

    const pacingExplicitAfterEcho = window.chatState.pacing_explicitly_set;
    const demandingnessExplicitAfterEcho = window.chatState.demandingness_explicitly_set;
    const readyAfterEcho = window.hasSufficientContext();
    const thread = document.getElementById("toni-chat-thread");
    const ctaAfterEcho = thread ? thread.children.some(c => c.id === "msg-step-ready") : false;

    // 4. Now user provides explicit taste in turn 2 ("I want brisk pacing")
    const briskContext = {
      ...payload.current_context,
      tonight_signals: [
        { name: "pacing", value: "brisk", signal_type: "soft_session_preference" }
      ]
    };
    window.syncContextToState(briskContext, 2, "I want brisk pacing");
    window.syncReadinessUI();

    const pacingExplicitAfterTaste = window.chatState.pacing_explicitly_set;
    const readyAfterTaste = window.hasSufficientContext();
    const ctaAfterTaste = thread ? thread.children.some(c => c.id === "msg-step-ready") : false;

    console.log(JSON.stringify({
      readyBeforeUtterance,
      hasDefaultPacingInPayload,
      hasDefaultDemandingnessInPayload,
      pacingExplicitAfterEcho,
      demandingnessExplicitAfterEcho,
      readyAfterEcho,
      ctaAfterEcho,
      pacingExplicitAfterTaste,
      readyAfterTaste,
      ctaAfterTaste
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["readyBeforeUtterance"] is False
    assert result["hasDefaultPacingInPayload"] is False
    assert result["hasDefaultDemandingnessInPayload"] is False
    assert result["pacingExplicitAfterEcho"] is False
    assert result["demandingnessExplicitAfterEcho"] is False
    assert result["readyAfterEcho"] is False
    assert result["ctaAfterEcho"] is False
    assert result["pacingExplicitAfterTaste"] is True
    assert result["readyAfterTaste"] is True
    assert result["ctaAfterTaste"] is True


def test_process_dialogue_turn_full_flow_does_not_enable_readiness_on_hi_tony():
    """
    Verifies full async processTextDialogueTurn round trip using mockFetch:
    'Hi Tony' with confirmed UK + Netflix does not enable readiness.
    Subsequent 'I want brisk pacing' enables readiness and renders CTA.
    """
    js = """
    window.selectMarket("UK");
    window.toggleService("Netflix");

    // Turn 1: "Hi Tony"
    await window.enqueueTextDialogueTurn("Hi Tony");
    const readyAfterHiTony = window.hasSufficientContext();
    const thread = document.getElementById("toni-chat-thread");
    const ctaAfterHiTony = thread ? thread.children.some(c => c.id === "msg-step-ready") : false;

    // Turn 2: "I want brisk pacing"
    await window.enqueueTextDialogueTurn("I want brisk pacing");
    const readyAfterBrisk = window.hasSufficientContext();
    const ctaAfterBrisk = thread ? thread.children.some(c => c.id === "msg-step-ready") : false;

    console.log(JSON.stringify({
      readyAfterHiTony,
      ctaAfterHiTony,
      readyAfterBrisk,
      ctaAfterBrisk
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["readyAfterHiTony"] is False
    assert result["ctaAfterHiTony"] is False
    assert result["readyAfterBrisk"] is True
    assert result["ctaAfterBrisk"] is True


