"""Unrestricted UK discovery and consent, with actual frontend JavaScript replay."""
import asyncio
import json
import pytest
import api
import ranking
import availability
from contracts import UserContext, TasteSignal, SignalType, AvailabilityResult, AvailabilityStatus, VoiceTurnRequest
from test_voice_search_journey import _run_voice_journey_js


REQUEST = 'I am in the UK, want something funny like Ted Lasso, with no restrictions and access to all channels.'


def context(**updates):
    return UserContext(country='UK', service_access=[], intake_depth='a_couple_of_questions', **updates)


def test_uk_ted_lasso_voice_confirmation_searches_once_and_resets():
    response = api.process_voice_turn(VoiceTurnRequest(user_input=REQUEST, current_context=context(), mode='voice'))
    ctx = response.updated_context.model_dump(mode='json')
    assert ctx['min_release_year'] is None
    assert not ctx['allow_rent_buy']
    assert ctx['service_access'] == [p['name'] for p in api.PROVIDER_PRESETS['UK']]
    assert next(s['value'] for s in ctx['tonight_signals'] if s['name'] == 'reference_films') == ['Ted Lasso']
    assert 'no extra-cost rentals, any year' in response.assistant_reply
    result = _run_voice_journey_js('const ctx=' + json.dumps(ctx) + ';const offer=' + json.dumps(response.assistant_reply) + ';' + r'''
      await toggleSingleBrainVoice();
      const socket=mockSockets.at(-1); socket.simulateOpen(); socket.simulateMessage({type:'init_ack',status:'ready'});
      socket.simulateMessage({type:'transcript',role:'user',turn_id:1,text:'UK, funny like Ted Lasso, no restrictions, access to all channels.'});
      socket.simulateMessage({type:'turn_complete',turn_id:1,user_text:'UK, funny like Ted Lasso, no restrictions, access to all channels.',assistant_reply:offer,updated_context:ctx});
      socket.simulateMessage({type:'transcript',role:'user',turn_id:2,text:'Yes, please.'});
      // A mis-extracted yes must not alter the choices the viewer accepted.
      const event={type:'turn_complete',turn_id:2,user_text:'Yes, please.',
        assistant_reply:'Tell me your preferences.',updated_context:{...ctx,service_access:['Netflix'],min_release_year:2023,allow_rent_buy:true,tonight_signals:[]}};
      socket.simulateMessage(event);socket.simulateMessage(event);
      await new Promise(r=>setTimeout(r,450));
      const calls=mockFetchCalls.filter(c=>c.url.includes('/api/recommend'));
      const before={count:calls.length,body:calls[0]?.body,voice:voiceActive,view:currentView};
      restartConversation();
      console.log(JSON.stringify({before,year:chatState.min_release_year,services:chatState.service_access,refs:chatState.reference_films,offer:pendingVoiceSearchOffer,history:chatState.conversation_history}));
    ''')
    assert result['before']['count'] == 1
    assert result['before']['voice'] is False and result['before']['view'] == 'results'
    for field in ('min_release_year', 'allow_rent_buy', 'service_access'):
        assert result['before']['body'][field] == ctx[field]
    assert result['before']['body']['tonight_signals'] == [
        {k:v for k,v in signal.items() if k != 'provenance'} for signal in ctx['tonight_signals']]
    assert {k: result[k] for k in ('year','services','refs','offer','history')} == dict(year=None,services=[],refs=[],offer=None,history=[])


@pytest.mark.parametrize('text,year,rent', [
    ('No restrictions',None,False), ('Any year, include rentals',None,True),
    ('From 2020, included only',2020,False), ('After 2020, rentals are fine',2021,True),
    ('Yes, please.',2023,False),
])
def test_explicit_constraints_and_confirmation_preserve_other_choices(text, year, rent):
    ctx=context(min_release_year=2023)
    ctx.service_access=['Sky Go']
    ctx.tonight_signals=[TasteSignal(name='reference_films',value=['Ted Lasso'],signal_type=SignalType.SOFT_SESSION_PREFERENCE)]
    updated,_=api.extract_voice_context(text,ctx)
    assert updated.min_release_year == year and updated.allow_rent_buy is rent
    assert updated.service_access == ['Sky Go'] and updated.tonight_signals == ctx.tonight_signals
    async_updated,_=asyncio.run(api.extract_voice_context_async(text,ctx))
    assert async_updated == updated


