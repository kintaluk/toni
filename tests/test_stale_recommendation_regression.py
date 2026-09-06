"""
Behavioral regression tests for TONI stale recommendations, delayed callbacks, and conversation invalidation.

Ensures that:
- Return / Adjust / Refine in chat continues the existing conversation with its history and preferences intact.
- New chat / Start fresh clears history, preferences, constraints, in-flight requests, and results.
- Recommendations triggered after a submitted refinement use the context updated by that dialogue turn.
- Older requests, timers and failures cannot overwrite newer results or alter their loading state.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import pytest

INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "static" / "index.html"


def _run_stale_test_in_node(js_test_code: str) -> dict:
    """
    Executes a test script inside Node.js with mock DOM, Fetch, and Web APIs,
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
    // Default hidden for loading-view and results-view
    if (id === 'loading-view' || id === 'results-view' || id === 'voice-status-bar' || id === 'toni-brand-modal') {{
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
      focus() {{}},
      remove() {{}},
      setAttribute() {{}},
      getAttribute() {{ return ''; }},
      innerHTML: '',
      innerText: '',
      textContent: '',
      value: '',
      offsetWidth: 100,
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

// --- Fetch Mock with Hooks & History ---
let fetchHook = null;
const mockFetchCalls = [];

globalThis.fetch = async (url, options = {{}}) => {{
  const callRecord = {{ url, options }};
  mockFetchCalls.push(callRecord);
  if (fetchHook) {{
    return fetchHook(url, options, callRecord);
  }}
  return {{
    ok: true,
    json: async () => ({{}})
  }};
}};

// Mock URLSearchParams
class MockURLSearchParams {{
  constructor(search) {{}}
  has() {{ return false; }}
  get() {{ return null; }}
}}
globalThis.URLSearchParams = MockURLSearchParams;

// --- Mock Media & Audio for safe fallback ---
const navigator = {{
  mediaDevices: {{
    getUserMedia: () => Promise.resolve({{ getTracks: () => [] }})
  }}
}};
Object.defineProperty(globalThis, 'navigator', {{
  value: navigator,
  configurable: true,
  writable: true
}});

class MockAudioContext {{
  constructor() {{
    this.sampleRate = 16000;
    this.state = 'suspended';
    this.currentTime = 0;
    this.destination = {{ connect() {{}} }};
  }}
  async resume() {{ this.state = 'running'; }}
  async close() {{ this.state = 'closed'; }}
  createMediaStreamSource() {{ return {{ connect() {{}} }}; }}
  createScriptProcessor() {{ return {{ connect() {{}}, disconnect() {{}} }}; }}
  createGain() {{ return {{ gain: {{ value: 1 }}, connect() {{}} }}; }}
  createBufferSource() {{ return {{ connect() {{}}, start() {{}}, stop() {{}} }}; }}
  createBuffer(ch, len, sr) {{ return {{ duration: 1, getChannelData: () => new Float32Array(len || 10) }}; }}
}}
globalThis.AudioContext = MockAudioContext;
globalThis.webkitAudioContext = MockAudioContext;

// --- Controllable Timers System ---
const realSetTimeout = globalThis.setTimeout;
const realClearTimeout = globalThis.clearTimeout;

function installControlledTimers() {{
  let currentTime = 0;
  let nextTimerId = 1;
  const activeTimers = new Map();

  globalThis.setTimeout = (fn, delay = 0, ...args) => {{
    const id = nextTimerId++;
    const due = currentTime + Math.max(0, delay);
    activeTimers.set(id, {{ fn, due, args }});
    return id;
  }};

  globalThis.clearTimeout = (id) => {{
    activeTimers.delete(id);
  }};

  const advanceTimers = async (ms) => {{
    currentTime += ms;
    while (true) {{
      let earliestId = null;
      let earliestDue = Infinity;
      for (const [id, timer] of activeTimers.entries()) {{
        if (timer.due <= currentTime && timer.due < earliestDue) {{
          earliestDue = timer.due;
          earliestId = id;
        }}
      }}
      if (earliestId === null) break;
      const timer = activeTimers.get(earliestId);
      activeTimers.delete(earliestId);
      try {{
        timer.fn(...timer.args);
      }} catch (e) {{
        console.warn("Timer callback error:", e);
      }}
      await new Promise(r => setImmediate(r));
    }}
  }};

  const advanceAllTimers = async () => {{
    while (activeTimers.size > 0) {{
      let earliestId = null;
      let earliestDue = Infinity;
      for (const [id, timer] of activeTimers.entries()) {{
        if (timer.due < earliestDue) {{
          earliestDue = timer.due;
          earliestId = id;
        }}
      }}
      if (earliestId === null) break;
      currentTime = earliestDue;
      const timer = activeTimers.get(earliestId);
      activeTimers.delete(earliestId);
      try {{
        timer.fn(...timer.args);
      }} catch (e) {{
        console.warn("Timer callback error:", e);
      }}
      await new Promise(r => setImmediate(r));
    }}
  }};

  return {{
    advanceTimers,
    advanceAllTimers,
    getCurrentTime: () => currentTime,
    getActiveTimerCount: () => activeTimers.size
  }};
}}
globalThis.installControlledTimers = installControlledTimers;

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
globalThis.mockSockets = mockSockets;

// Helper to determine which view is visible
const getActiveView = () => {{
  if (!getOrCreateElement('intake-view').classList.contains('hidden')) return 'intake';
  if (!getOrCreateElement('loading-view').classList.contains('hidden')) return 'loading';
  if (!getOrCreateElement('results-view').classList.contains('hidden')) return 'results';
  return 'unknown';
}};
globalThis.getActiveView = getActiveView;

const makeMockRecommendation = (title, year) => ({{
  recommendations: [{{
    metadata: {{
      title: title || "Mock Movie",
      year: year || 2020,
      genres: ["Drama"],
      director: "A. Director",
      runtime_minutes: 100,
      synopsis: "A great movie synopsis.",
      poster_url: "http://example.com/poster.jpg"
    }},
    availability: {{ status: "available", matched_services: ["Netflix"] }},
    match_reasons: ["Fits pacing"],
    scores: {{ composite: 85 }},
    profile: {{
      story_and_writing: 8,
      pacing_and_structure: 7,
      performances: 9,
      tone_and_emotional_character: ["dark", "tense"],
      craft_and_execution: 8,
      accessibility_and_demandingness: 6
    }}
  }}]
}});
globalThis.makeMockRecommendation = makeMockRecommendation;

// --- Evaluate static/index.html Application Script in Global Context ---
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


def test_reproduce_stale_recommendations_after_restart_while_fetch_pending():
    """
    Deterministic reproduction:
    In unhardened code, starting a recommendation request, restarting conversation while fetch is pending,
    and then resolving the fetch will overwrite chatState.lastResults with stale data and after 400ms
    hijack the view from 'intake' to 'results'.
    Corrected behavior:
    Old fetch is aborted/invalidated, chatState.lastResults remains null, active view remains 'intake'.
    """
    js = """
    let resolveRecommendFetch = null;
    let abortSignalTriggered = false;

    fetchHook = (url, options) => {
      if (url.includes('/api/recommend')) {
        if (options.signal) {
          options.signal.addEventListener('abort', () => {
            abortSignalTriggered = true;
          });
        }
        return new Promise((resolve) => {
          resolveRecommendFetch = () => {
            resolve({
              ok: true,
              json: async () => makeMockRecommendation("Stale Old Movie", 1999)
            });
          };
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    // 1. User starts recommendation request
    const pipelinePromise = window.triggerPipelineExecution();

    // Allow microtask queue to process so triggerPipelineExecution advances past turnQueue to in-flight fetch
    await new Promise(r => setImmediate(r));

    const viewDuringFetch = getActiveView();
    const isFetching = (resolveRecommendFetch !== null);

    // 2. User clicks 'Start fresh' / restartConversation() while fetch is pending
    window.restartConversation();

    const viewAfterRestart = getActiveView();
    const lastResultsAfterRestart = window.chatState.lastResults;

    // 3. Now the old pending fetch finishes and resolves
    resolveRecommendFetch();

    // Allow microtasks to run
    await new Promise(r => setTimeout(r, 50));
    const lastResultsImmediatelyAfterResolution = window.chatState.lastResults;

    // 4. Wait past the 400ms rendering delay
    await new Promise(r => setTimeout(r, 450));
    const viewAfterDelay = getActiveView();
    const finalLastResults = window.chatState.lastResults;

    console.log(JSON.stringify({
      viewDuringFetch,
      isFetching,
      abortSignalTriggered,
      viewAfterRestart,
      lastResultsAfterRestart,
      lastResultsImmediatelyAfterResolution,
      viewAfterDelay,
      finalLastResults
    }));
    """
    result = _run_stale_test_in_node(js)

    assert result["viewDuringFetch"] == "loading"
    assert result["isFetching"] is True
    assert result["abortSignalTriggered"] is True
    assert result["viewAfterRestart"] == "intake"
    assert result["lastResultsAfterRestart"] is None
    assert result["lastResultsImmediatelyAfterResolution"] is None
    assert result["finalLastResults"] is None
    assert result["viewAfterDelay"] == "intake"


def test_restart_while_response_json_pending():
    """
    Restart while response.json() is pending:
    Fetch promise resolves, but response.json() is still awaiting body parsing.
    User restarts conversation.
    response.json() resolves afterwards.
    Result: chatState.lastResults remains null, results are not rendered.
    """
    js = """
    let resolveJson = null;

    fetchHook = (url, options) => {
      if (url.includes('/api/recommend')) {
        return Promise.resolve({
          ok: true,
          json: () => new Promise((res) => {
            resolveJson = () => res(makeMockRecommendation("Json Movie", 2021));
          })
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    window.triggerPipelineExecution();
    await new Promise(r => setImmediate(r));

    const isJsonPending = (resolveJson !== null);

    // Restart while response.json() is in flight
    window.restartConversation();

    // Resolve json afterwards
    resolveJson();

    await new Promise(r => setTimeout(r, 50));
    const lastResultsAfterJson = window.chatState.lastResults;

    await new Promise(r => setTimeout(r, 450));
    const finalView = getActiveView();
    const finalResults = window.chatState.lastResults;

    console.log(JSON.stringify({
      isJsonPending,
      lastResultsAfterJson,
      finalView,
      finalResults
    }));
    """
    result = _run_stale_test_in_node(js)
    assert result["isJsonPending"] is True
    assert result["lastResultsAfterJson"] is None
    assert result["finalResults"] is None
    assert result["finalView"] == "intake"


def test_restart_after_response_parsing_before_rendering():
    """
    Restart after response parsing but during the 400ms pre-render delay:
    Fetch and json() complete successfully. recommendationRenderTimer is active.
    User restarts conversation during the delay.
    Timer fires.
    Result: render is skipped, chatState.lastResults remains null, view remains intake.
    """
    js = """
    fetchHook = (url, options) => {
      if (url.includes('/api/recommend')) {
        return Promise.resolve({
          ok: true,
          json: async () => makeMockRecommendation("Delay Movie", 2022)
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    window.triggerPipelineExecution();

    // Wait 100ms: fetch and json() complete, 400ms timer is ticking
    await new Promise(r => setTimeout(r, 100));
    const timerActiveBeforeRestart = (window.getRecommendationState().recommendationRenderTimer !== null);

    // User restarts during the pre-render delay
    window.restartConversation();
    const timerAfterRestart = window.getRecommendationState().recommendationRenderTimer;

    // Advance past the 400ms timer threshold
    await new Promise(r => setTimeout(r, 400));
    const finalView = getActiveView();
    const finalResults = window.chatState.lastResults;

    console.log(JSON.stringify({
      timerActiveBeforeRestart,
      timerAfterRestart: timerAfterRestart === null,
      finalView,
      finalResults
    }));
    """
    result = _run_stale_test_in_node(js)
    assert result["timerActiveBeforeRestart"] is True
    assert result["timerAfterRestart"] is True
    assert result["finalView"] == "intake"
    assert result["finalResults"] is None


def test_restart_before_text_or_voice_auto_recommendation_timers_fire():
    """
    Restart before text or voice auto-recommendation timers fire:
    User submits affirmative dialogue turn ("yes please show me").
    The auto recommendation timer (600ms) is scheduled.
    User restarts conversation at 200ms.
    Result: Timer is cancelled; at 700ms, no recommendation request was triggered, view remains intake.
    """
    js = """
    let recommendCallCount = 0;

    fetchHook = (url, options) => {
      if (url.includes('/api/voice/turn')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            assistant_reply: "Finding your films now!",
            ready_to_recommend: true,
            updated_context: {}
          })
        });
      }
      if (url.includes('/api/recommend')) {
        recommendCallCount++;
        return Promise.resolve({
          ok: true,
          json: async () => makeMockRecommendation("Auto Movie", 2023)
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    // Enqueue text dialogue turn with affirmative intent
    window.enqueueTextDialogueTurn("yes please show me what fits");

    // Wait for dialogue turn to process and schedule the 600ms timer
    await new Promise(r => setTimeout(r, 100));
    const timerScheduled = (window.getRecommendationState().autoRecommendationTimer !== null);

    // User restarts conversation before 600ms timer fires
    window.restartConversation();
    const timerAfterRestart = window.getRecommendationState().autoRecommendationTimer;

    // Wait past 600ms
    await new Promise(r => setTimeout(r, 650));
    const finalView = getActiveView();

    console.log(JSON.stringify({
      timerScheduled,
      timerAfterRestart: timerAfterRestart === null,
      recommendCallCount,
      finalView
    }));
    """
    result = _run_stale_test_in_node(js)
    assert result["timerScheduled"] is True
    assert result["timerAfterRestart"] is True
    assert result["recommendCallCount"] == 0
    assert result["finalView"] == "intake"


def test_start_new_request_after_restart_then_resolve_or_reject_old_request():
    """
    Start a new request after restart; then resolve or reject the old request:
    Old request 1 is in-flight.
    Conversation restarts.
    New request 2 starts and is in-flight.
    Old request 1 rejects or resolves.
    Result: Old request 1 does NOT clear isGenerating or abort Request 2.
    Request 2 completes normally and renders Request 2 results.
    """
    js = """
    let resolveReq1 = null;
    let resolveReq2 = null;

    fetchHook = (url, options) => {
      if (url.includes('/api/recommend')) {
        return new Promise((resolve) => {
          if (!resolveReq1) {
            resolveReq1 = () => resolve({
              ok: true,
              json: async () => makeMockRecommendation("Old Request 1 Film", 2010)
            });
          } else {
            resolveReq2 = () => resolve({
              ok: true,
              json: async () => makeMockRecommendation("New Request 2 Film", 2024)
            });
          }
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    // 1. Trigger Request 1
    window.triggerPipelineExecution();
    await new Promise(r => setImmediate(r));

    // 2. Restart conversation
    window.restartConversation();

    // 3. Trigger Request 2 in new conversation
    window.triggerPipelineExecution();
    await new Promise(r => setImmediate(r));

    const stateWhileReq2Pending = window.getRecommendationState();

    // 4. Old Request 1 resolves
    resolveReq1();
    await new Promise(r => setTimeout(r, 50));

    // Request 2 loading state must NOT have been cleared by Request 1
    const isGeneratingAfterReq1Resolved = window.getRecommendationState().isGenerating;

    // 5. Request 2 resolves
    resolveReq2();
    await new Promise(r => setTimeout(r, 500));

    const finalView = getActiveView();
    const renderedTitle = window.chatState.lastResults?.recommendations[0]?.metadata?.title;

    console.log(JSON.stringify({
      req2IsGeneratingInitial: stateWhileReq2Pending.isGenerating,
      isGeneratingAfterReq1Resolved,
      finalView,
      renderedTitle
    }));
    """
    result = _run_stale_test_in_node(js)
    assert result["req2IsGeneratingInitial"] is True
    assert result["isGeneratingAfterReq1Resolved"] is True
    assert result["finalView"] == "results"
    assert result["renderedTitle"] == "New Request 2 Film"


def test_supersede_request_within_same_conversation_and_resolve_out_of_order():
    """
    Supersede a request within the same conversation and resolve responses out of order:
    Request 1 is triggered (e.g. initial request).
    Request 2 is triggered (e.g. newer recommendation intent / duplicate click / refined trigger).
    Request 1 is aborted/superseded.
    Request 1 resolves AFTER Request 2.
    Result: Request 1 never renders, Request 2 renders, Request 1 cleanup does not clear Request 2 state.
    """
    js = """
    let resolveReq1 = null;
    let resolveReq2 = null;
    let req1Aborted = false;

    fetchHook = (url, options) => {
      if (url.includes('/api/recommend')) {
        return new Promise((resolve, reject) => {
          if (!resolveReq1) {
            if (options.signal) {
              options.signal.addEventListener('abort', () => {
                req1Aborted = true;
                reject(new Error("AbortError"));
              });
            }
            resolveReq1 = () => resolve({
              ok: true,
              json: async () => makeMockRecommendation("Superseded Movie 1", 2001)
            });
          } else {
            resolveReq2 = () => resolve({
              ok: true,
              json: async () => makeMockRecommendation("Winner Movie 2", 2025)
            });
          }
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    // Trigger Request 1
    window.triggerPipelineExecution();
    await new Promise(r => setImmediate(r));

    // Trigger Request 2 within same conversation (superseding Request 1)
    window.triggerPipelineExecution();
    await new Promise(r => setImmediate(r));

    // Resolve Request 2 FIRST
    resolveReq2();
    await new Promise(r => setTimeout(r, 450));
    const titleAfterReq2 = window.chatState.lastResults?.recommendations[0]?.metadata?.title;

    // Now try to resolve Request 1 (out of order / late)
    try { resolveReq1(); } catch(e) {}
    await new Promise(r => setTimeout(r, 450));

    const finalTitle = window.chatState.lastResults?.recommendations[0]?.metadata?.title;
    const finalView = getActiveView();

    console.log(JSON.stringify({
      req1Aborted,
      titleAfterReq2,
      finalTitle,
      finalView
    }));
    """
    result = _run_stale_test_in_node(js)
    assert result["req1Aborted"] is True
    assert result["titleAfterReq2"] == "Winner Movie 2"
    assert result["finalTitle"] == "Winner Movie 2"
    assert result["finalView"] == "results"


def test_submit_refinement_and_immediately_request_recommendations():
    """
    Submit a refinement and immediately request recommendations:
    User submits a refinement dialogue turn.
    While dialogue turn is in-flight, triggerPipelineExecution() is called.
    triggerPipelineExecution() awaits the pending turn in turnQueue before building payload.
    Result: The recommendations fetch payload contains the updated signals from the dialogue turn!
    """
    js = """
    let capturedPayload = null;

    fetchHook = (url, options) => {
      if (url.includes('/api/voice/turn')) {
        return new Promise(resolve => {
          setTimeout(() => {
            resolve({
              ok: true,
              json: async () => ({
                assistant_reply: "Understood, setting pacing to fast and tone to thriller.",
                ready_to_recommend: false,
                updated_context: {
                  tonight_signals: [
                    { name: "pacing", value: "fast", signal_type: "soft_session_preference" },
                    { name: "tone", value: "thriller", signal_type: "soft_session_preference" }
                  ]
                }
              })
            });
          }, 50);
        });
      }
      if (url.includes('/api/recommend')) {
        capturedPayload = JSON.parse(options.body);
        return Promise.resolve({
          ok: true,
          json: async () => makeMockRecommendation("Refined Thriller", 2023)
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    // User submits refinement
    window.enqueueTextDialogueTurn("I want something fast and thrilling");

    // Immediately request recommendations (before turn completes)
    window.triggerPipelineExecution();

    // Wait for queue and fetch to complete
    await new Promise(r => setTimeout(r, 200));

    const pacingSignal = capturedPayload?.tonight_signals?.find(s => s.name === 'pacing')?.value;
    const toneSignal = capturedPayload?.tonight_signals?.find(s => s.name === 'tone')?.value;

    console.log(JSON.stringify({
      pacingSignal,
      toneSignal
    }));
    """
    result = _run_stale_test_in_node(js)
    assert result["pacingSignal"] == "fast"
    assert result["toneSignal"] == "thriller"


def test_return_to_chat_without_editing_confirms_history_and_constraints_intact():
    """
    Return to chat without editing; confirm history and constraints remain intact:
    User sets preferences and exclusions, then generates recommendations and views results.
    User returns to chat (returnToChat()).
    Result: conversation history, excluded genres, service access, pacing, and tone are completely preserved.
    """
    js = """
    fetchHook = (url, options) => {
      if (url.includes('/api/recommend')) {
        return Promise.resolve({
          ok: true,
          json: async () => makeMockRecommendation("Found Film", 2022)
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    // Set user state
    window.chatState.pacing = "unhurried";
    window.chatState.tone = "melancholic";
    window.chatState.service_access = ["MUBI", "BFI Player"];
    window.chatState.exclude_genres = ["Horror", "Musical"];
    window.chatState.conversation_history = [
      { role: "user", content: "Something thoughtful" },
      { role: "assistant", content: "Got it." }
    ];

    // Generate and view results
    window.triggerPipelineExecution();
    await new Promise(r => setTimeout(r, 500));
    const viewAtResults = getActiveView();

    // Return to chat
    window.returnToChat();
    const viewAfterReturn = getActiveView();

    console.log(JSON.stringify({
      viewAtResults,
      viewAfterReturn,
      historyLength: window.chatState.conversation_history.length,
      pacing: window.chatState.pacing,
      tone: window.chatState.tone,
      services: window.chatState.service_access,
      excludeGenres: window.chatState.exclude_genres
    }));
    """
    result = _run_stale_test_in_node(js)
    assert result["viewAtResults"] == "results"
    assert result["viewAfterReturn"] == "intake"
    assert result["historyLength"] == 2
    assert result["pacing"] == "unhurried"
    assert result["tone"] == "melancholic"
    assert result["services"] == ["MUBI", "BFI Player"]
    assert result["excludeGenres"] == ["Horror", "Musical"]


def test_request_recommendations_while_dialogue_pending_then_restart_before_turn_finishes():
    """
    Request recommendations while a dialogue turn is pending, then restart before that turn finishes:
    User submits turn -> turn is in-flight.
    User clicks "Find what fits" -> waits on turnQueue.
    Before turn finishes, user clicks "Start fresh" (restartConversation()).
    Turn eventually finishes.
    Result: Recommendation request does NOT dispatch fetch, UI does not switch to loading/results, view is intake.
    """
    js = """
    let resolveTurn = null;
    let recommendCallCount = 0;

    fetchHook = (url, options) => {
      if (url.includes('/api/voice/turn')) {
        return new Promise(resolve => {
          resolveTurn = () => resolve({
            ok: true,
            json: async () => ({
              assistant_reply: "Turn reply",
              ready_to_recommend: false,
              updated_context: {}
            })
          });
        });
      }
      if (url.includes('/api/recommend')) {
        recommendCallCount++;
        return Promise.resolve({
          ok: true,
          json: async () => makeMockRecommendation("Never Shown", 2024)
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    // 1. Dialogue turn starts
    window.enqueueTextDialogueTurn("pending turn");
    await new Promise(r => setImmediate(r));

    // 2. Recommendation request waiting on turn
    const pipelinePromise = window.triggerPipelineExecution();

    // 3. User restarts conversation BEFORE turn resolves
    window.restartConversation();

    // 4. Now turn resolves
    if (resolveTurn) resolveTurn();
    await new Promise(r => setTimeout(r, 100));

    const finalView = getActiveView();
    const finalResults = window.chatState.lastResults;

    console.log(JSON.stringify({
      recommendCallCount,
      finalView,
      finalResults
    }));
    """
    result = _run_stale_test_in_node(js)
    assert result["recommendCallCount"] == 0
    assert result["finalView"] == "intake"
    assert result["finalResults"] is None


def test_make_two_recommendation_requests_while_waiting_for_dialogue():
    """
    Make two recommendation requests while both are waiting for dialogue:
    Dialogue turn is in-flight.
    User clicks recommendations (Request 1).
    User clicks recommendations again (Request 2).
    Dialogue turn finishes.
    Result: Only Request 2 proceeds to dispatch fetch; Request 1 is aborted/superseded at identity check.
    Total recommendation fetch calls == 1.
    """
    js = """
    let resolveTurn = null;
    let recommendCalls = [];

    fetchHook = (url, options) => {
      if (url.includes('/api/voice/turn')) {
        return new Promise(resolve => {
          resolveTurn = () => resolve({
            ok: true,
            json: async () => ({
              assistant_reply: "Dialogue done",
              ready_to_recommend: false,
              updated_context: {}
            })
          });
        });
      }
      if (url.includes('/api/recommend')) {
        recommendCalls.push({ url, body: options.body });
        return Promise.resolve({
          ok: true,
          json: async () => makeMockRecommendation("Single Winner", 2024)
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    // Dialogue turn in flight
    window.enqueueTextDialogueTurn("Slow dialogue turn");
    await new Promise(r => setImmediate(r));

    // Request 1 while waiting
    window.triggerPipelineExecution();

    // Request 2 while waiting
    window.triggerPipelineExecution();

    // Turn finishes
    if (resolveTurn) resolveTurn();
    await new Promise(r => setTimeout(r, 100));

    // Wait past delayed render
    await new Promise(r => setTimeout(r, 450));

    const totalRecommendCalls = recommendCalls.length;
    const finalView = getActiveView();
    const renderedTitle = window.chatState.lastResults?.recommendations[0]?.metadata?.title;

    console.log(JSON.stringify({
      totalRecommendCalls,
      finalView,
      renderedTitle
    }));
    """
    result = _run_stale_test_in_node(js)
    assert result["totalRecommendCalls"] == 1
    assert result["finalView"] == "results"
    assert result["renderedTitle"] == "Single Winner"


def test_older_turn_completing_after_newer_refinement_submitted():
    """
    Test an older turn completing after a newer refinement has been submitted:
    Turn 1 (e.g. affirmative query "show me") is enqueued.
    Turn 2 (newer refinement "wait I changed my mind") is enqueued immediately.
    Turn 1 completes late (after Turn 2 was submitted).
    Result: Turn 1 is rejected from scheduling an auto-recommendation timer because turnId !== latestDialogueTurnId.
    """
    js = """
    let resolveTurn1 = null;
    let resolveTurn2 = null;
    let recommendCallCount = 0;

    fetchHook = (url, options) => {
      if (url.includes('/api/voice/turn')) {
        const body = JSON.parse(options.body);
        if (body.user_input && body.user_input.includes("show me")) {
          return new Promise(resolve => {
            resolveTurn1 = () => resolve({
              ok: true,
              json: async () => ({
                assistant_reply: "Turn 1 reply",
                ready_to_recommend: true,
                updated_context: {}
              })
            });
          });
        } else {
          return new Promise(resolve => {
            resolveTurn2 = () => resolve({
              ok: true,
              json: async () => ({
                assistant_reply: "Turn 2 reply",
                ready_to_recommend: false,
                updated_context: {}
              })
            });
          });
        }
      }
      if (url.includes('/api/recommend')) {
        recommendCallCount++;
        return Promise.resolve({
          ok: true,
          json: async () => makeMockRecommendation("Never Scheduled", 2024)
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    // User submits Turn 1 (with affirmative intent)
    window.enqueueTextDialogueTurn("show me what fits");

    // User immediately submits Turn 2 (refinement)
    window.enqueueTextDialogueTurn("wait actually no comedies");

    // Allow Turn 1 to reach in-flight fetch
    await new Promise(r => setImmediate(r));

    // Turn 1 resolves
    if (resolveTurn1) resolveTurn1();
    await new Promise(r => setTimeout(r, 50));

    // Check if auto-recommendation timer was scheduled by Turn 1
    const timerAfterTurn1 = window.getRecommendationState().autoRecommendationTimer;

    // Allow Turn 2 to reach in-flight fetch and resolve
    await new Promise(r => setImmediate(r));
    if (resolveTurn2) resolveTurn2();
    await new Promise(r => setTimeout(r, 50));

    // Wait past the 600ms auto recommendation window
    await new Promise(r => setTimeout(r, 650));

    console.log(JSON.stringify({
      timerAfterTurn1: timerAfterTurn1 === null,
      recommendCallCount
    }));
    """
    result = _run_stale_test_in_node(js)
    assert result["timerAfterTurn1"] is True
    assert result["recommendCallCount"] == 0


def test_reproduce_manual_request_while_affirmative_dialogue_pending():
    """
    Regression test for Race 1:
    Enqueue an affirmative turn, click Find before it resolves, resolve the turn,
    then advance all timers. Assert exactly one recommendation request is made.
    """
    js_code = """
    const { advanceTimers, advanceAllTimers } = installControlledTimers();

    let resolveTurnPromise = null;
    let recommendCallCount = 0;
    const recommendCalls = [];

    fetchHook = (url, options, record) => {
      if (url.includes('/api/voice/turn')) {
        return new Promise((resolve) => {
          resolveTurnPromise = () => {
            resolve({
              ok: true,
              json: async () => ({
                assistant_reply: "Sure! Let's find your movies.",
                ready_to_recommend: true,
                updated_context: {
                  tonight_signals: [
                    { name: "pacing", value: "brisk", signal_type: "soft_session_preference" }
                  ]
                }
              })
            });
          };
        });
      }
      if (url.includes('/api/recommend')) {
        recommendCallCount++;
        recommendCalls.push({ url, body: options.body ? JSON.parse(options.body) : null });
        return Promise.resolve({
          ok: true,
          json: async () => makeMockRecommendation("Speed", 1994)
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    // 1. Enqueue affirmative text dialogue turn
    window.enqueueTextDialogueTurn("yes please find what fits");
    await new Promise(r => setImmediate(r));

    // 2. User clicks Find before the turn resolves
    window.triggerPipelineExecution();
    await new Promise(r => setImmediate(r));

    // 3. Resolve the affirmative turn
    if (!resolveTurnPromise) {
      throw new Error("Turn promise was not initialized");
    }
    resolveTurnPromise();
    await new Promise(r => setImmediate(r));
    await new Promise(r => setImmediate(r));

    // 4. Advance all timers (including the 600ms auto recommendation timer and 400ms render timer)
    await advanceAllTimers();

    console.log(JSON.stringify({
      recommendCallCount,
      recommendCalls
    }));
    """
    res = _run_stale_test_in_node(js_code)
    assert res["recommendCallCount"] == 1, f"Expected exactly 1 recommendation request, got {res['recommendCallCount']}"


def test_reproduce_new_spoken_refinement_while_live_auto_recommendation_timer_pending():
    """
    Regression test for Race 2:
    Schedule recommendations from a completed voice turn, begin a new spoken refinement
    before the timer fires, then advance timers. Assert no premature request or voice teardown.
    Complete the refinement and verify subsequent valid recommendations use its updated context.
    """
    js_code = """
    const { advanceTimers, advanceAllTimers } = installControlledTimers();

    let recommendCallCount = 0;
    const recommendCalls = [];

    fetchHook = (url, options, record) => {
      if (url.includes('/api/recommend')) {
        recommendCallCount++;
        recommendCalls.push({ url, body: options.body ? JSON.parse(options.body) : null });
        return Promise.resolve({
          ok: true,
          json: async () => makeMockRecommendation("Alien", 1979)
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    // 1. Start voice session
    window.toggleSingleBrainVoice();
    await new Promise(r => setImmediate(r));

    const ws = mockSockets[mockSockets.length - 1];
    ws.simulateOpen();
    ws.simulateMessage({ type: "init_ack", status: "ready" });
    await new Promise(r => setImmediate(r));

    // 2. Complete affirmative voice turn 1 ("show me what fits")
    ws.simulateMessage({ type: "transcript", role: "user", text: "yes please show me what fits" });
    ws.simulateMessage({ type: "transcript", role: "assistant", text: "Finding the best matches for you." });
    ws.simulateMessage({
      type: "turn_complete",
      ready_to_recommend: true,
      updated_context: {
        tonight_signals: [
          { name: "pacing", value: "steady", signal_type: "soft_session_preference" }
        ]
      }
    });
    await new Promise(r => setImmediate(r));

    // Check timer was scheduled
    const recState1 = window.getRecommendationState();

    // 3. Advance partway (e.g. 300ms of the 1000ms timer)
    await advanceTimers(300);

    // 4. Begin a new spoken refinement before the 1000ms timer fires
    ws.simulateMessage({ type: "transcript", role: "user", text: "actually no horror, make it comedy" });
    await new Promise(r => setImmediate(r));

    // 5. Advance timers past the original 1000ms (e.g. 1500ms)
    await advanceTimers(1500);

    // Assert NO premature request or voice teardown
    const voiceStateDuringRefinement = window.getVoiceState();
    const prematureCallCount = recommendCallCount;

    // 6. Complete the refinement (Turn 2) with updated context
    ws.simulateMessage({ type: "transcript", role: "assistant", text: "Understood, comedy it is." });
    ws.simulateMessage({
      type: "turn_complete",
      ready_to_recommend: false,
      updated_context: {
        tonight_signals: [
          { name: "pacing", value: "steady", signal_type: "soft_session_preference" },
          { name: "tone", value: "comedy", signal_type: "soft_session_preference" },
          { name: "exclude-genre", value: ["Horror"], signal_type: "hard_constraint" }
        ]
      }
    });
    await new Promise(r => setImmediate(r));

    // Advance timers again - Turn 2 was not affirmative, so still no premature request
    await advanceAllTimers();
    const callCountAfterRefinement = recommendCallCount;

    // 7. Now trigger recommendations validly (e.g. click Find or affirmative turn)
    await window.triggerPipelineExecution();
    await advanceAllTimers();

    console.log(JSON.stringify({
      prematureCallCount,
      voiceActiveDuringRefinement: voiceStateDuringRefinement.voiceActive,
      callCountAfterRefinement,
      totalRecommendCalls: recommendCallCount,
      lastRecommendCall: recommendCalls[recommendCalls.length - 1]
    }));
    """
    res = _run_stale_test_in_node(js_code)
    assert res["prematureCallCount"] == 0, f"Premature request fired! Call count: {res['prematureCallCount']}"
    assert res["voiceActiveDuringRefinement"] is True, "Voice was prematurely torn down!"
    assert res["callCountAfterRefinement"] == 0, "Premature request fired after non-affirmative refinement!"
    assert res["totalRecommendCalls"] == 1, f"Expected exactly 1 valid request, got {res['totalRecommendCalls']}"
    signals = res["lastRecommendCall"]["body"]["tonight_signals"]
    tone_sig = next((s for s in signals if s["name"] == "tone"), None)
    assert tone_sig and tone_sig["value"] == "comedy", f"Expected tone 'comedy', got {tone_sig}"
    exclude_sig = next((s for s in signals if s["name"] == "exclude-genre"), None)
    assert exclude_sig and "Horror" in exclude_sig["value"], f"Expected exclude 'Horror', got {exclude_sig}"


def test_manual_request_consumes_pending_turn_but_allows_subsequent_affirmative_refinement():
    """
    Verifies that while an explicit recommendation request consumes the pending turn's
    automatic intent, it does NOT suppress genuinely newer intent from subsequent turns.
    """
    js_code = """
    const { advanceTimers, advanceAllTimers } = installControlledTimers();

    let resolveTurn1 = null;
    let resolveTurn2 = null;
    let recommendCallCount = 0;
    const recommendCalls = [];

    fetchHook = (url, options) => {
      if (url.includes('/api/voice/turn')) {
        const body = JSON.parse(options.body);
        if (body.user_input && body.user_input.includes("Turn 1")) {
          return new Promise(r => {
            resolveTurn1 = () => r({
              ok: true,
              json: async () => ({
                assistant_reply: "Turn 1 reply",
                ready_to_recommend: true,
                updated_context: {}
              })
            });
          });
        } else {
          return new Promise(r => {
            resolveTurn2 = () => r({
              ok: true,
              json: async () => ({
                assistant_reply: "Turn 2 reply",
                ready_to_recommend: true,
                updated_context: {
                  tonight_signals: [
                    { name: "pacing", value: "brisk", signal_type: "soft_session_preference" }
                  ]
                }
              })
            });
          });
        }
      }
      if (url.includes('/api/recommend')) {
        recommendCallCount++;
        recommendCalls.push({ url, body: options.body ? JSON.parse(options.body) : null });
        return Promise.resolve({
          ok: true,
          json: async () => makeMockRecommendation("Speed", 1994)
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    // 1. Enqueue affirmative text turn 1
    window.enqueueTextDialogueTurn("Turn 1 show me what fits");
    await new Promise(r => setImmediate(r));

    // 2. User clicks Find before Turn 1 resolves
    window.triggerPipelineExecution();
    await new Promise(r => setImmediate(r));

    // 3. Turn 1 resolves
    resolveTurn1();
    await new Promise(r => setImmediate(r));
    await new Promise(r => setImmediate(r));

    // Advance all timers: only 1 recommendation call occurred
    await advanceAllTimers();
    const callsAfterTurn1 = recommendCallCount;

    // 4. Return to chat and submit genuinely newer affirmative Turn 2
    window.returnToChat();
    window.enqueueTextDialogueTurn("Turn 2 show me what fits briskly");
    await new Promise(r => setImmediate(r));

    // 5. Turn 2 resolves affirmative
    resolveTurn2();
    await new Promise(r => setImmediate(r));
    await new Promise(r => setImmediate(r));

    // 6. Advance timers: Turn 2's automatic trigger should fire!
    await advanceAllTimers();
    const callsAfterTurn2 = recommendCallCount;

    console.log(JSON.stringify({
      callsAfterTurn1,
      callsAfterTurn2,
      lastCallSignals: recommendCalls[recommendCalls.length - 1].body.tonight_signals
    }));
    """
    res = _run_stale_test_in_node(js_code)
    assert res["callsAfterTurn1"] == 1, f"Expected 1 call after Turn 1, got {res['callsAfterTurn1']}"
    assert res["callsAfterTurn2"] == 2, f"Expected 2 calls after Turn 2, got {res['callsAfterTurn2']}"
    pacing_sig = next((s for s in res["lastCallSignals"] if s["name"] == "pacing"), None)
    assert pacing_sig and pacing_sig["value"] == "brisk"


def test_barge_in_and_late_turn_complete_cannot_recreate_timer_after_new_user_turn_begun():
    """
    Verifies that when a user barges in or begins a new turn, late completion of an older turn
    cannot recreate an obsolete timer or tear down voice.
    """
    js_code = """
    const { advanceTimers, advanceAllTimers } = installControlledTimers();

    let recommendCallCount = 0;
    fetchHook = (url, options) => {
      if (url.includes('/api/recommend')) {
        recommendCallCount++;
        return Promise.resolve({
          ok: true,
          json: async () => makeMockRecommendation("Inception", 2010)
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    // 1. Start voice session
    window.toggleSingleBrainVoice();
    await new Promise(r => setImmediate(r));

    const ws = mockSockets[mockSockets.length - 1];
    ws.simulateOpen();
    ws.simulateMessage({ type: "init_ack", status: "ready" });
    await new Promise(r => setImmediate(r));

    // 2. User starts Turn 1 with affirmative words
    ws.simulateMessage({ type: "transcript", role: "user", text: "show me what fits" });
    ws.simulateMessage({ type: "transcript", role: "assistant", text: "Searching..." });

    // 3. User barges in before Turn 1 complete arrives
    ws.simulateMessage({ type: "interrupted" });
    await new Promise(r => setImmediate(r));

    // 4. User starts Turn 2
    ws.simulateMessage({ type: "transcript", role: "user", text: "wait actually I want something quiet" });
    await new Promise(r => setImmediate(r));

    // 5. Server sends late turn_complete from Turn 1 with ready_to_recommend: true
    // Because currentVoiceTurnId has advanced, this must NOT schedule an auto recommendation timer
    ws.simulateMessage({
      type: "turn_complete",
      ready_to_recommend: true,
      updated_context: {}
    });
    await new Promise(r => setImmediate(r));

    const timerAfterLateCompletion = window.getRecommendationState().autoRecommendationTimer;

    // Advance timers past 1000ms
    await advanceTimers(1500);

    const voiceState = window.getVoiceState();

    console.log(JSON.stringify({
      timerWasScheduled: timerAfterLateCompletion !== null,
      voiceActive: voiceState.voiceActive,
      recommendCallCount
    }));
    """
    res = _run_stale_test_in_node(js_code)
    assert res["timerWasScheduled"] is False, "Late turn completion recreated an auto-recommendation timer!"
    assert res["voiceActive"] is True, "Voice was prematurely torn down by late turn completion!"
    assert res["recommendCallCount"] == 0, "Premature recommendation request fired!"


def test_reproduce_refinement_b_submitted_while_find_awaits_turn_a():
    """
    Reproduces and verifies the race:
    Submit turn A -> click Find while A is pending -> submit affirmative refinement B before A resolves
    -> resolve A -> resolve B.

    Verifies:
    1. Turn B is not marked consumed before its context is incorporated.
    2. The final recommendation request includes B's preferences.
    3. Older results cannot replace the updated shortlist.
    4. The original manual-plus-automatic duplicate-request test still passes.
    """
    js_code = """
    const { advanceTimers, advanceAllTimers } = installControlledTimers();

    let resolveTurnA = null;
    let resolveTurnB = null;
    let resolveRec1 = null;
    let resolveRec2 = null;

    let recommendCallCount = 0;
    const recommendCalls = [];

    fetchHook = (url, options) => {
      if (url.includes('/api/voice/turn')) {
        const body = JSON.parse(options.body);
        if (body.user_input && body.user_input.includes("Turn A")) {
          return new Promise(r => {
            resolveTurnA = () => r({
              ok: true,
              json: async () => ({
                assistant_reply: "Turn A reply",
                ready_to_recommend: true,
                updated_context: {
                  tonight_signals: [
                    { name: "tone", value: "noir", signal_type: "soft_session_preference" }
                  ]
                }
              })
            });
          });
        } else {
          return new Promise(r => {
            resolveTurnB = () => r({
              ok: true,
              json: async () => ({
                assistant_reply: "Turn B reply",
                ready_to_recommend: true,
                updated_context: {
                  tonight_signals: [
                    { name: "tone", value: "comedy", signal_type: "soft_session_preference" }
                  ]
                }
              })
            });
          });
        }
      }
      if (url.includes('/api/recommend')) {
        recommendCallCount++;
        const callIdx = recommendCallCount;
        recommendCalls.push({ callIdx, url, body: options.body ? JSON.parse(options.body) : null });
        if (callIdx === 1) {
          return new Promise(r => {
            resolveRec1 = () => r({
              ok: true,
              json: async () => makeMockRecommendation("Chinatown", 1974)
            });
          });
        } else {
          return new Promise(r => {
            resolveRec2 = () => r({
              ok: true,
              json: async () => makeMockRecommendation("Airplane!", 1980)
            });
          });
        }
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    };

    // 1. Submit turn A
    window.enqueueTextDialogueTurn("Turn A noir");
    await new Promise(r => setImmediate(r));

    // 2. Click Find while A is pending
    window.triggerPipelineExecution();
    await new Promise(r => setImmediate(r));

    // 3. Submit affirmative refinement B before A resolves
    window.enqueueTextDialogueTurn("Turn B comedy affirmative show me");
    await new Promise(r => setImmediate(r));

    // 4. Resolve A
    resolveTurnA();
    await new Promise(r => setImmediate(r));
    await new Promise(r => setImmediate(r));

    // Snapshot state after A resolved and request 1 started
    const stateAfterAResolved = window.getRecommendationState();
    const callsAfterA = recommendCallCount;
    const req1Payload = recommendCalls[0] ? recommendCalls[0].body : null;

    // 5. Resolve B
    resolveTurnB();
    await new Promise(r => setImmediate(r));
    await new Promise(r => setImmediate(r));

    const stateAfterBResolved = window.getRecommendationState();

    // Advance timers so B's 600ms timer fires
    await advanceTimers(800);
    await new Promise(r => setImmediate(r));

    const callsAfterBTimer = recommendCallCount;
    const req2Payload = recommendCalls[1] ? recommendCalls[1].body : null;

    // 6. Now resolve older Request 1 (Chinatown)
    if (resolveRec1) {
      resolveRec1();
      await new Promise(r => setImmediate(r));
      await advanceTimers(500);
    }
    const lastResultsAfterRec1 = window.chatState.lastResults;

    // 7. Now resolve newer Request 2 (Airplane!)
    if (resolveRec2) {
      resolveRec2();
      await new Promise(r => setImmediate(r));
      await advanceTimers(500);
    }
    const lastResultsAfterRec2 = window.chatState.lastResults;
    const container = document.getElementById("watchcards-container");
    const containerChildrenHtml = (container?.children || []).map(c => c.innerHTML).join(" ");

    console.log(JSON.stringify({
      callsAfterA,
      lastConsumedAfterA: stateAfterAResolved.lastConsumedDialogueTurnId,
      callsAfterBTimer,
      req1Tone: req1Payload ? req1Payload.tonight_signals.find(s => s.name === "tone")?.value : null,
      req2Tone: req2Payload ? req2Payload.tonight_signals.find(s => s.name === "tone")?.value : null,
      hasChinatownInLastResults: lastResultsAfterRec1?.recommendations?.[0]?.metadata?.title === "Chinatown",
      hasAirplaneInLastResults: lastResultsAfterRec2?.recommendations?.[0]?.metadata?.title === "Airplane!",
      hasChinatownInDom: containerChildrenHtml.includes("Chinatown"),
      hasAirplaneInDom: containerChildrenHtml.includes("Airplane!")
    }));
    """
    res = _run_stale_test_in_node(js_code)
    # 1. B is not marked consumed before its context is incorporated:
    # Turn A is turn 1, Turn B is turn 2.
    # When A resolved, lastConsumedDialogueTurnId must be 1, NOT 2!
    assert res["lastConsumedAfterA"] == 1, f"Expected lastConsumedAfterA == 1, got {res['lastConsumedAfterA']}"
    # Request 1 used Turn A's context (noir)
    assert res["req1Tone"] == "noir", f"Expected req1Tone 'noir', got {res['req1Tone']}"
    # 2. B was not suppressed: B's timer fired and made Request 2
    assert res["callsAfterBTimer"] == 2, f"Expected 2 recommend calls after B timer, got {res['callsAfterBTimer']}"
    assert res["req2Tone"] == "comedy", f"Expected req2Tone 'comedy', got {res['req2Tone']}"
    # 3. Older results (Chinatown) could not overwrite the shortlist
    assert res["hasChinatownInLastResults"] is False, "Older results from Request 1 replaced lastResults!"
    assert res["hasChinatownInDom"] is False, "Older results from Request 1 rendered into DOM!"
    assert res["hasAirplaneInLastResults"] is True, "Final recommendation results not set in lastResults!"
    assert res["hasAirplaneInDom"] is True, "Final recommendation results (Airplane!) not displayed in DOM!"



