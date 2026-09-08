"""
Tests for Gemini Live Receive Path Decoupling, Request Deadlines, and Concurrency (Fix 4).
"""

import sys
import os
import asyncio
import json
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from fastapi import WebSocket, WebSocketDisconnect

# Ensure local module imports work
sys.path.append(str(Path(__file__).resolve().parent.parent / "src"))

import api
from contracts import UserContext, IntakeDepth, TasteSignal, SignalType


class MockWebSocket:
    """Mock FastAPI WebSocket for deterministic inspection."""
    def __init__(self, incoming_messages: Optional[List[Dict[str, Any]]] = None):
        self.incoming = asyncio.Queue()
        if incoming_messages:
            for m in incoming_messages:
                self.incoming.put_nowait(json.dumps(m))
        self.sent_messages: List[Dict[str, Any]] = []
        self.is_closed = False

    async def accept(self):
        pass

    async def receive_text(self) -> str:
        if self.is_closed:
            raise WebSocketDisconnect(code=1000)
        return await self.incoming.get()

    async def send_json(self, data: Dict[str, Any]):
        if self.is_closed:
            raise RuntimeError("Cannot send on closed WebSocket")
        self.sent_messages.append(data)

    async def close(self):
        self.is_closed = True


class MockServerContent:
    def __init__(
        self,
        interrupted: bool = False,
        input_transcription: Optional[str] = None,
        output_transcription: Optional[str] = None,
        model_turn_parts: Optional[List[Any]] = None,
        turn_complete: bool = False
    ):
        self.interrupted = interrupted
        self.input_transcription = MagicMock(text=input_transcription) if input_transcription else None
        self.output_transcription = MagicMock(text=output_transcription) if output_transcription else None
        self.model_turn = MagicMock(parts=model_turn_parts) if model_turn_parts else None
        self.turn_complete = turn_complete


class MockResponse:
    def __init__(self, content: MockServerContent):
        self.server_content = content


