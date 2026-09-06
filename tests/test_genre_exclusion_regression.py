"""
Behavioral regression tests verifying TONI genre exclusions in the frontend.

Ensures that:
1. Dropdown choices in the UI survive into both voice/text context payloads and recommendation requests.
2. Multiple exclusions (e.g. from conversational context or personas) are preserved without truncation.
3. Intentionally clearing exclusions (e.g. selecting "Nothing to rule out") removes the exclusion from requests.
4. An empty array in exclude_genres never shadows exclude_genre.

These tests execute the actual JavaScript from static/index.html using Node.js and inspect the resulting payloads.
"""

import json
import shutil
import subprocess
from pathlib import Path
import pytest

INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "static" / "index.html"


def _run_js_in_node(js_test_code: str) -> dict:
    """
    Executes a test script inside Node.js that loads the actual <script>
    from static/index.html in a DOM-compatible test harness and returns JSON output.
    """
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("node is not available on PATH")

    html_content = INDEX_HTML_PATH.read_text(encoding="utf-8")
    last_script_start = html_content.rfind("<script>")
    last_script_end = html_content.rfind("</script>")
    assert last_script_start != -1 and last_script_end != -1, "Main script tag not found in static/index.html"

    app_script = html_content[last_script_start + 8 : last_script_end]

    harness = f"""
const elements = {{}};
const getOrCreateElement = (id) => {{
  if (!elements[id]) {{
    elements[id] = {{
      id,
      className: '',
      style: {{}},
      dataset: {{}},
      classList: {{ add() {{}}, remove() {{}} }},
      appendChild() {{}},
      querySelectorAll() {{ return []; }},
      scrollTo() {{}},
      innerHTML: '',
      value: '',
      addEventListener() {{}},
      removeEventListener() {{}}
    }};
  }}
  return elements[id];
}};

const window = {{
  addEventListener() {{}},
  location: {{ search: '' }}
}};

const document = {{
  createElement(tag) {{
    return {{
      tagName: tag.toUpperCase(),
      className: '',
      style: {{}},
      setAttribute() {{}},
      getAttribute() {{ return ''; }},
      appendChild() {{}},
      replaceWith() {{}},
      querySelectorAll() {{ return []; }},
      querySelector() {{ return null; }},
      classList: {{ add() {{}}, remove() {{}} }},
      textContent: '',
      addEventListener() {{}},
      removeEventListener() {{}}
    }};
  }},
  getElementById: getOrCreateElement,
  querySelectorAll() {{ return []; }},
  addEventListener() {{}}
}};

let lastFetchCall = null;
global.window = window;
global.document = document;
global.fetch = (url, options) => {{
  lastFetchCall = {{
    url,
    options,
    body: options && options.body ? JSON.parse(options.body) : null
  }};
  return Promise.resolve({{
    ok: true,
    json: () => Promise.resolve({{ recommendations: [] }})
  }});
}};

// Load and evaluate static/index.html application script
{app_script}

// Test block
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

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", encoding="utf-8", delete=False) as tf:
        tf.write(harness)
        temp_path = Path(tf.name)

    try:
        res = subprocess.run(
            [node_bin, str(temp_path)],
            capture_output=True,
            text=True,
            cwd=str(INDEX_HTML_PATH.parent.parent),
            timeout=10
        )
        if res.returncode != 0:
            pytest.fail(f"Node script execution failed (code {res.returncode}):\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass

    try:
        return json.loads(res.stdout.strip())
    except json.JSONDecodeError as exc:
        pytest.fail(f"Could not parse JSON output from Node test:\nOutput was:\n{res.stdout}\nError: {exc}")


def test_dropdown_selection_populates_voice_and_recommendation_payloads():
    """
    Simulates user selecting 'Horror' from the dropdown and verifying
    both voice turn payload and recommendation pipeline request receive ['Horror'].
    """
    js = """
    window.chatState.intake_depth = 'get_to_know_me';
    window.renderStep4();

    // User explicitly selects Horror in dropdown
    const selectEl = document.getElementById('chat-exclude-genre');
    selectEl.value = 'Horror';
    selectEl.onchange();
    window.confirmStep4();

    const voicePayload = window.buildVoiceTurnPayload('find me a movie', 'text');
    await window.triggerPipelineExecution();

    console.log(JSON.stringify({
      voice_signals: voicePayload.current_context.tonight_signals,
      recommend_signals: lastFetchCall ? lastFetchCall.body.tonight_signals : null,
      chat_exclude_genre: window.chatState.exclude_genre,
      chat_exclude_genres: window.chatState.exclude_genres
    }));
    """
    out = _run_js_in_node(js)

    voice_exclude = [s for s in out["voice_signals"] if s["name"] == "exclude-genre"]
    assert len(voice_exclude) == 1, f"Expected exclude-genre in voice payload, got: {out['voice_signals']}"
    assert voice_exclude[0]["value"] == ["Horror"]
    assert voice_exclude[0]["signal_type"] == "hard_constraint"

    recommend_exclude = [s for s in out["recommend_signals"] if s["name"] == "exclude-genre"]
    assert len(recommend_exclude) == 1, f"Expected exclude-genre in recommend payload, got: {out['recommend_signals']}"
    assert recommend_exclude[0]["value"] == ["Horror"]
    assert recommend_exclude[0]["signal_type"] == "hard_constraint"

    assert out["chat_exclude_genre"] == "Horror"
    assert out["chat_exclude_genres"] == ["Horror"]


def test_multiple_exclusions_survive_unchanged_step4_confirmation():
    """
    Verifies that multiple exclusions (e.g. from conversation or personas)
    survive unchanged Step 4 confirmation without being overwritten by single-select value.
    """
    js = """
    window.syncContextToState({
      tonight_signals: [
        { name: 'exclude-genre', value: ['Horror', 'Sci-Fi'], signal_type: 'hard_constraint' }
      ]
    });
    window.chatState.intake_depth = 'get_to_know_me';
    window.renderStep4();

    // User confirms Step 4 WITHOUT modifying or changing the dropdown
    window.confirmStep4();

    const voicePayload = window.buildVoiceTurnPayload('continue conversation', 'voice');
    await window.triggerPipelineExecution();

    console.log(JSON.stringify({
      voice_signals: voicePayload.current_context.tonight_signals,
      recommend_signals: lastFetchCall ? lastFetchCall.body.tonight_signals : null,
      effective_exclusions: window.getEffectiveExcludedGenres(),
      chat_exclude_genres: window.chatState.exclude_genres
    }));
    """
    out = _run_js_in_node(js)

    voice_exclude = [s for s in out["voice_signals"] if s["name"] == "exclude-genre"]
    assert len(voice_exclude) == 1
    assert voice_exclude[0]["value"] == ["Horror", "Sci-Fi"]

    recommend_exclude = [s for s in out["recommend_signals"] if s["name"] == "exclude-genre"]
    assert len(recommend_exclude) == 1
    assert recommend_exclude[0]["value"] == ["Horror", "Sci-Fi"]
    assert out["effective_exclusions"] == ["Horror", "Sci-Fi"]
    assert out["chat_exclude_genres"] == ["Horror", "Sci-Fi"]


def test_absent_exclusion_survives_unchanged_step4_confirmation():
    """
    Verifies that an exclusion absent from the dropdown options (e.g. 'Romance')
    survives unchanged Step 4 confirmation without being cleared by the default dropdown value.
    """
    js = """
    window.syncContextToState({
      tonight_signals: [
        { name: 'exclude-genre', value: ['Romance'], signal_type: 'hard_constraint' }
      ]
    });
    window.chatState.intake_depth = 'get_to_know_me';
    window.renderStep4();

    // User confirms Step 4 WITHOUT modifying or changing the dropdown
    window.confirmStep4();

    const voicePayload = window.buildVoiceTurnPayload('find romance-free film', 'text');
    await window.triggerPipelineExecution();

    console.log(JSON.stringify({
      voice_signals: voicePayload.current_context.tonight_signals,
      recommend_signals: lastFetchCall ? lastFetchCall.body.tonight_signals : null,
      effective_exclusions: window.getEffectiveExcludedGenres(),
      chat_exclude_genres: window.chatState.exclude_genres
    }));
    """
    out = _run_js_in_node(js)

    voice_exclude = [s for s in out["voice_signals"] if s["name"] == "exclude-genre"]
    assert len(voice_exclude) == 1, f"Expected exclude-genre in voice payload, got {out['voice_signals']}"
    assert voice_exclude[0]["value"] == ["Romance"]

    recommend_exclude = [s for s in out["recommend_signals"] if s["name"] == "exclude-genre"]
    assert len(recommend_exclude) == 1, f"Expected exclude-genre in recommend payload, got {out['recommend_signals']}"
    assert recommend_exclude[0]["value"] == ["Romance"]
    assert out["effective_exclusions"] == ["Romance"]
    assert out["chat_exclude_genres"] == ["Romance"]


def test_explicitly_changing_or_clearing_dropdown_updates_payloads():
    """
    Verifies that explicitly changing or clearing the dropdown in Step 4
    updates both voice and recommendation payloads correctly through the confirmation path.
    """
    js = """
    // 1. Start with multiple exclusions
    window.syncContextToState({
      tonight_signals: [
        { name: 'exclude-genre', value: ['Horror', 'Sci-Fi'], signal_type: 'hard_constraint' }
      ]
    });
    window.chatState.intake_depth = 'get_to_know_me';
    window.renderStep4();

    // Explicitly change dropdown to 'Crime'
    const selectEl = document.getElementById('chat-exclude-genre');
    selectEl.value = 'Crime';
    selectEl.onchange();
    window.confirmStep4();

    const voicePayload1 = window.buildVoiceTurnPayload('update to crime', 'text');
    await window.triggerPipelineExecution();
    const recommendSignals1 = lastFetchCall ? lastFetchCall.body.tonight_signals : null;

    // 2. Now explicitly clear the dropdown to '' (Nothing to rule out)
    window.chatState.step = 4;
    window.renderStep4();
    selectEl.value = '';
    selectEl.onchange();
    window.confirmStep4();

    const voicePayload2 = window.buildVoiceTurnPayload('update to cleared', 'text');
    await window.triggerPipelineExecution();
    const recommendSignals2 = lastFetchCall ? lastFetchCall.body.tonight_signals : null;

    console.log(JSON.stringify({
      voice_signals_1: voicePayload1.current_context.tonight_signals,
      recommend_signals_1: recommendSignals1,
      voice_signals_2: voicePayload2.current_context.tonight_signals,
      recommend_signals_2: recommendSignals2,
      effective_exclusions_2: window.getEffectiveExcludedGenres()
    }));
    """
    out = _run_js_in_node(js)

    # Check state after explicitly changing to Crime
    voice_exclude_1 = [s for s in out["voice_signals_1"] if s["name"] == "exclude-genre"]
    assert len(voice_exclude_1) == 1
    assert voice_exclude_1[0]["value"] == ["Crime"]

    rec_exclude_1 = [s for s in out["recommend_signals_1"] if s["name"] == "exclude-genre"]
    assert len(rec_exclude_1) == 1
    assert rec_exclude_1[0]["value"] == ["Crime"]

    # Check state after explicitly clearing to ''
    voice_exclude_2 = [s for s in out["voice_signals_2"] if s["name"] == "exclude-genre"]
    assert len(voice_exclude_2) == 0, f"Expected no exclude-genre after clearing, got {voice_exclude_2}"

    rec_exclude_2 = [s for s in out["recommend_signals_2"] if s["name"] == "exclude-genre"]
    assert len(rec_exclude_2) == 0, f"Expected no exclude-genre in recommend after clearing, got {rec_exclude_2}"
    assert out["effective_exclusions_2"] == []


def test_empty_exclude_genres_does_not_shadow_dropdown_selection():
    """
    Direct reproduction test of the bug:
    In unpatched code, chatState.exclude_genres was initialized to [] (which is truthy in JS),
    and chatState.exclude_genre was set by the dropdown.
    Verifies that setting chatState.exclude_genre directly is never shadowed by an empty array.
    """
    js = """
    // Explicitly test direct assignment to chatState.exclude_genre
    window.chatState.exclude_genre = 'Crime';

    const voicePayload = window.buildVoiceTurnPayload('mood', 'text');
    await window.triggerPipelineExecution();

    console.log(JSON.stringify({
      voice_signals: voicePayload.current_context.tonight_signals,
      recommend_signals: lastFetchCall ? lastFetchCall.body.tonight_signals : null,
      effective_exclusions: window.getEffectiveExcludedGenres()
    }));
    """
    out = _run_js_in_node(js)

    voice_exclude = [s for s in out["voice_signals"] if s["name"] == "exclude-genre"]
    assert len(voice_exclude) == 1
    assert voice_exclude[0]["value"] == ["Crime"]

    recommend_exclude = [s for s in out["recommend_signals"] if s["name"] == "exclude-genre"]
    assert len(recommend_exclude) == 1
    assert recommend_exclude[0]["value"] == ["Crime"]
    assert out["effective_exclusions"] == ["Crime"]


def test_persona_loading_and_reset_behavior():
    """
    Verifies persona loading sets exclusions, and loading another persona without exclusions
    resets them cleanly.
    """
    js = """
    // 1. Persona with exclusion
    const personaWithExclusion = {
      country: 'UK',
      service_access: ['Netflix'],
      allow_rent_buy: false,
      intake_depth: 'deep',
      tonight_signals: [
        { name: 'exclude_genre', value: ['Horror'] }
      ]
    };
    window.applyPersona(personaWithExclusion, 'Persona With Horror Excluded');

    const voicePayload1 = window.buildVoiceTurnPayload('test', 'text');
    await window.triggerPipelineExecution();
    const signals1 = lastFetchCall ? lastFetchCall.body.tonight_signals : null;

    // 2. Persona without exclusion
    const personaWithoutExclusion = {
      country: 'UK',
      service_access: ['Netflix'],
      allow_rent_buy: false,
      intake_depth: 'quick',
      tonight_signals: []
    };
    window.applyPersona(personaWithoutExclusion, 'Persona Neutral');

    const voicePayload2 = window.buildVoiceTurnPayload('test', 'text');
    await window.triggerPipelineExecution();
    const signals2 = lastFetchCall ? lastFetchCall.body.tonight_signals : null;

    console.log(JSON.stringify({
      persona1_recommend_signals: signals1,
      persona2_recommend_signals: signals2
    }));
    """
    out = _run_js_in_node(js)

    p1_exclude = [s for s in out["persona1_recommend_signals"] if s["name"] == "exclude-genre"]
    assert len(p1_exclude) == 1
    assert p1_exclude[0]["value"] == ["Horror"]

    p2_exclude = [s for s in out["persona2_recommend_signals"] if s["name"] == "exclude-genre"]
    assert len(p2_exclude) == 0
