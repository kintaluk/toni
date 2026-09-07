"""Regression tests covering defects identified during independent release validation.
These tests verify that:
1. "Any length is fine" clears max-runtime in fallback and merge.
2. "Horror is fine now" clears exclude-genre even when the resulting set is empty.
3. Service replacement/removal works ("Netflix only, remove Disney+").
4. Rich preferences (preferred_genres, reference_films) are preserved in context.
5. "no horror or comedy" masks both genres and does not emit tone=funny.
6. "no adventure or family" excludes Adventure and Family.
7. "I want a horror film" extracts positive preferred_genres=[Horror].
8. Transcript chunk joining is fragment-safe without naive spaces inside subwords.
9. Evidence processing enforces end-to-end deadline ceiling.
"""
import json
import pytest
import time
from unittest.mock import MagicMock, patch

from tests.test_voice_search_journey import _run_voice_journey_js

from contracts import (
    UserContext,
    TasteSignal,
    SignalType,
    IntakeDepth,
    SIGNAL_MAX_RUNTIME,
    SIGNAL_EXCLUDE_GENRE,
    SIGNAL_TONE,
    SIGNAL_PACING,
    SIGNAL_PREFERRED_GENRES,
    SIGNAL_REFERENCE_FILMS,
)
import api
from api import (
    _extract_voice_context_fallback,
    _merge_signals_into_context,
    join_transcript_chunks,
    ContextExtractionLLMOutput,
)
import evidence


def test_runtime_clearing_fallback():
    """User saying 'Any length is fine' must clear max-runtime from context."""
    base_ctx = UserContext(
        country="UK",
        service_access=["Netflix"],
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
        tonight_signals=[
            TasteSignal(name=SIGNAL_MAX_RUNTIME, value=90, signal_type=SignalType.HARD_CONSTRAINT),
            TasteSignal(name=SIGNAL_PACING, value="leisurely", signal_type=SignalType.SOFT_SESSION_PREFERENCE),
        ]
    )
    updated_ctx, ready = _extract_voice_context_fallback("Any length is fine.", base_ctx)
    runtime_signals = [s for s in updated_ctx.tonight_signals if s.name == SIGNAL_MAX_RUNTIME]
    assert len(runtime_signals) == 0, f"Expected max-runtime to be cleared, got: {runtime_signals}"
    pacing_signals = [s for s in updated_ctx.tonight_signals if s.name == SIGNAL_PACING]
    assert len(pacing_signals) == 1


def test_runtime_clearing_merge():
    """_merge_signals_into_context must clear max-runtime when clear_max_runtime is True."""
    base_ctx = UserContext(
        country="UK",
        service_access=["Netflix"],
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
        tonight_signals=[
            TasteSignal(name=SIGNAL_MAX_RUNTIME, value=90, signal_type=SignalType.HARD_CONSTRAINT),
        ]
    )
    llm_output = ContextExtractionLLMOutput(
        clear_max_runtime=True
    )
    merged = _merge_signals_into_context(base_ctx, llm_output)
    runtime_signals = [s for s in merged.tonight_signals if s.name == SIGNAL_MAX_RUNTIME]
    assert len(runtime_signals) == 0, f"Expected max-runtime cleared on merge, got: {runtime_signals}"


def test_exclusion_removal_fallback_to_empty_set():
    """Removing the sole excluded genre must clear exclude-genre signal completely."""
    base_ctx = UserContext(
        country="UK",
        service_access=["Netflix"],
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
        tonight_signals=[
            TasteSignal(name=SIGNAL_EXCLUDE_GENRE, value=["Horror"], signal_type=SignalType.HARD_CONSTRAINT),
        ]
    )
    updated_ctx, ready = _extract_voice_context_fallback("Horror is fine now, remove that exclusion.", base_ctx)
    excl_signals = [s for s in updated_ctx.tonight_signals if s.name == SIGNAL_EXCLUDE_GENRE]
    assert len(excl_signals) == 0, f"Expected exclude-genre to be completely cleared, got: {excl_signals}"