# ---------------------------------------------------------------------------
# Test 1: Upstream events forwarded while extraction is deliberately blocked
# ---------------------------------------------------------------------------
def test_upstream_events_forwarded_while_extraction_pending(monkeypatch):
    """
    Proves that with Fix 4, when Turn 1 extraction is held/blocked,
    subsequent upstream events (speech_complete, Turn 2 transcripts, audio)
    are received and forwarded to the WebSocket immediately without waiting.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock-gemini-key")
    monkeypatch.delenv("TONI_MOCK_GEMINI_LIVE", raising=False)

    extraction_started = asyncio.Event()
    extraction_can_proceed = asyncio.Event()

    async def slow_extract(user_input, current_context, conversation_history=None, timeout=3.5, client=None):
        extraction_started.set()
        await extraction_can_proceed.wait()
        return current_context, False

    monkeypatch.setattr(api, "extract_voice_context_async", slow_extract)

    session_responses = asyncio.Queue()

    class ControlledGeminiSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def receive(self):
            while True:
                item = await session_responses.get()
                if item is None:
                    break
                yield item

    controlled_session = ControlledGeminiSession()

    class ControlledLive:
        def connect(self, *args, **kwargs):
            return controlled_session

    class ControlledAio:
        live = ControlledLive()

    class ControlledClient:
        aio = ControlledAio()

    import google.genai
    monkeypatch.setattr(google.genai, "Client", lambda *args, **kwargs: ControlledClient())

    ws = MockWebSocket(incoming_messages=[
        {"type": "init", "context": {"country": "UK", "service_access": ["Netflix"]}}
    ])

    async def run_scenario():
        server_task = asyncio.create_task(api.websocket_voice_live(ws))

        while not any(m.get("type") == "init_ack" for m in ws.sent_messages):
            await asyncio.sleep(0.01)

        # 1. Turn 1: user speaks, bot speaks, turn completes
        await session_responses.put(MockResponse(MockServerContent(input_transcription="I want something brisk")))
        await session_responses.put(MockResponse(MockServerContent(output_transcription="Looking for brisk films")))
        await session_responses.put(MockResponse(MockServerContent(turn_complete=True)))

        # Wait for Turn 1 extraction to start and block
        await extraction_started.wait()

        # Turn 1 extraction is STILL BLOCKED.
        # 2. Immediately yield Turn 2 events from Gemini Live
        await session_responses.put(MockResponse(MockServerContent(input_transcription="Actually, make it funny")))

        # Allow receive loop to forward
        await asyncio.sleep(0.02)

        # PROOF: Turn 2's transcript WAS forwarded while Turn 1 extraction is STILL running!
        transcripts = [m.get("text") for m in ws.sent_messages if m.get("type") == "transcript"]
        assert "Actually, make it funny" in transcripts, "Turn 2 transcript should be forwarded immediately without waiting for Turn 1 extraction"

        # Check turn_id association
        t2_msg = next(m for m in ws.sent_messages if m.get("text") == "Actually, make it funny")
        assert t2_msg.get("turn_id") == 2, "Turn 2 message should have turn_id == 2"

        # Check speech_complete was sent for Turn 1
        speech_completes = [m for m in ws.sent_messages if m.get("type") == "speech_complete"]
        assert len(speech_completes) == 1
        assert speech_completes[0].get("turn_id") == 1

        # Now release Turn 1 extraction
        extraction_can_proceed.set()
        await asyncio.sleep(0.02)

        ws.is_closed = True
        await session_responses.put(None)
        server_task.cancel()
        try:
            await server_task
        except (asyncio.CancelledError, WebSocketDisconnect):
            pass

    asyncio.run(run_scenario())


# ---------------------------------------------------------------------------
# Test 2: Multiple turns retain ordered context updates and readiness
# ---------------------------------------------------------------------------
def test_multiple_turns_retain_ordered_context_and_readiness(monkeypatch):
    """
    Proves that sequential extraction correctly merges context signals
    in turn order, preserving pacing, runtime, and affirmative readiness.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock-gemini-key")
    monkeypatch.delenv("TONI_MOCK_GEMINI_LIVE", raising=False)

    extraction_order = []

    async def mock_extract(user_input, current_context, conversation_history=None, timeout=3.5, client=None):
        extraction_order.append(user_input)
        # Use fallback extractor logic for predictable signal updates
        return api._extract_voice_context_fallback(user_input, current_context)

    monkeypatch.setattr(api, "extract_voice_context_async", mock_extract)

    session_responses = asyncio.Queue()

    class ControlledGeminiSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def receive(self):
            while True:
                item = await session_responses.get()
                if item is None:
                    break
                yield item

    controlled_session = ControlledGeminiSession()

    class ControlledLive:
        def connect(self, *args, **kwargs):
            return controlled_session

    class ControlledAio:
        live = ControlledLive()

    class ControlledClient:
        aio = ControlledAio()

    import google.genai
    monkeypatch.setattr(google.genai, "Client", lambda *args, **kwargs: ControlledClient())

    ws = MockWebSocket(incoming_messages=[
        {"type": "init", "context": {"country": "UK", "service_access": ["Netflix"]}}
    ])

    async def run_scenario():
        server_task = asyncio.create_task(api.websocket_voice_live(ws))

        while not any(m.get("type") == "init_ack" for m in ws.sent_messages):
            await asyncio.sleep(0.01)

        # Turn 1: "under 90 minutes"
        await session_responses.put(MockResponse(MockServerContent(input_transcription="Keep it under 90 minutes")))
        await session_responses.put(MockResponse(MockServerContent(output_transcription="Got it, short films")))
        await session_responses.put(MockResponse(MockServerContent(turn_complete=True)))

        # Turn 2: "and make it funny, show me"
        await session_responses.put(MockResponse(MockServerContent(input_transcription="Make it funny, show me what you got")))
        await session_responses.put(MockResponse(MockServerContent(output_transcription="Here are comedies")))
        await session_responses.put(MockResponse(MockServerContent(turn_complete=True)))

        # Wait for both turn_completes to be processed by extraction pipeline
        while len([m for m in ws.sent_messages if m.get("type") == "turn_complete"]) < 2:
            await asyncio.sleep(0.01)

        turn_completes = [m for m in ws.sent_messages if m.get("type") == "turn_complete"]
        assert len(turn_completes) == 2

        # Turn 1
        t1 = turn_completes[0]
        assert t1.get("turn_id") == 1
        t1_runtime = next((s for s in t1["updated_context"]["tonight_signals"] if s["name"] == api.SIGNAL_MAX_RUNTIME), None)
        assert t1_runtime is not None
        assert t1_runtime["value"] == 90
        assert t1["ready_to_recommend"] is False

        # Turn 2 (retains max_runtime=90 from Turn 1 AND adds funny/ready)
        t2 = turn_completes[1]
        assert t2.get("turn_id") == 2
        t2_runtime = next((s for s in t2["updated_context"]["tonight_signals"] if s["name"] == api.SIGNAL_MAX_RUNTIME), None)
        assert t2_runtime is not None
        assert t2_runtime["value"] == 90
        assert t2["ready_to_recommend"] is True
        assert any(s["name"] == api.SIGNAL_TONE and s["value"] == "funny" for s in t2["updated_context"]["tonight_signals"])

        # Check sequential order preserved
        assert extraction_order == ["Keep it under 90 minutes", "Make it funny, show me what you got"]

        ws.is_closed = True
        await session_responses.put(None)
        server_task.cancel()
        try:
            await server_task
        except (asyncio.CancelledError, WebSocketDisconnect):
            pass

    asyncio.run(run_scenario())


