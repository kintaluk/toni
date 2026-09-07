"""Refinements stay on results and year limits survive every candidate source."""
from pathlib import Path
import pytest
from test_voice_search_journey import _run_voice_journey_js


def test_no_results_controls_navigate_to_chat():
    html = (Path(__file__).resolve().parents[1]/'static/index.html').read_text(encoding='utf-8')
    for label in ['Adjust in chat', 'Return to chat', 'Refine in chat', 'onclick="returnToChat()"']:
        assert label not in html
    result = _run_voice_journey_js(r'''
      renderDedicatedResultsPage({recommendations:[]});
      console.log(JSON.stringify({footerHidden:document.getElementById('bottom-chat-bar').classList.contains('hidden'),
        has2015:document.getElementById('results-quick-refine-bar').innerHTML.includes('2015 onwards'),
        has2020:document.getElementById('results-quick-refine-bar').innerHTML.includes('2020 onwards'),view:currentView}));
    ''')
    assert result['footerHidden'] and result['view'] == 'results'
    assert result['has2015'] and result['has2020']


def test_contextual_refinements_preserve_access_genre_and_year():
    result = _run_voice_journey_js(r'''
      chatState.country_confirmed = true;
      chatState.service_access = ['Sky Go']; chatState.preferred_genres = ['Horror'];
      chatState.reference_films = ['The Shining']; chatState.tone = 'intense';
      chatState.max_runtime = 100; setExcludeGenre('Comedy');
      renderDedicatedResultsPage({recommendations:[]});
      const horrorLabel = document.getElementById('results-quick-refine-bar').innerHTML.includes('Less intense');
      await quickRefine('year','2020'); await new Promise(r=>setTimeout(r,450));
      await quickRefine('lighter'); await new Promise(r=>setTimeout(r,450));
      await quickRefine('shorter'); await new Promise(r=>setTimeout(r,450));
      const requests = mockFetchCalls.filter(c=>c.url.includes('/api/recommend'));
      console.log(JSON.stringify({horrorLabel,view:currentView,requests:requests.map(r=>r.body),
        chatCalls:mockFetchCalls.filter(c=>c.url.includes('/api/voice/turn')).length}));
    ''')
    assert result['horrorLabel'] and result['view'] == 'results' and result['chatCalls'] == 0
    assert len(result['requests']) == 3
    for request in result['requests']:
        assert request['min_release_year'] == 2020 and request['service_access'] == ['Sky Go']
        signals = {s['name']:s['value'] for s in request['tonight_signals']}
        assert signals['preferred_genres'] == ['Horror'] and signals['exclude-genre'] == ['Comedy']
    assert {s['name']:s['value'] for s in result['requests'][-1]['tonight_signals']}['max-runtime'] == 85
    assert {s['name']:s['value'] for s in result['requests'][-1]['tonight_signals']}['tone'] == 'eerie'


def test_failed_refinement_keeps_results_and_restores_their_filter():
    result = _run_voice_journey_js(r'''
      chatState.lastResults = {recommendations:[]}; chatState.min_release_year = 2015;
      renderDedicatedResultsPage(chatState.lastResults);
      mockFetchHandler = async()=>{throw new Error('upstream unavailable')};
      await quickRefine('year','2020');
      console.log(JSON.stringify({view:currentView,year:chatState.min_release_year,
        footerHidden:document.getElementById('bottom-chat-bar').classList.contains('hidden')}));
    ''')
    assert result == dict(view='results',year=2015,footerHidden=True)


def test_more_like_stays_on_results_and_any_year_clears_limit():
    result = _run_voice_journey_js(r'''
      chatState.service_access = ['Sky Go']; chatState.min_release_year = 2020;
      await refineMoreLike("Kiki's Delivery Service"); await new Promise(r=>setTimeout(r,450));
      await quickRefine('year',''); await new Promise(r=>setTimeout(r,450));
      const requests = mockFetchCalls.filter(c=>c.url.includes('/api/recommend'));
      console.log(JSON.stringify({view:currentView,last:requests.at(-1).body,
        chatCalls:mockFetchCalls.filter(c=>c.url.includes('/api/voice/turn')).length}));
    ''')
    assert result['view'] == 'results' and result['chatCalls'] == 0
    assert result['last']['min_release_year'] is None
    assert any(s['name']=='reference_films' and s['value']==["Kiki's Delivery Service"] for s in result['last']['tonight_signals'])


@pytest.mark.parametrize('mode', ['live','seed','discovery_failure'])
def test_year_filter_precedes_availability_and_applies_to_refill(monkeypatch, mode):
    import ranking
    from contracts import UserContext, AvailabilityResult, AvailabilityStatus, FilmMetadata
    ctx = UserContext(country='UK',service_access=['Sky Go'],intake_depth='a_couple_of_questions',min_release_year=2020)
    calls = []
    def availability(title, year, *args, **kwargs):
        calls.append((title,year))
        return AvailabilityResult(status=AvailabilityStatus.UNAVAILABLE,provider='test',country='UK',matched_services=[])
    monkeypatch.setattr(ranking,'get_film_availability',availability)
    def discover(*a,**kw):
        if mode == 'discovery_failure': raise TimeoutError('upstream failure')
        return [FilmMetadata(**s['metadata']) for s in ranking.SEED_FILMS]
    monkeypatch.setattr(ranking,'discover_candidates_with_gemini',discover)
    response = ranking.rank_movies(ctx,force_live_evidence=False,use_live_pipeline=mode!='seed')
    assert not response.recommendations
    assert calls and all(year >= 2020 for _,year in calls)
