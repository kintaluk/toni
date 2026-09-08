import asyncio
import pytest
import review_updates as updates
import ranking
from contracts import FilmMetadata, FilmProfile, EvidenceState, UserContext, AvailabilityResult, AvailabilityStatus
from test_voice_search_journey import _run_voice_journey_js


FILM = FilmMetadata(title="Blink Twice", year=2024, director="Zoë Kravitz",
                    runtime_minutes=102, age_rating="R", genres=["Thriller"])
REVIEW = {"url":"https://www.rogerebert.com/reviews/blink-twice-film-review-2024",
          "content":"Substantive review. " * 40}
PROFILE = FilmProfile(story_and_writing=3, pacing_and_structure=3, performances=4,
                      craft_and_execution=4, accessibility_and_demandingness=3,
                      tone_and_emotional_character=["tense"])


@pytest.fixture(autouse=True)
def isolate_review_client(monkeypatch):
    monkeypatch.setattr(updates, "get_review_client", lambda: object())


def collect():
    async def run():
        return [row async for row in updates.stream_review_updates([FILM])]
    return asyncio.run(run())


def test_broadens_search_after_failure_then_streams_success(monkeypatch):
    calls = []
    def evidence(**kw):
        calls.append(kw)
        return [REVIEW] if kw["expanded"] else []
    monkeypatch.setattr(updates, "get_film_evidence", evidence)
    monkeypatch.setattr(updates, "generate_film_profile", lambda **kw: (PROFILE, EvidenceState.SPARSE_EVIDENCE, "One critic found tense performances."))
    rows = collect()
    assert [r["review_status"] for r in rows] == ["searching_more", "complete"]
    assert calls[0]["force_live"] is False and calls[1]["expanded"] is True
    assert rows[-1]["evidence_sources"] == [REVIEW["url"]]
    assert all(r["title"] == FILM.title and r["index"] == 0 for r in rows)


def test_synthesis_failure_preserves_links_and_does_not_claim_sparse_coverage(monkeypatch):
    second = dict(REVIEW, url="https://www.theguardian.com/film/review")
    monkeypatch.setattr(updates, "get_film_evidence", lambda **kw: [REVIEW, second])
    def fail(**kw):
        raise TimeoutError("Provider timed out")
    monkeypatch.setattr(updates, "generate_film_profile", fail)
    rows = collect()
    assert [r["review_status"] for r in rows] == ["searching_more", "unavailable"]
    assert rows[-1]["review_failure"] == "synthesis"
    assert rows[-1]["evidence_sources"] == [REVIEW["url"], second["url"]]
    assert "profile" not in rows[-1] and "evidence_state" not in rows[-1]


def test_failed_retrieval_never_attempts_synthesis(monkeypatch):
    monkeypatch.setattr(updates, "get_film_evidence", lambda **kw: [])
    def unexpected(**kw):
        pytest.fail("Cannot synthesize criticism without reviews")
    monkeypatch.setattr(updates, "generate_film_profile", unexpected)
    rows = collect()
    assert rows[-1]["review_status"] == "unavailable"
    assert rows[-1]["review_failure"] == "retrieval"


def test_seven_films_share_one_client_setup_and_keep_full_synthesis_budget(monkeypatch):
    setups = []
    shared = object()
    def create_client():
        setups.append(True)
        return shared
    monkeypatch.setattr(updates, "get_review_client", create_client)
    second = dict(REVIEW, url="https://www.theguardian.com/film/review")
    monkeypatch.setattr(updates, "get_film_evidence", lambda **kw: [REVIEW, second])
    def profile(**kw):
        assert kw['client'] is shared
        assert kw['deadline'] - updates.time.monotonic() >= 10
        return PROFILE, EvidenceState.SPARSE_EVIDENCE, "Review summary."
    monkeypatch.setattr(updates, "generate_film_profile", profile)
    async def run():
        films = [FILM.model_copy(update={'title':f'Film {i}'}) for i in range(7)]
        return [row async for row in updates.stream_review_updates(films)]
    rows = asyncio.run(run())
    assert len(setups) == 1
    assert len(rows) == 7 and all(row['review_status'] == 'complete' for row in rows)


def test_shortlist_phase_never_calls_evidence_or_synthesis(monkeypatch):
    films = [FILM.model_copy(update={"title":f"Film {i}"}) for i in range(5)]
    monkeypatch.setattr(ranking, "discover_candidates_with_gemini", lambda *a, **kw: films)
    monkeypatch.setattr(ranking, "get_film_availability", lambda *a, **kw: AvailabilityResult(
        status=AvailabilityStatus.AVAILABLE, provider="test", matched_services=["Netflix"], country="UK"))
    def unexpected(*a, **kw):
        pytest.fail("The shortlist must not wait for reviews")
    monkeypatch.setattr(ranking, "get_film_evidence", unexpected)
    monkeypatch.setattr(ranking, "generate_film_profile", unexpected)
    monkeypatch.setattr(ranking, "get_film_poster_url", lambda *a: None)
    monkeypatch.setattr(ranking, "get_film_trailer_url", lambda *a: None)
    ctx = UserContext(country="UK", service_access=["Netflix"], intake_depth="just_give_me_something")
    result = ranking.rank_movies(ctx, use_live_pipeline=True, defer_reviews=True)
    assert len(result.recommendations) == 5
    assert all(r.review_status == "pending" and not r.evidence_sources and not r.stretch_signal for r in result.recommendations)


def test_review_updates_cannot_rerank_or_replace_films_or_mutate_a_new_search():
    result = _run_voice_journey_js(r'''
      const rec={metadata:{title:'Film',year:2024},role:'best_fit',review_status:'pending',evidence_sources:[]};
      const data={recommendations:[rec]}; chatState.lastResults=data; switchToView('results');
      const id=recommendationRequestId, gen=sessionGeneration;
      applyReviewUpdate(data,{index:0,title:'Wrong film',year:2024,review_status:'unavailable'},id,gen);
      const wrong=rec.review_status;
      applyReviewUpdate(data,{index:0,title:'Film',year:2024,review_status:'searching_more',metadata:{title:'Bad'},role:'worth_a_stretch'},id,gen);
      const valid=rec.review_status;
      recommendationRequestId++;
      applyReviewUpdate(data,{index:0,title:'Film',year:2024,review_status:'unavailable'},id,gen);
      console.log(JSON.stringify({wrong,valid,last:rec.review_status,title:rec.metadata.title,role:rec.role}));
    ''')
    assert result == dict(wrong="pending", valid="searching_more", last="searching_more", title="Film", role="best_fit")


def test_ndjson_stream_updates_cards_and_marks_incomplete_results_unavailable():
    result = _run_voice_journey_js(r'''
      const rec={metadata:{title:'Film',year:2024},role:'best_fit',review_status:'pending',evidence_sources:[]};
      const data={recommendations:[rec]}; chatState.lastResults=data; switchToView('results');
      const wire=JSON.stringify({index:0,title:'Film',year:2024,review_status:'searching_more'})+'\n';
      const chunks=[wire.slice(0,14),wire.slice(14)];
      globalThis.fetch=async()=>({ok:true,body:{getReader:()=>({
        read:async()=>chunks.length ? {value:new TextEncoder().encode(chunks.shift()),done:false} : {done:true},
        releaseLock(){}
      })}});
      await enrichDisplayedReviews(data,recommendationRequestId,sessionGeneration);
      console.log(JSON.stringify({status:rec.review_status,results:currentView,title:rec.metadata.title}));
    ''')
    assert result == dict(status="unavailable", results="results", title="Film")