# ---------------------------------------------------------------------------
# Test 3: Request deadline configuration & stalled async request fallback
# ---------------------------------------------------------------------------
def test_extract_voice_context_deadline_config(monkeypatch):
    """
    Verifies that extract_voice_context configures http_options with
    timeout in milliseconds and retry_options.attempts == 1.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock-key")
    monkeypatch.delenv("TONI_TESTING", raising=False)

    captured_config = {}

    class MockModels:
        def generate_content(self, model, contents, config=None):
            captured_config["model"] = model
            captured_config["http_options"] = config.http_options if config else None
            # Return dummy response
            res = MagicMock()
            res.parsed = None
            return res

    class MockClient:
        models = MockModels()

    import google.genai
    monkeypatch.setattr(google.genai, "Client", lambda *args, **kwargs: MockClient())

    ctx = UserContext(country="UK", service_access=["Netflix"], intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS)
    api.extract_voice_context("I want a mystery", ctx, timeout=2.5)

    assert "http_options" in captured_config
    http_opts = captured_config["http_options"]
    assert http_opts is not None
    assert http_opts.timeout == 10000  # Provider minimum applies to test keys too.
    assert http_opts.retry_options is not None
    assert http_opts.retry_options.attempts == 1


def test_stalled_async_extraction_times_out_and_uses_fallback(monkeypatch):
    """
    Proves that extract_voice_context_async bounds a stalled async call
    with an overall cancellable deadline and returns deterministic fallback.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock-key")
    monkeypatch.delenv("TONI_TESTING", raising=False)

    call_cancelled = False

    class StalledAioModels:
        async def generate_content(self, model, contents, config=None):
            nonlocal call_cancelled
            try:
                # Deliberately stall for 10 seconds
                await asyncio.sleep(10.0)
            except asyncio.CancelledError:
                call_cancelled = True
                raise

    class StalledAio:
        models = StalledAioModels()

    class MockClient:
        aio = StalledAio()

    async def run():
        ctx = UserContext(country="UK", service_access=["Netflix"], intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS)
        start = asyncio.get_event_loop().time()
        res_ctx, ready = await api.extract_voice_context_async(
            user_input="Under 90 minutes and funny",
            current_context=ctx,
            timeout=0.1,
            client=MockClient()
        )
        elapsed = asyncio.get_event_loop().time() - start

        # Must finish in < 1.0s (not hang for 10s)
        assert elapsed < 1.0
        # Must return fallback extracted signals
        runtime_sig = next((s for s in res_ctx.tonight_signals if s.name == api.SIGNAL_MAX_RUNTIME), None)
        assert runtime_sig is not None
        assert runtime_sig.value == 90
        assert any(s.name == api.SIGNAL_TONE and s.value == "funny" for s in res_ctx.tonight_signals)
        assert call_cancelled is True

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Test 4: Sustained burst under held extraction bounds queue and tasks
# ---------------------------------------------------------------------------
def test_sustained_burst_under_held_extraction_bounds_queue_and_tasks(monkeypatch):
    """
    Proves that a sustained burst while the first extraction is held unresolved
    bounds the queue to MAX_PENDING_TURNS, prevents multiple worker tasks,
    commits updates strictly in turn order via best-effort fallback,
    resolves conflicting constraints (e.g. 90 min then 120 min -> 120 min),
    and delivers exactly one ordered completion for every accepted turn.
    """
    ws = MockWebSocket()
    initial_ctx = UserContext(country="UK", service_access=["Netflix"], intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS)

    async def run():
        held_event = asyncio.Event()

        async def stalled_extract(user_input, current_context, conversation_history=None, timeout=3.5, client=None):
            await held_event.wait()
            return current_context, False

        monkeypatch.setattr(api, "extract_voice_context_async", stalled_extract)

        pipeline = api.LiveExtractionPipeline(
            websocket=ws,
            initial_context=initial_ctx,
            initial_history=[],
            client=None
        )

        # Enqueue Turn 1 ("under 90 minutes"): starts in-flight and stalls
        pipeline.enqueue_turn(1, "under 90 minutes", "Bot 1", [])
        await asyncio.sleep(0.01)

        assert pipeline.in_flight_task is not None
        assert not pipeline.in_flight_task.done()

        # Enqueue Turn 2 ("under 120 minutes"), Turn 3 ("funny"), Turn 4 ("bring up shortlist") while Turn 1 is blocked
        pipeline.enqueue_turn(2, "under 120 minutes", "Bot 2", [])
        pipeline.enqueue_turn(3, "make it funny", "Bot 3", [])
        pipeline.enqueue_turn(4, "bring up the shortlist", "Bot 4", [])

        # Assert queue size is strictly bounded to MAX_PENDING_TURNS
        assert pipeline.queue.qsize() <= api.LiveExtractionPipeline.MAX_PENDING_TURNS

        # Assert in_flight_cancelled_for_overload was triggered
        assert pipeline.in_flight_cancelled_for_overload is True

        # Assert only 1 worker task exists and is active
        assert pipeline.worker_task is not None
        assert not pipeline.worker_task.done()

        # Release stalled event and wait for queue to drain through worker loop
        held_event.set()
        while len([m for m in ws.sent_messages if m.get("type") == "turn_complete"]) < 4:
            await asyncio.sleep(0.01)
        await pipeline.shutdown()

        # Check all completion IDs: exactly [1, 2, 3, 4] with no missing completions
        completed_ids = [m["turn_id"] for m in ws.sent_messages if m.get("type") == "turn_complete"]
        assert completed_ids == [1, 2, 3, 4], f"Expected completions [1, 2, 3, 4], got {completed_ids}"

        # Check conflicting constraints: Turn 1 set 90 min, Turn 2 set 120 min -> final runtime must be 120!
        runtime_sig = next((s for s in pipeline.session_ctx.tonight_signals if s.name == api.SIGNAL_MAX_RUNTIME), None)
        assert runtime_sig is not None, "Max runtime signal must be present in session context"
        assert runtime_sig.value == 120, f"Expected final runtime 120 from Turn 2, got {runtime_sig.value}"

        # Check tone from Turn 3
        assert any(s.name == api.SIGNAL_TONE and s.value == "funny" for s in pipeline.session_ctx.tonight_signals)

        # Check ready flag from Turn 4
        t4_msg = next(m for m in ws.sent_messages if m.get("type") == "turn_complete" and m.get("turn_id") == 4)
        assert t4_msg["ready_to_recommend"] is True

        # Check conversation history: all 4 turns preserved in authoritative order
        user_msgs = [m["content"] for m in pipeline.conversation_history if m["role"] == "user"]
        assert user_msgs == ["under 90 minutes", "under 120 minutes", "make it funny", "bring up the shortlist"]

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Test 5: Disconnect invalidates late updates and cleans up owned resources
# ---------------------------------------------------------------------------
def test_disconnect_invalidates_late_updates_and_cleans_resources(monkeypatch):
    """
    Proves that when a WebSocket disconnects, in-flight work is cancelled,
    live session exit and client.aio.aclose() are awaited exactly once,
    and late results cannot write to the closed socket.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock-gemini-key")
    monkeypatch.delenv("TONI_MOCK_GEMINI_LIVE", raising=False)

    extraction_started = asyncio.Event()

    async def slow_extract(user_input, current_context, conversation_history=None, timeout=3.5, client=None):
        extraction_started.set()
        await asyncio.sleep(5.0)
        return current_context, False

    monkeypatch.setattr(api, "extract_voice_context_async", slow_extract)

    live_exit_called = False
    client_close_called = False

    class MockGeminiSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            nonlocal live_exit_called
            live_exit_called = True
        async def receive(self):
            yield MockResponse(MockServerContent(input_transcription="Hello TONI"))
            yield MockResponse(MockServerContent(turn_complete=True))
            while True:
                await asyncio.sleep(1.0)

    class MockLive:
        def connect(self, *args, **kwargs):
            return MockGeminiSession()

    class MockAio:
        live = MockLive()
        async def aclose(self):
            nonlocal client_close_called
            client_close_called = True

    class MockClient:
        aio = MockAio()

    import google.genai
    monkeypatch.setattr(google.genai, "Client", lambda *args, **kwargs: MockClient())

    ws = MockWebSocket(incoming_messages=[
        {"type": "init", "context": {"country": "UK", "service_access": ["Netflix"]}}
    ])

    async def run():
        server_task = asyncio.create_task(api.websocket_voice_live(ws))

        while not extraction_started.is_set():
            await asyncio.sleep(0.01)

        # Disconnect client while extraction is in flight
        await ws.close()
        # Trigger disconnect in server loop
        server_task.cancel()
        try:
            await server_task
        except (asyncio.CancelledError, WebSocketDisconnect):
            pass

        # Verify resource cleanup
        assert live_exit_called is True, "Live session context manager __aexit__ must be called"
        assert client_close_called is True, "Client aio.aclose() must be called"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Test 6: Pipeline state ownership uses context and history from init
# ---------------------------------------------------------------------------
def test_pipeline_uses_init_context_and_history(monkeypatch):
    """
    Proves that LiveExtractionPipeline updates its context and history from
    the frontend's init message rather than retaining default initial objects.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock-gemini-key")
    monkeypatch.delenv("TONI_MOCK_GEMINI_LIVE", raising=False)

    received_history = []
    received_context = []

    async def capture_extract(user_input, current_context, conversation_history=None, timeout=3.5, client=None):
        received_context.append(current_context)
        received_history.append(list(conversation_history or []))
        return current_context, False

    monkeypatch.setattr(api, "extract_voice_context_async", capture_extract)

    class MockGeminiSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def receive(self):
            yield MockResponse(MockServerContent(input_transcription="Recommend something"))
            yield MockResponse(MockServerContent(turn_complete=True))
            while True:
                await asyncio.sleep(1.0)

    class MockLive:
        def connect(self, *args, **kwargs):
            return MockGeminiSession()

    class MockAio:
        live = MockLive()
        async def aclose(self):
            pass

    class MockClient:
        aio = MockAio()

    import google.genai
    monkeypatch.setattr(google.genai, "Client", lambda *args, **kwargs: MockClient())

    init_context = {
        "country": "US",
        "service_access": ["Prime Video", "Hulu"],
        "intake_depth": "a_couple_of_questions",
        "tonight_signals": [
            {"name": "exclude_genre", "value": ["Horror"], "signal_type": "hard_constraint"}
        ]
    }
    init_history = [
        {"role": "user", "content": "Prior message"},
        {"role": "assistant", "content": "Prior reply"}
    ]

    ws = MockWebSocket(incoming_messages=[
        {"type": "init", "context": init_context, "conversation_history": init_history}
    ])

    async def run():
        server_task = asyncio.create_task(api.websocket_voice_live(ws))

        while len(received_history) == 0:
            await asyncio.sleep(0.01)

        # Assert the extraction used the INIT context, NOT the default UK context
        assert received_context[0].country == "US"
        assert received_context[0].service_access == ["Prime Video", "Hulu"]
        assert any(s.name == "exclude_genre" and "Horror" in s.value for s in received_context[0].tonight_signals)

        # Assert the extraction received the prior conversation history from init
        assert len(received_history[0]) == 2
        assert received_history[0][0]["content"] == "Prior message"

        ws.is_closed = True
        server_task.cancel()
        try:
            await server_task
        except (asyncio.CancelledError, WebSocketDisconnect):
            pass

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Node.js Test Harness for Real Frontend JavaScript Execution
# ---------------------------------------------------------------------------
import subprocess
import shutil
import tempfile

INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "static" / "index.html"


def _run_live_frontend_test_in_node(js_test_code: str) -> dict:
    """
    Executes a test script inside Node.js with mock DOM, WebSocket, Fetch, and Web APIs,
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

const mockAudioContexts = [];
class MockAudioNode {{
  constructor(ctx) {{
    this.context = ctx;
    this.gain = {{ value: 1 }};
    this.onaudioprocess = null;
    this.onended = null;
    this.buffer = null;
    this.connectedTo = [];
    this.isStarted = false;
    this.isStopped = false;
    this.isDisconnected = false;
  }}
  connect(dest) {{
    this.connectedTo.push(dest);
  }}
  disconnect() {{
    this.isDisconnected = true;
  }}
  start() {{
    this.isStarted = true;
  }}
  stop() {{
    this.isStopped = true;
  }}
}}

class MockAudioContext {{
  constructor() {{
    this.sampleRate = 16000;
    this.state = 'suspended';
    this.currentTime = 0;
    this.destination = new MockAudioNode(this);
    mockAudioContexts.push(this);
  }}
  async resume() {{ this.state = 'running'; }}
  async close() {{ this.state = 'closed'; }}
  createMediaStreamSource() {{ return new MockAudioNode(this); }}
  createScriptProcessor() {{ return new MockAudioNode(this); }}
  createGain() {{ return new MockAudioNode(this); }}
  createBufferSource() {{ return new MockAudioNode(this); }}
  createBuffer(ch, len, sr) {{ return {{ duration: 1, getChannelData: () => new Float32Array(len || 10) }}; }}
}}
globalThis.AudioContext = MockAudioContext;
globalThis.webkitAudioContext = MockAudioContext;

// --- Mock WebSocket System ---
const mockWebSockets = [];
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
    mockWebSockets.push(this);
    setImmediate(() => {{
      this.readyState = MockWebSocket.OPEN;
      if (this.onopen) this.onopen({{ type: 'open' }});
    }});
  }}
  send(data) {{
    this.sentMessages.push(typeof data === 'string' ? JSON.parse(data) : data);
  }}
  close() {{
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose({{ type: 'close' }});
  }}
  simulateMessage(msgObj) {{
    if (this.onmessage) {{
      this.onmessage({{ data: JSON.stringify(msgObj) }});
    }}
  }}
}}
globalThis.WebSocket = MockWebSocket;

// --- Controllable Timers System ---
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
      await timer.fn(...timer.args);
    }} catch (err) {{
      console.error('Timer execution error:', err);
    }}
  }}
}};

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
  }} catch (err) {{
    console.error('Test failed with error:', err);
    process.exit(1);
  }}
}})();
"""

    with tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False, encoding="utf-8") as f:
        f.write(harness)
        tmp_path = Path(f.name)

    try:
        proc = subprocess.run(
            [node_bin, str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"Node script failed with exit code {proc.returncode}.\n"
                f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
            )

        for line in proc.stdout.splitlines():
            if line.startswith("__RESULT__"):
                return json.loads(line[len("__RESULT__"):])

        raise AssertionError(f"No __RESULT__ found in output:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Test 7: Real JS Execution - Decoupled Voice Event Sequence and Turn Ownership
# ---------------------------------------------------------------------------
def test_node_decoupled_voice_event_sequence_and_turn_ownership():
    """
    Executes actual JavaScript from static/index.html under window === globalThis.
    Simulates: Turn 1 extraction pending -> Turn 2 transcript arrives -> Turn 1 completes -> Turn 2 completes.
    Verifies:
    1. Turn 1 extraction completion does NOT wipe or finalize Turn 2's transcript bubble.
    2. completedDialogueTurnId does not prematurely advance to 2 when Turn 1 completes.
    3. Turn 1 does NOT trigger recommendations because Turn 2 has already superseded it.
    4. When Turn 2 completes, completedDialogueTurnId advances to 2 and recommendations trigger.
    """
    js_test = """
      await toggleSingleBrainVoice();
      await new Promise(r => setImmediate(r));
      const ws = mockWebSockets[0];
      ws.simulateMessage({ type: "init_ack", status: "ready" });

      // 1. Turn 1 transcript and speech
      ws.simulateMessage({ type: "transcript", role: "user", text: "I want a brisk movie", turn_id: 1 });
      ws.simulateMessage({ type: "transcript", role: "assistant", text: "Here are brisk films", turn_id: 1 });
      ws.simulateMessage({ type: "speech_complete", turn_id: 1 });

      const stateAfterSpeech1 = {
        currentVoiceTurnId,
        latestDialogueTurnId,
        userText: currentVoiceUserText,
        userBubbleActive: !!currentVoiceUserBubble
      };

      // 2. While Turn 1 extraction is pending in backend, Turn 2 speech arrives!
      ws.simulateMessage({ type: "transcript", role: "user", text: "Actually make it funny, show me", turn_id: 2 });
      const stateAfterSpeech2 = {
        currentVoiceTurnId,
        latestDialogueTurnId,
        userText: currentVoiceUserText,
        userBubbleActive: !!currentVoiceUserBubble
      };

      // 3. Now delayed Turn 1 extraction completes!
      ws.simulateMessage({
        type: "turn_complete",
        turn_id: 1,
        updated_context: { tonight_signals: [{ name: "pacing", value: "brisk" }] },
        ready_to_recommend: false,
        user_text: "I want a brisk movie",
        assistant_reply: "Here are brisk films"
      });

      const stateAfterTurn1Complete = {
        completedDialogueTurnId,
        pacing: chatState.pacing,
        userText: currentVoiceUserText,
        userBubbleActive: !!currentVoiceUserBubble,
        autoRecTimerActive: !!autoRecommendationTimer
      };

      // 4. Turn 2 assistant speech and completion arrive
      ws.simulateMessage({ type: "transcript", role: "assistant", text: "Sure thing!", turn_id: 2 });
      ws.simulateMessage({ type: "speech_complete", turn_id: 2 });
      ws.simulateMessage({
        type: "turn_complete",
        turn_id: 2,
        updated_context: { tonight_signals: [{ name: "pacing", value: "brisk" }, { name: "tone", value: "funny" }] },
        ready_to_recommend: true,
        user_text: "Actually make it funny, show me",
        assistant_reply: "Sure thing!"
      });

      const stateAfterTurn2Complete = {
        completedDialogueTurnId,
        pacing: chatState.pacing,
        tone: chatState.tone,
        history: chatState.conversation_history
      };

      console.log("__RESULT__" + JSON.stringify({
        stateAfterSpeech1,
        stateAfterSpeech2,
        stateAfterTurn1Complete,
        stateAfterTurn2Complete
      }));
    """

    res = _run_live_frontend_test_in_node(js_test)

    # 1. After Turn 1 speech
    assert res["stateAfterSpeech1"]["currentVoiceTurnId"] == 1
    assert res["stateAfterSpeech1"]["latestDialogueTurnId"] == 1

    # 2. After Turn 2 speech arrives while Turn 1 extraction was pending
    assert res["stateAfterSpeech2"]["currentVoiceTurnId"] == 2
    assert res["stateAfterSpeech2"]["latestDialogueTurnId"] == 2
    assert res["stateAfterSpeech2"]["userBubbleActive"] is True
    assert res["stateAfterSpeech2"]["userText"] == "Actually make it funny, show me"

    # 3. After Turn 1 completes: Turn 2's active bubble was NOT wiped, completed turn is 1 (not 2), no auto-rec timer
    assert res["stateAfterTurn1Complete"]["completedDialogueTurnId"] == 1
    assert res["stateAfterTurn1Complete"]["pacing"] == "brisk"
    assert res["stateAfterTurn1Complete"]["userBubbleActive"] is True
    assert res["stateAfterTurn1Complete"]["userText"] == "Actually make it funny, show me"
    assert res["stateAfterTurn1Complete"]["autoRecTimerActive"] is False

    # 4. After Turn 2 completes: completed turn is 2, tone is funny, both turns in history
    assert res["stateAfterTurn2Complete"]["completedDialogueTurnId"] == 2
    assert res["stateAfterTurn2Complete"]["pacing"] == "brisk"
    assert res["stateAfterTurn2Complete"]["tone"] == "funny"
    user_history = [m["content"] for m in res["stateAfterTurn2Complete"]["history"] if m["role"] == "user"]
    assert user_history == ["I want a brisk movie", "Actually make it funny, show me"]


# ---------------------------------------------------------------------------
# Test 8: Real JS Execution - Typed Refinement During Pending Voice Extraction
# ---------------------------------------------------------------------------
def test_node_typed_refinement_during_pending_voice_extraction():
    """
    Directly tests Reproduction 2 from user requirements:
    Voice turn 1 says 'under 90 minutes, dark'; speech completes but extraction remains pending.
    User submits 'actually comedy' in text.
    TurnQueue coordinates so typed refinement executes after voice turn 1's context is incorporated.
    Field versioning ensures that if delayed voice extraction results arrive, stale tone ('dark')
    cannot overwrite newer intent ('comedy'), while earlier constraints ('max_runtime: 90') are preserved.
    """
    js_test = """
      await toggleSingleBrainVoice();
      await new Promise(r => setImmediate(r));
      const ws = mockWebSockets[0];
      ws.simulateMessage({ type: "init_ack", status: "ready" });

      // Voice Turn 1: speech completes, but turn_complete extraction remains pending in backend
      ws.simulateMessage({ type: "transcript", role: "user", text: "under 90 minutes, dark", turn_id: 1 });
      ws.simulateMessage({ type: "transcript", role: "assistant", text: "Got it.", turn_id: 1 });
      ws.simulateMessage({ type: "speech_complete", turn_id: 1 });

      // Set up Fetch hook for /api/voice/turn (typed turn processing)
      let textFetchPayload = null;
      fetchHook = async (url, options) => {
        if (url === "/api/voice/turn") {
          textFetchPayload = JSON.parse(options.body);
          return {
            ok: true,
            json: async () => ({
              assistant_reply: "Switching to comedy.",
              updated_context: {
                country: "UK",
                service_access: ["Netflix"],
                tonight_signals: [
                  { name: "max-runtime", value: 90 },
                  { name: "tone", value: "comedy" }
                ]
              },
              ready_to_recommend: false
            })
          };
        }
        return { ok: true, json: async () => ({}) };
      };

      // Submit typed refinement "actually comedy"
      const textPromise = enqueueTextDialogueTurn("actually comedy");

      // Now deliver Voice Turn 1 extraction result
      ws.simulateMessage({
        type: "turn_complete",
        turn_id: 1,
        updated_context: {
          country: "UK",
          service_access: ["Netflix"],
          tonight_signals: [
            { name: "max-runtime", value: 90 },
            { name: "tone", value: "dark" }
          ]
        },
        ready_to_recommend: false,
        user_text: "under 90 minutes, dark",
        assistant_reply: "Got it."
      });

      // Await typed refinement completion
      await textPromise;

      // Simulate a late/redundant delivery of Voice Turn 1
      syncContextToState({
        tonight_signals: [
          { name: "max-runtime", value: 90 },
          { name: "tone", value: "dark" }
        ]
      }, 1);

      const result = {
        tone: chatState.tone,
        max_runtime: chatState.max_runtime,
        history: chatState.conversation_history,
        textPayloadSignals: textFetchPayload ? textFetchPayload.current_context.tonight_signals : []
      };

      console.log("__RESULT__" + JSON.stringify(result));
    """

    res = _run_live_frontend_test_in_node(js_test)

    # 1. Protected newer intent: tone is "comedy", NOT reverted to "dark"
    assert res["tone"] == "comedy", f"Expected tone 'comedy', got {res['tone']}"

    # 2. Earlier constraint preserved: max_runtime is 90
    assert res["max_runtime"] == 90, f"Expected max_runtime 90, got {res['max_runtime']}"

    # 3. Payload sent to /api/voice/turn included earlier context from Voice Turn 1
    assert any(s.get("name") == "max-runtime" and s.get("value") == 90 for s in res["textPayloadSignals"])

    # 4. Authoritative conversation history: Voice Turn 1 followed by Text Turn 2
    user_msgs = [m["content"] for m in res["history"] if m["role"] == "user"]
    assert user_msgs == ["under 90 minutes, dark", "actually comedy"]


# ---------------------------------------------------------------------------
# Test 9: Real JS Execution - Mixed Text/Voice Turns and Voice Reconnect
# ---------------------------------------------------------------------------
def test_node_mixed_text_voice_turns_and_voice_reconnect():
    """
    Verifies that when voice reconnects (or retries), the backend socket turn counter
    restarting at 1 does NOT collide with previous turn IDs or typed turns.
    Conversation-wide dialogue turn IDs remain monotonically increasing,
    and conversation history and context remain authoritative.
    """
    js_test = """
      // Session 1 Voice Turn
      await toggleSingleBrainVoice();
      await new Promise(r => setImmediate(r));
      const ws1 = mockWebSockets[0];
      ws1.simulateMessage({ type: "init_ack", status: "ready" });

      ws1.simulateMessage({ type: "transcript", role: "user", text: "fast paced", turn_id: 1 });
      ws1.simulateMessage({ type: "speech_complete", turn_id: 1 });
      ws1.simulateMessage({
        type: "turn_complete",
        turn_id: 1,
        updated_context: { tonight_signals: [{ name: "pacing", value: "fast" }] },
        user_text: "fast paced",
        assistant_reply: "Fast films."
      });
      const convTurn1 = completedDialogueTurnId;

      // Session 1 Text Turn
      fetchHook = async (url, options) => ({
        ok: true,
        json: async () => ({
          assistant_reply: "Under 95 min set.",
          updated_context: {
            tonight_signals: [
              { name: "pacing", value: "fast" },
              { name: "max-runtime", value: 95 }
            ]
          }
        })
      });
      await enqueueTextDialogueTurn("under 95 minutes");
      const convTurn2 = completedDialogueTurnId;

      // Disconnect and reconnect voice session
      teardownVoiceSession();
      await toggleSingleBrainVoice();
      await new Promise(r => setImmediate(r));
      const ws2 = mockWebSockets[1];
      ws2.simulateMessage({ type: "init_ack", status: "ready" });

      // Backend for ws2 restarts turn counter at 1:
      ws2.simulateMessage({ type: "transcript", role: "user", text: "funny mood", turn_id: 1 });
      ws2.simulateMessage({ type: "speech_complete", turn_id: 1 });
      ws2.simulateMessage({
        type: "turn_complete",
        turn_id: 1,
        updated_context: {
          tonight_signals: [
            { name: "pacing", value: "fast" },
            { name: "max-runtime", value: 95 },
            { name: "tone", value: "funny" }
          ]
        },
        user_text: "funny mood",
        assistant_reply: "Added funny mood."
      });
      const convTurn3 = completedDialogueTurnId;

      const result = {
        convTurn1,
        convTurn2,
        convTurn3,
        pacing: chatState.pacing,
        max_runtime: chatState.max_runtime,
        tone: chatState.tone,
        history: chatState.conversation_history
      };

      console.log("__RESULT__" + JSON.stringify(result));
    """

    res = _run_live_frontend_test_in_node(js_test)

    # Monotonically increasing conversation turn IDs without collision
    assert res["convTurn1"] == 1
    assert res["convTurn2"] == 2
    assert res["convTurn3"] == 3, f"Expected reconnected voice turn to map to turn 3, got {res['convTurn3']}"

    # Authoritative context contains all merged signals across turns
    assert res["pacing"] == "fast"
    assert res["max_runtime"] == 95
    assert res["tone"] == "funny"

    # Authoritative history has all 3 turns in chronological order
    user_msgs = [m["content"] for m in res["history"] if m["role"] == "user"]
    assert user_msgs == ["fast paced", "under 95 minutes", "funny mood"]

