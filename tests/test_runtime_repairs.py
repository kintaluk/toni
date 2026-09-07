"""Regressions for request budgets, source identity and lossless transcripts."""
import importlib.util
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from runtime_budget import BoundedExecutor, call_until
from build_provenance import source_manifest, verify_manifest
from api import join_transcript_chunks


@pytest.mark.parametrize('chunks,expected', [
    (['I', ' enjoy', ' comedy'], 'I enjoy comedy'),
    (['feel', ' alive'], 'feel alive'),
    (['something', ' less', ' demanding'], 'something less demanding'),
    (['an', ' English', ' film'], 'an English film'),
    (['com', 'fort', 'able', ' and', ' per', 'fectly', ' fine.'], 'comfortable and perfectly fine.'),
    (['Don', "'t", ' add', ' ##', ' symbols', '.'], "Don't add ## symbols."),
])
def test_text_delta_boundaries_match_frontend(chunks, expected):
    assert join_transcript_chunks(chunks) == expected
    spec = importlib.util.spec_from_file_location('journey', Path(__file__).with_name('test_voice_search_journey.py'))
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    result = h._run_voice_journey_js('const chunks='+json.dumps(chunks)+'; console.log(JSON.stringify({text:chunks.reduce((t,c)=>smartAppendChunk(t,c),"")}));')
    assert result['text'] == expected


def test_worker_limit_remains_bounded_after_timeouts():
    pool = BoundedExecutor(max_workers=2)
    release = threading.Event()
    futures = [pool.submit(release.wait) for _ in range(2)]
    try:
        assert all(f is not None for f in futures)
        assert all(pool.submit(lambda: None) is None for _ in range(100))
    finally:
        release.set()
        for future in futures:
            future.result(timeout=1)
        pool._pool.shutdown()


def test_waiting_deadline_does_not_wait_for_slow_worker():
    release = threading.Event()
    start = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            call_until(start + .1, release.wait)
        assert time.monotonic()-start < .5
    finally:
        release.set()


def test_upstream_deadline_keyword_is_forwarded():
    assert call_until(time.monotonic()+1, lambda deadline: deadline, deadline=42) == 42


def test_recorded_live_transcript_preserves_boundaries():
    chunks = ["I enjoy", " comedy.", " I feel", " alive.", " Something", " less",
              " demanding,", " like", " an", " English", " film,", " would", " be",
              " perfectly", " fine."]
    expected = "I enjoy comedy. I feel alive. Something less demanding, like an English film, would be perfectly fine."
    test_text_delta_boundaries_match_frontend(chunks, expected)


def test_source_fingerprint_detects_stale_manifest(tmp_path):
    (tmp_path/'src').mkdir()
    source=tmp_path/'src'/'app.py'
    source.write_text('original',encoding='utf-8')
    manifest=source_manifest(tmp_path)
    (tmp_path/'build_manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    assert verify_manifest(tmp_path)['manifest_verified'] is True
    source.write_text('repaired',encoding='utf-8')
    assert verify_manifest(tmp_path)['manifest_verified'] is False
    assert source_manifest(tmp_path)['source_fingerprint'] != manifest['source_fingerprint']


def test_discovery_sends_supported_timeout_even_at_exact_budget(monkeypatch):
    import ranking
    from contracts import UserContext, IntakeDepth
    fake=Mock()
    fake.models.generate_content.return_value=SimpleNamespace(parsed=SimpleNamespace(candidates=[]))
    monkeypatch.setenv('GEMINI_API_KEY','test')
    monkeypatch.delenv('TONI_MOCK_GEMINI_LIVE',raising=False)
    monkeypatch.setattr(ranking,'get_gemini_client',lambda:fake)
    ctx=UserContext(country='UK',service_access=['Netflix'],intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING)
    ranking.discover_candidates_with_gemini(ctx, deadline=time.monotonic()+10)
    assert fake.models.generate_content.call_count == 1
    assert fake.models.generate_content.call_args.kwargs['config'].http_options.timeout == 10000