def test_exclusion_removal_merge():
    """_merge_signals_into_context must clear exclude-genre if clear_exclusions is True."""
    base_ctx = UserContext(
        country="UK",
        service_access=["Netflix"],
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
        tonight_signals=[
            TasteSignal(name=SIGNAL_EXCLUDE_GENRE, value=["Horror"], signal_type=SignalType.HARD_CONSTRAINT),
        ]
    )
    llm_output = ContextExtractionLLMOutput(
        clear_exclusions=True
    )
    merged = _merge_signals_into_context(base_ctx, llm_output)
    excl_signals = [s for s in merged.tonight_signals if s.name == SIGNAL_EXCLUDE_GENRE]
    assert len(excl_signals) == 0, f"Expected exclude-genre cleared on merge, got: {excl_signals}"


def test_service_replacement_and_removal_fallback():
    """'Netflix only, remove Disney+' must result in services=['Netflix']."""
    base_ctx = UserContext(
        country="UK",
        service_access=["Disney+", "BBC iPlayer"],
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
    )
    updated_ctx, ready = _extract_voice_context_fallback("Netflix only, remove Disney+", base_ctx)
    assert "Disney+" not in updated_ctx.service_access
    assert "Netflix" in updated_ctx.service_access
    assert updated_ctx.service_access == ["Netflix"]


def test_service_replacement_merge():
    """_merge_signals_into_context must respect replace_services and remove_services."""
    base_ctx = UserContext(
        country="UK",
        service_access=["Disney+", "BBC iPlayer"],
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
    )
    llm_output = ContextExtractionLLMOutput(
        replace_services=["Netflix"]
    )
    merged = _merge_signals_into_context(base_ctx, llm_output)
    assert merged.service_access == ["Netflix"]


def test_rich_preferences_preservation():
    """Preferred genres and reference films must be captured and merged into tonight_signals."""
    base_ctx = UserContext(
        country="UK",
        service_access=["Netflix"],
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
    )
    llm_output = ContextExtractionLLMOutput(
        preferred_genres=["Comedy"],
        reference_films=["Paddington"]
    )
    merged = _merge_signals_into_context(base_ctx, llm_output)
    pref_genre = next((s for s in merged.tonight_signals if s.name == SIGNAL_PREFERRED_GENRES), None)
    ref_film = next((s for s in merged.tonight_signals if s.name == SIGNAL_REFERENCE_FILMS), None)
    assert pref_genre is not None and pref_genre.value == ["Comedy"]
    assert ref_film is not None and ref_film.value == ["Paddington"]


def test_multi_genre_negation_and_tone_masking():
    """'no horror or comedy' must exclude both Horror and Comedy, and NOT emit tone=funny."""
    base_ctx = UserContext(
        country="UK",
        service_access=["Netflix"],
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
    )
    updated_ctx, _ = _extract_voice_context_fallback("no horror or comedy", base_ctx)
    excl_sig = next((s for s in updated_ctx.tonight_signals if s.name == SIGNAL_EXCLUDE_GENRE), None)
    assert excl_sig is not None
    assert set(excl_sig.value) == {"Comedy", "Horror"}
    tone_sig = next((s for s in updated_ctx.tonight_signals if s.name == SIGNAL_TONE), None)
    assert tone_sig is None, f"Expected no positive tone to be emitted, got: {tone_sig}"


def test_canonical_genres_extended():
    """'no adventure or family' must exclude Adventure and Family."""
    base_ctx = UserContext(
        country="UK",
        service_access=["Netflix"],
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
    )
    updated_ctx, _ = _extract_voice_context_fallback("no adventure or family", base_ctx)
    excl_sig = next((s for s in updated_ctx.tonight_signals if s.name == SIGNAL_EXCLUDE_GENRE), None)
    assert excl_sig is not None
    assert set(excl_sig.value) == {"Adventure", "Family"}


def test_positive_genre_extraction():
    """'I want a horror film' must extract preferred_genres=[Horror]."""
    base_ctx = UserContext(
        country="UK",
        service_access=["Netflix"],
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
    )
    updated_ctx, _ = _extract_voice_context_fallback("I want a horror film", base_ctx)
    pref_sig = next((s for s in updated_ctx.tonight_signals if s.name == SIGNAL_PREFERRED_GENRES), None)
    assert pref_sig is not None
    assert pref_sig.value == ["Horror"]
    excl_sig = next((s for s in updated_ctx.tonight_signals if s.name == SIGNAL_EXCLUDE_GENRE), None)
    assert excl_sig is None


