"""Regressions for the viewer's actual wording and the persistent results exit."""
import json
import pytest
from api import _extract_voice_context_fallback, _apply_explicit_service_access, PROVIDER_PRESETS
from contracts import UserContext
from test_voice_search_journey import _run_voice_journey_js
from src.availability import normalize_service_name


@pytest.mark.parametrize('utterance', [
    "I have I'm watching from the UK. I have all of them.",
    "I've got all of them.", "I have them all.",
])
def test_possessive_all_services(utterance):
    ctx = UserContext(country='UK', service_access=[], intake_depth='a_couple_of_questions')
    ctx = _apply_explicit_service_access(ctx, utterance)
    assert set(ctx.service_access) == {p['name'] for p in PROVIDER_PRESETS['UK']}
    assert {'Sky Go', 'NOW Cinema'} <= set(ctx.service_access)


@pytest.mark.parametrize('utterance', [
    "I don't have all of them.", "I haven't got all of them.",
    "I want to watch all of them.", "I have seen all of them.",
])
def test_no_access_from_negative_or_unrelated_pronouns(utterance):
    ctx = UserContext(country='UK', service_access=['Netflix'], intake_depth='a_couple_of_questions')
    assert _apply_explicit_service_access(ctx, utterance).service_access == ['Netflix']


def test_exact_screenshot_words_reach_visible_button_and_results():
    ctx = UserContext(country='UK', service_access=[], intake_depth='a_couple_of_questions')
    events = []
    for i, text in enumerate([
        'Hey Tony. How you doing?', 'Yeah. She was. I want some comedy.',
        "I have I'm watching from the UK. I have all of them.",
    ], 1):
        ctx, _ = _extract_voice_context_fallback(text, ctx)
        events.append({'type':'turn_complete','turn_id':i,'user_text':text,
                       'assistant_reply':'Any runtime limits?',
                       'updated_context':ctx.model_dump(),'ready_to_recommend':False})
    assert any(s.name == 'preferred_genres' and 'Comedy' in s.value for s in ctx.tonight_signals)
    result = _run_voice_journey_js(r'''
      await toggleSingleBrainVoice();
      const socket = mockSockets[mockSockets.length-1]; socket.simulateOpen();
      socket.simulateMessage({type:'init_ack',status:'ready'});
    ''' + f'for(const event of {json.dumps(events)}) socket.simulateMessage(event);' + r'''
      renderReadyTurn(); confirmChoices();
      const visible = !document.getElementById('persistent-results-action').classList.contains('hidden');
      if (!visible) throw new Error('Viewer cannot click a hidden results action');
      const before = mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).length;
      await handleReadyCTAClick();
      await new Promise(resolve=>setTimeout(resolve,450));
      const requests = mockFetchCalls.filter(c=>c.url.includes('/api/recommend'));
      console.log(JSON.stringify({visible,before,count:requests.length,
        payload:requests[0]?.body,view:currentView,
        cards:document.getElementById('watchcards-container').children.length}));
    ''')
    assert result['visible'] and result['before'] == 0
    assert result['count'] == 1 and result['view'] == 'results' and result['cards'] > 0
    assert {'Sky Go', 'NOW Cinema'} <= set(result['payload']['service_access'])


def test_persistent_action_does_not_depend_on_model_offer_and_resets():
    result = _run_voice_journey_js(r'''
      const visible = ()=>!document.getElementById('persistent-results-action').classList.contains('hidden');
      syncReadinessUI(); const initial = visible();
      chatState.country_confirmed = true; chatState.service_access = ['Sky Go'];
      syncReadinessUI(); const broad = visible();
      switchToView('results'); const results = visible();
      switchToView('intake'); const returned = visible();
      chatState.service_access = []; syncReadinessUI(); const cleared = visible();
      chatState.service_access = ['Sky Go']; syncReadinessUI();
      restartConversation(); const restarted = visible();
      console.log(JSON.stringify({initial,broad,results,returned,cleared,restarted}));
    ''')
    assert result == dict(initial=False,broad=False,results=False,returned=False,cleared=False,restarted=False)


def test_sky_and_now_parse_and_match_upstream_names_without_store():
    ctx = UserContext(country='UK', service_access=[], intake_depth='a_couple_of_questions')
    ctx,_ = _extract_voice_context_fallback('I have Sky and NOW Cinema.', ctx)
    assert {'Sky Go', 'NOW Cinema'} <= set(ctx.service_access)
    assert normalize_service_name('Sky') == normalize_service_name('Sky Go')
    assert normalize_service_name('NOW Cinema') == normalize_service_name('Now TV Cinema')
    assert normalize_service_name('Sky Store') != normalize_service_name('Sky Go')
    ctx,_ = _extract_voice_context_fallback('Remove Sky.', ctx)
    assert 'Sky Go' not in ctx.service_access and 'NOW Cinema' in ctx.service_access
    ctx,_ = _extract_voice_context_fallback('I have Sky Store.', ctx)
    assert 'Sky Go' not in ctx.service_access


@pytest.mark.parametrize('selected,upstream', [('Sky', 'Sky Go'), ('NOW Cinema', 'Now TV Cinema')])
def test_live_availability_routes_match_selected_uk_service(monkeypatch, selected, upstream):
    import src.availability as availability
    monkeypatch.setattr(availability, '_watchmode_api_key', lambda: None)
    monkeypatch.setattr(availability, '_tmdb_api_key', lambda: 'test')
    monkeypatch.setattr(availability, 'tmdb_search', lambda *a, **kw: 999999)
    monkeypatch.setattr(availability, 'tmdb_get_watch_providers', lambda *a, **kw: {
        'GB': {'flatrate':[{'provider_name':upstream}], 'rent':[{'provider_name':'Sky Store'}]}})
    ctx = availability.UserContext(country='UK', service_access=[selected],
                                   allow_rent_buy=False, intake_depth='a_couple_of_questions')
    result = availability.get_film_availability('UK provider regression fixture',2026,ctx)
    assert result.status.value == 'available'
    assert result.matched_services == [upstream]