def test_no_restrictions_clears_old_limits_but_keeps_taste():
    ctx=context(min_release_year=2023)
    ctx.tonight_signals=[TasteSignal(name=name,value=value,signal_type=kind) for name,value,kind in [
        ('max-runtime',90,SignalType.HARD_CONSTRAINT),('exclude-genre',['Horror'],SignalType.HARD_CONSTRAINT),
        ('tone','funny',SignalType.SOFT_SESSION_PREFERENCE)]]
    updated,_=api.extract_voice_context('No restrictions',ctx)
    assert updated.min_release_year is None
    assert [(s.name,s.value) for s in updated.tonight_signals] == [('tone','funny')]


def test_text_confirmation_uses_the_same_saved_choices():
    result=_run_voice_journey_js(r'''
      let turn=0;
      mockFetchHandler=async(url,opts)=>{
        mockFetchCalls.push({url,body:JSON.parse(opts.body)});
        if(url.includes('/api/recommend')) return {ok:true,json:async()=>({recommendations:[]})};
        turn++;
        return {ok:true,json:async()=>({assistant_reply:turn===1?'Included access only, any year. Shall I search with these choices?':'Collect preferences.',
          updated_context:{country:'UK',service_access:turn===1?['Sky Go']:[],min_release_year:turn===1?null:2023,tonight_signals:[{name:'tone',value:'funny'}]}})};
      };
      enqueueTextDialogueTurn('UK, Sky Go, funny please');await turnQueue;
      enqueueTextDialogueTurn('Yes, please.');await turnQueue;
      await new Promise(r=>setTimeout(r,450));
      console.log(JSON.stringify({calls:mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).map(c=>c.body)}));
    ''')
    assert len(result['calls']) == 1
    assert result['calls'][0]['service_access'] == ['Sky Go']
    assert result['calls'][0]['min_release_year'] is None


def test_availability_failure_is_not_a_genuine_no_match(monkeypatch):
    film=ranking.FilmMetadata(**ranking.SEED_FILMS[0]['metadata'])
    monkeypatch.setattr(ranking,'discover_candidates_with_gemini',lambda *a,**kw:[film])
    monkeypatch.setattr(ranking,'SEED_FILMS',[])
    def fail(*a,**kw): raise TimeoutError('provider timeout')
    monkeypatch.setattr(ranking,'get_film_availability',fail)
    response=ranking._rank_movies_live(context(),defer_reviews=True)
    assert not response.recommendations
    assert response.search_diagnostics['unverified'] == 1
    assert response.search_diagnostics['unavailable'] == 0
    monkeypatch.setattr(ranking,'get_film_availability',lambda *a,**kw:AvailabilityResult(status=AvailabilityStatus.UNAVAILABLE,provider='TMDB',country='UK',matched_services=[]))
    response=ranking._rank_movies_live(context(),defer_reviews=True)
    assert response.search_diagnostics['unverified'] == 0
    assert response.search_diagnostics['unavailable'] == 1


def test_free_tmdb_channels_are_included(monkeypatch):
    monkeypatch.setenv('TONI_USE_MOCK_AVAILABILITY','false')
    monkeypatch.setattr(availability,'_watchmode_api_key',lambda:None)
    monkeypatch.setattr(availability,'_tmdb_api_key',lambda:'test')
    monkeypatch.setattr(availability,'tmdb_search',lambda *a,**kw:1)
    monkeypatch.setattr(availability,'tmdb_get_watch_providers',lambda *a,**kw:{'GB':{'free':[{'provider_name':'BBC iPlayer'}]}})
    ctx=context();ctx.service_access=['BBC iPlayer']
    result=availability.get_film_availability('A film',2000,ctx)
    assert result.status == AvailabilityStatus.AVAILABLE and result.matched_services == ['BBC iPlayer']