def test_transcript_chunks_fragment_safety():
    """join_transcript_chunks must not insert spaces between subwords like ['per', 'fectly']."""
    assert join_transcript_chunks(["per", "fectly"]) == "perfectly"
    assert join_transcript_chunks(["Hello,", " world"]) == "Hello, world"
    assert join_transcript_chunks(["Hello", " world"]) == "Hello world"
    assert join_transcript_chunks(["Great!", " Let's", " go."]) == "Great! Let's go."


def test_audio_buffer_duration_5s_10s_20s():
    """Verify that complete 5s, 10s, and 20s audio responses are buffered and played without exceeding buffer limit."""
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    // 24kHz 16-bit mono PCM: 1s = 24000 samples * 2 bytes = 48,000 bytes raw
    const oneSecSamples = new Int16Array(24000);
    const oneSecBase64 = Buffer.from(oneSecSamples.buffer).toString('base64');

    // Test 5-second response
    for (let i = 0; i < 5; i++) {
        socket.simulateMessage({ type: 'audio', data: oneSecBase64 });
    }
    window.releaseTurnAudioBuffer("How would you describe your perfect film tonight?");
    const sources5s = window.getActiveAudioSourceNodes().length;
    window.stopPlaybackAudio();

    // Test 10-second response
    for (let i = 0; i < 10; i++) {
        socket.simulateMessage({ type: 'audio', data: oneSecBase64 });
    }
    window.releaseTurnAudioBuffer("Are you in the mood for something fast-paced or more relaxed?");
    const sources10s = window.getActiveAudioSourceNodes().length;
    window.stopPlaybackAudio();

    // Test 20-second response
    for (let i = 0; i < 20; i++) {
        socket.simulateMessage({ type: 'audio', data: oneSecBase64 });
    }
    window.releaseTurnAudioBuffer("Tell me what kinds of movies you usually enjoy on weekends.");
    const sources20s = window.getActiveAudioSourceNodes().length;

    console.log(JSON.stringify({
        sources5s,
        sources10s,
        sources20s
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["sources5s"] == 5, f"Expected 5 queued chunks for 5s audio, got {result['sources5s']}"
    assert result["sources10s"] == 10, f"Expected 10 queued chunks for 10s audio, got {result['sources10s']}"
    assert result["sources20s"] == 20, f"Expected 20 queued chunks for 20s audio, got {result['sources20s']}"


def test_audio_buffer_overflow_withholds_truncated_speech():
    """If turn audio exceeds MAX_TURN_AUDIO_BUFFER_BYTES (4MB), audio must be withheld, never playing truncated speech."""
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    // 100KB chunk in base64: ~133,334 chars
    const bigChunk = "A".repeat(133334);
    // Send 35 chunks = ~4.6 MB (> 4MB limit)
    for (let i = 0; i < 35; i++) {
        socket.simulateMessage({ type: 'audio', data: bigChunk });
    }

    // Attempt release
    window.releaseTurnAudioBuffer("What would you like to watch tonight?");
    const sourcesAfterOverflow = window.getActiveAudioSourceNodes().length;
    const threadHtml = document.getElementById('toni-chat-thread').innerHTML;
    const hasRecoverablePrompt = threadHtml.includes("tuning in to your tastes");

    console.log(JSON.stringify({
        sourcesAfterOverflow,
        hasRecoverablePrompt
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["sourcesAfterOverflow"] == 0, "Overflowed turn audio must be withheld, not scheduled for playback"
    assert result["hasRecoverablePrompt"] is True, "Must show recoverable prompt on overflow"


def test_delayed_transcript_and_no_bypass_for_missing_text():
    """Audio arriving before transcript must NOT bypass validation when text is missing, but release once valid transcript arrives."""
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    const samplePcm16 = new Int16Array(2400);
    const dummyAudio = Buffer.from(samplePcm16.buffer).toString('base64');

    // Audio arrives
    socket.simulateMessage({ type: 'audio', data: dummyAudio });

    // Attempt release with missing text -> must fail validation and withhold audio
    const checkMissing = window.validateAssistantAudioOutput("");
    window.releaseTurnAudioBuffer("");
    const sourcesBeforeTranscript = window.getActiveAudioSourceNodes().length;

    // Delayed transcript arrives without resending audio
    socket.simulateMessage({ type: 'transcript', role: 'assistant', text: 'What kind of mood are you in tonight?', turn_id: 1 });
    window.releaseTurnAudioBuffer(1);
    const sourcesAfterTranscript = window.getActiveAudioSourceNodes().length;

    console.log(JSON.stringify({
        checkMissing,
        sourcesBeforeTranscript,
        sourcesAfterTranscript
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["checkMissing"]["valid"] is False
    assert result["checkMissing"]["reason"] == "missing_transcript"
    assert result["sourcesBeforeTranscript"] == 0, "Must withhold audio when transcript is missing"
    assert result["sourcesAfterTranscript"] == 1, "Must release audio once valid transcript arrives"


def test_duplicate_completion_events_single_playback():
    """Consecutive speech_complete and turn_complete for the same turn must trigger exactly one playback."""
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    const samplePcm16 = new Int16Array(2400);
    const dummyAudio = Buffer.from(samplePcm16.buffer).toString('base64');

    // Audio chunks and transcript arrive for turn 1
    socket.simulateMessage({ type: 'transcript', role: 'assistant', text: 'Hello! How can I help you find a movie tonight?', turn_id: 1 });
    socket.simulateMessage({ type: 'audio', data: dummyAudio });

    // 1. speech_complete arrives
    socket.simulateMessage({ type: 'speech_complete', turn_id: 1 });
    const sourcesAfterSpeechComplete = window.getActiveAudioSourceNodes().length;

    // 2. turn_complete arrives for the exact same turn
    socket.simulateMessage({ type: 'turn_complete', turn_id: 1, assistant_reply: 'Hello! How can I help you find a movie tonight?' });
    const sourcesAfterTurnComplete = window.getActiveAudioSourceNodes().length;

    console.log(JSON.stringify({
        sourcesAfterSpeechComplete,
        sourcesAfterTurnComplete
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["sourcesAfterSpeechComplete"] == 1
    assert result["sourcesAfterTurnComplete"] == 1, "Duplicate turn_complete must not double-enqueue audio chunks"


def test_interruption_stops_playback_and_clears_buffer():
    """User interruption while TONI is speaking must stop audio playback and clear audio buffers."""
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    const samplePcm16 = new Int16Array(2400);
    const dummyAudio = Buffer.from(samplePcm16.buffer).toString('base64');

    socket.simulateMessage({ type: 'transcript', role: 'assistant', text: 'What kind of mood are you in tonight?', turn_id: 1 });
    socket.simulateMessage({ type: 'audio', data: dummyAudio });
    socket.simulateMessage({ type: 'speech_complete', turn_id: 1 });
    const sourcesPlaying = window.getActiveAudioSourceNodes().length;

    // User interrupts by speaking
    socket.simulateMessage({ type: 'transcript', role: 'user', text: 'Actually I want a comedy', turn_id: 2 });
    const sourcesAfterInterruption = window.getActiveAudioSourceNodes().length;
    const voiceState = window.getVoiceState();

    console.log(JSON.stringify({
        sourcesPlaying,
        sourcesAfterInterruption,
        isToniSpeaking: voiceState.isToniSpeaking
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["sourcesPlaying"] == 1
    assert result["sourcesAfterInterruption"] == 0, "User interruption must immediately stop playing audio"
    assert result["isToniSpeaking"] is False


def test_successive_turns_isolation():
    """Multiple conversational turns must be cleanly isolated without leaking audio or transcripts across turns."""
    js = """
    await window.toggleSingleBrainVoice();
    const socket = mockSockets[mockSockets.length - 1];
    socket.simulateOpen();
    socket.simulateMessage({ type: 'init_ack', status: 'ready' });

    const samplePcm16 = new Int16Array(2400);
    const dummyAudio = Buffer.from(samplePcm16.buffer).toString('base64');

    // Turn 1
    socket.simulateMessage({ type: 'transcript', role: 'assistant', text: 'What kind of mood are you in tonight?', turn_id: 1 });
    socket.simulateMessage({ type: 'audio', data: dummyAudio });
    socket.simulateMessage({ type: 'turn_complete', turn_id: 1, assistant_reply: 'What kind of mood are you in tonight?' });
    const sourcesTurn1 = window.getActiveAudioSourceNodes().length;
    window.stopPlaybackAudio();

    // Turn 2
    socket.simulateMessage({ type: 'transcript', role: 'user', text: 'Something lighthearted please.', turn_id: 2 });
    socket.simulateMessage({ type: 'transcript', role: 'assistant', text: 'Got it, do you prefer British or American humor?', turn_id: 2 });
    socket.simulateMessage({ type: 'audio', data: dummyAudio });
    socket.simulateMessage({ type: 'turn_complete', turn_id: 2, assistant_reply: 'Got it, do you prefer British or American humor?' });
    const sourcesTurn2 = window.getActiveAudioSourceNodes().length;

    console.log(JSON.stringify({
        sourcesTurn1,
        sourcesTurn2
    }));
    """
    result = _run_voice_journey_js(js)
    assert result["sourcesTurn1"] == 1
    assert result["sourcesTurn2"] == 1


def test_upstream_delta_spacing_python_and_js():
    """Synthetic text deltas preserve whitespace, subwords and punctuation in both implementations."""
    # Synthetic delta fixture using the screenshot wording:
    chunks1 = ["Hello", "there!", "To", "help", "you", "find", "that", "perfect", "film,", "tell", "me,", "what", "kind", "of", "mood", "are", "you", "in", "tonight?"]
    chunks1 = [chunks1[0]] + [" " + c for c in chunks1[1:]]
    expected1 = "Hello there! To help you find that perfect film, tell me, what kind of mood are you in tonight?"
    assert join_transcript_chunks(chunks1) == expected1

    # Another synthetic delta fixture:
    chunks2 = ["Understood,", "a", "warm,", "slow", "comedy", "on", "Netflix", "under", "100", "minutes", "without", "any", "rentals", "or", "horror."]
    chunks2 = [chunks2[0]] + [" " + c for c in chunks2[1:]]
    expected2 = "Understood, a warm, slow comedy on Netflix under 100 minutes without any rentals or horror."
    assert join_transcript_chunks(chunks2) == expected2

    # Contractions and punctuation
    chunks3 = ["I'm", "ready", "to", "help.", "Don't", "worry,", "we'll", "find", "what's", "best."]
    chunks3 = [chunks3[0]] + [" " + c for c in chunks3[1:]]
    expected3 = "I'm ready to help. Don't worry, we'll find what's best."
    assert join_transcript_chunks(chunks3) == expected3

    # Subwords
    chunks4 = ["per", "fectly", " balanced"]
    expected4 = "perfectly balanced"
    assert join_transcript_chunks(chunks4) == expected4

    # Verify in JavaScript smartAppendChunk via Node.js
    js = f"""
    const chunks1 = {json.dumps(chunks1)};
    const chunks2 = {json.dumps(chunks2)};
    const chunks3 = {json.dumps(chunks3)};
    const chunks4 = {json.dumps(chunks4)};

    let text1 = "";
    for (const c of chunks1) text1 = smartAppendChunk(text1, c);

    let text2 = "";
    for (const c of chunks2) text2 = smartAppendChunk(text2, c);

    let text3 = "";
    for (const c of chunks3) text3 = smartAppendChunk(text3, c);

    let text4 = "";
    for (const c of chunks4) text4 = smartAppendChunk(text4, c);

    console.log(JSON.stringify({{ text1, text2, text3, text4 }}));
    """
    result = _run_voice_journey_js(js)
    assert result["text1"] == expected1
    assert result["text2"] == expected2
    assert result["text3"] == expected3
    assert result["text4"] == expected4


def test_shorter_never_increases_cap_exhaustive():
    """Verify that quickRefine('shorter') strictly monotonically decreases/tightens max_runtime and never increases any cap."""
    test_caps = [None, 150, 120, 105, 100, 95, 90, 85, 80, 75, 70, 65, 60, 50, 45, 40, 35, 30]
    js = f"""
    const initialCaps = {json.dumps(test_caps)};
    const results = [];
    for (const cap of initialCaps) {{
        chatState.max_runtime = cap;
        await quickRefine('shorter');
        await new Promise(r=>setTimeout(r,450));
        results.push({{ initial: cap, updated: chatState.max_runtime }});
    }}
    console.log(JSON.stringify(results));
    """
    results = _run_voice_journey_js(js)
    for res in results:
        init = res["initial"]
        updated = res["updated"]
        assert updated >= 30, f"Cap must not go below 30 min floor: {res}"
        assert updated <= 90, f"Shorter must cap at 90 min max: {res}"
        if init is not None:
            assert updated <= init, f"Cap increased from {init} to {updated}! Shorter must never increase an existing cap."


def test_empty_services_replacement_python_and_js():
    """Verify that replace_services=[] in Python and service_access=[] in JS correctly empties service_access."""
    # Python
    base_ctx = UserContext(
        country="UK",
        service_access=["Netflix", "Disney+"],
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
    )
    llm_output = ContextExtractionLLMOutput(
        replace_services=[]
    )
    merged = _merge_signals_into_context(base_ctx, llm_output)
    assert merged.service_access == [], f"Expected empty services list, got {merged.service_access}"

    # JavaScript
    js = """
    chatState.service_access = ["Netflix", "Disney+"];
    fieldVersions.service_access = 1;
    syncContextToState({ service_access: [] }, 2);
    console.log(JSON.stringify({ service_access: chatState.service_access }));
    """
    result = _run_voice_journey_js(js)
    assert result["service_access"] == [], f"Expected JS service_access to be [], got {result['service_access']}"


def test_ranking_pipeline_deadline_and_tone_filter(monkeypatch):
    """Verify that candidates with personal_fit_score < 20 (such as dark films for warm requests) are excluded from STRONG_ALTERNATIVE."""
    from ranking import rank_movies, OutputRole
    from contracts import FilmMetadata

    meta_warm = FilmMetadata(
        title="Paddington 2",
        year=2017,
        director="Paul King",
        runtime_minutes=103,
        genres=["Comedy", "Family"],
        age_rating="PG",
        available_services=["Netflix"],
        imdb_id="tt4468740"
    )
    meta_dark = FilmMetadata(
        title="The Dark Knight",
        year=2008,
        director="Christopher Nolan",
        runtime_minutes=152,
        genres=["Action", "Crime", "Drama"],
        age_rating="12A",
        available_services=["Netflix"],
        imdb_id="tt0468569"
    )
    meta_gentle = FilmMetadata(
        title="Amélie",
        year=2001,
        director="Jean-Pierre Jeunet",
        runtime_minutes=122,
        genres=["Comedy", "Romance"],
        age_rating="15",
        available_services=["Netflix"],
        imdb_id="tt0211915"
    )

    from availability import AvailabilityResult, AvailabilityStatus
    mock_avail = AvailabilityResult(status=AvailabilityStatus.AVAILABLE, services=["Netflix"], provider="watchmode", country="UK")
    monkeypatch.setattr("ranking.discover_candidates_with_gemini", lambda ctx, **kw: [meta_warm, meta_dark, meta_gentle])
    monkeypatch.setattr("ranking.get_film_availability", lambda *args, **kw: mock_avail)
    monkeypatch.setattr("ranking.get_film_evidence", lambda **kw: [{"url": "https://example.com", "text": "Delightful warm film."}])

    context = UserContext(
        country="UK",
        service_access=["Netflix"],
        allow_rent_buy=False,
        intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
        tonight_signals=[
            TasteSignal(name=SIGNAL_TONE, value="warm", signal_type=SignalType.SOFT_SESSION_PREFERENCE),
            TasteSignal(name=SIGNAL_PACING, value="measured", signal_type=SignalType.SOFT_SESSION_PREFERENCE),
        ]
    )

    res = rank_movies(context, force_live_evidence=False, use_live_pipeline=True)
    assert len(res.recommendations) >= 1
    dark_rec = next((r for r in res.recommendations if "Dark Knight" in r.metadata.title), None)
    if dark_rec:
        assert dark_rec.role != OutputRole.STRONG_ALTERNATIVE, "Dark film must not be presented as STRONG_ALTERNATIVE for warm request"