def test_yes_arrives_before_offer_context_commit():
    result=_run_voice_journey_js(r'''
      await toggleSingleBrainVoice();
      const socket=mockSockets.at(-1);socket.simulateOpen();socket.simulateMessage({type:'init_ack',status:'ready'});
      const ctx={country:'UK',service_access:['Sky Go'],min_release_year:null,tonight_signals:[{name:'tone',value:'funny'}]};
      socket.simulateMessage({type:'transcript',role:'user',turn_id:1,text:'UK, Sky Go, funny.'});
      socket.simulateMessage({type:'transcript',role:'assistant',turn_id:1,text:'Shall I search with these choices?'});
      socket.simulateMessage({type:'transcript',role:'user',turn_id:2,text:'Yes, please.'});
      socket.simulateMessage({type:'turn_complete',turn_id:1,user_text:'UK, Sky Go, funny.',assistant_reply:'Shall I search with these choices?',updated_context:ctx});
      socket.simulateMessage({type:'turn_complete',turn_id:2,user_text:'Yes, please.',assistant_reply:'Tell me more.',updated_context:ctx});
      await new Promise(r=>setTimeout(r,450));
      console.log(JSON.stringify({requests:mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).length,view:currentView}));
    ''')
    assert result == dict(requests=1,view='results')


def test_voice_offer_can_be_confirmed_in_text_after_muting():
    result=_run_voice_journey_js(r'''
      await toggleSingleBrainVoice();
      chatState.country_confirmed=true;chatState.service_access=['Sky Go'];
      latestDialogueTurnId=completedDialogueTurnId=1;
      handleVoiceSearchConfirmation('Funny','Shall I search with these choices?',1);
      await toggleSingleBrainVoice();
      latestDialogueTurnId=completedDialogueTurnId=2;
      handleVoiceSearchConfirmation('Yes, please.','Searching.',2);
      await new Promise(r=>setTimeout(r,450));
      console.log(JSON.stringify({requests:mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).length}));
    ''')
    assert result['requests'] == 1


@pytest.mark.parametrize('action,value,field,expected', [('year','','min_release_year',None),('rentals','','allow_rent_buy',True)])
def test_empty_results_adjustments_retain_other_preferences(action,value,field,expected):
    result=_run_voice_journey_js('const action='+json.dumps(action)+';const value='+json.dumps(value)+';' + r'''
      chatState.country_confirmed=true;chatState.service_access=['Sky Go'];chatState.min_release_year=2023;
      chatState.reference_films=['Ted Lasso'];chatState.tone='funny';chatState.max_runtime=120;
      chatState.lastResults={recommendations:[],search_diagnostics:{year_excluded:4,unavailable:3}};
      lastSuccessfulPreferences=capturePreferences();renderDedicatedResultsPage(chatState.lastResults);
      const html=document.getElementById('watchcards-container').innerHTML;
      await quickRefine(action,value);await new Promise(r=>setTimeout(r,450));
      console.log(JSON.stringify({html,body:mockFetchCalls.find(c=>c.url.includes('/api/recommend'))?.body}));
    ''')
    assert 'Try any year; keep other choices' in result['html']
    assert result['body'][field] == expected
    assert result['body']['service_access'] == ['Sky Go']
    signals={s['name']:s['value'] for s in result['body']['tonight_signals']}
    assert signals == {'tone':'funny','max-runtime':120,'reference_films':['Ted Lasso']}


def test_failed_checks_offer_retry_instead_of_relaxing_preferences():
    result=_run_voice_journey_js(r'''
      chatState.min_release_year=2023;
      renderDedicatedResultsPage({recommendations:[],search_diagnostics:{unverified:2,year_excluded:4,unavailable:3}});
      console.log(JSON.stringify({html:document.getElementById('watchcards-container').innerHTML}));
    ''')
    assert 'Search checks could not be completed' in result['html']
    assert 'Retry saved choices' in result['html']
    assert 'Try any year; keep other choices' not in result['html']
