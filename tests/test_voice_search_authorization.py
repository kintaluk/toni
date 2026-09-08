"""Only confirmation of the current search offer can authorize spoken search."""
import pytest
from test_voice_search_journey import _run_voice_journey_js

SETUP = r'''
await toggleSingleBrainVoice();
const socket = mockSockets[mockSockets.length-1]; socket.simulateOpen();
socket.simulateMessage({type:'init_ack',status:'ready'});
'''


def test_echoed_search_question_and_breath_never_leave_intake():
    result = _run_voice_journey_js(SETUP + r'''
      const echo = 'Which country are you in? Are you ready to see what fits? Find what fits.';
      socket.simulateMessage({type:'transcript',role:'user',turn_id:1,text:echo});
      socket.simulateMessage({type:'turn_complete',turn_id:1,user_text:echo,
        assistant_reply:'Tap Find my results.',ready_to_recommend:true,
        updated_context:{country:'UK',service_access:[],tonight_signals:[]}});
      audioWorkletOrProcessor.onaudioprocess({inputBuffer:{getChannelData:()=>new Float32Array(640).fill(.1)}});
      await new Promise(resolve=>setTimeout(resolve,800));
      console.log(JSON.stringify({view:currentView,voice:voiceActive,handoff:searchHandoffActive,
        requests:mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).length,
        timer:autoRecommendationTimer,button:!document.getElementById('persistent-results-action').classList.contains('hidden')}));
    ''')
    assert result == dict(view='intake',voice=True,handoff=False,requests=0,timer=None,button=False)


@pytest.mark.parametrize('confirmed', [False, True])
def test_failed_handoff_has_visible_action_and_correct_next_step(confirmed):
    result = _run_voice_journey_js(SETUP + f'chatState.country_confirmed = {str(confirmed).lower()};' + r'''
      chatState.service_access = ['Sky Go'];
      isMicAudioInFlight = true;
      const handoff = executeVoiceSearchHandoff('cta_button_click');
      activeHandoffBarrier.reject(new Error('HandoffTimeout'));
      await handoff;
      const button = !document.getElementById('persistent-results-action').classList.contains('hidden');
      const notice = document.getElementById('toni-chat-thread').innerHTML;
      // A visible Review choices button provides recovery without authorizing search.
      if(chatState.country_confirmed) {renderReadyTurn();confirmChoices();}
      await handleReadyCTAClick();
      await new Promise(resolve=>setTimeout(resolve,450));
      console.log(JSON.stringify({button,notice,view:currentView,step:chatState.step,
        requests:mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).length,
        services:chatState.service_access}));
    ''')
    assert result['button'] is confirmed
    assert 'saved' in result['notice']
    assert result['services'] == ['Sky Go']
    assert result['requests'] == (1 if confirmed else 0)
    assert result['view'] == ('results' if confirmed else 'intake')
    if not confirmed:
        assert result['step'] == 2


def test_button_collects_missing_services_without_search():
    result = _run_voice_journey_js(r'''
      chatState.country_confirmed = true; chatState.service_access = [];
      await handleReadyCTAClick();
      console.log(JSON.stringify({view:currentView,step:chatState.step,
        requests:mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).length,
        button:!document.getElementById('persistent-results-action').classList.contains('hidden')}));
    ''')
    assert result == dict(view='intake',step=3,requests=0,button=False)


def test_http_voice_fallback_readiness_cannot_start_search():
    result = _run_voice_journey_js(r'''
      voiceActive = true;
      mockFetchHandler = async(url,opts)=>{
        mockFetchCalls.push({url,opts});
        return {ok:true,json:async()=>({assistant_reply:'Tap Find my results.',
          ready_to_recommend:true,updated_context:{country:'UK',service_access:['Netflix'],tonight_signals:[]}})};
      };
      await handleVoiceUtterance('Find what fits.');
      await new Promise(resolve=>setTimeout(resolve,800));
      console.log(JSON.stringify({requests:mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).length,
        view:currentView,timer:autoRecommendationTimer}));
    ''')
    assert result == dict(requests=0,view='intake',timer=None)


@pytest.mark.parametrize('reply,expected', [('Yes please',1),('Not yet',0),('Yes, but no horror',0),('Shall I search with these choices?',0)])
@pytest.mark.parametrize('offer', ['Shall I search with these choices?', 'Shall I search with these choices then?', 'Would you like me to search now?'])
def test_only_complete_confirmation_of_current_offer_starts_one_visual_search(reply, expected, offer):
    import json
    result = _run_voice_journey_js(SETUP + 'const answer=' + json.dumps(reply) + '; const offer=' + json.dumps(offer) + ';' + r'''
      chatState.country_confirmed=true;
      const ctx={country:'UK',country_confirmed:true,service_access:['Netflix'],tonight_signals:[]};
      socket.simulateMessage({type:'transcript',role:'user',turn_id:1,text:'UK and Netflix'});
      socket.simulateMessage({type:'turn_complete',turn_id:1,user_text:'UK and Netflix',
        assistant_reply:offer,updated_context:ctx});
      socket.simulateMessage({type:'transcript',role:'user',turn_id:2,text:answer});
      const event={type:'turn_complete',turn_id:2,user_text:answer,assistant_reply:'Searching.',updated_context:ctx};
      socket.simulateMessage(event); socket.simulateMessage(event);
      await new Promise(resolve=>setTimeout(resolve,450));
      console.log(JSON.stringify({requests:mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).length,
        voice:voiceActive,view:currentView}));
    ''')
    assert result['requests'] == expected
    assert result['voice'] is (expected == 0)
    assert result['view'] == ('results' if expected else 'intake')


def test_yes_to_an_unrelated_question_or_after_preference_edit_does_not_search():
    result = _run_voice_journey_js(SETUP + r'''
      chatState.country_confirmed=true; chatState.service_access=['Netflix'];
      completedDialogueTurnId=latestDialogueTurnId=1;
      handleVoiceSearchConfirmation('Comedy','Do you like comedy?',1);
      completedDialogueTurnId=latestDialogueTurnId=2;
      const unrelated=handleVoiceSearchConfirmation('Yes','Okay.',2);
      handleVoiceSearchConfirmation('Comedy','Shall I search with these choices?',2);
      toggleExcludedGenre('Horror');
      completedDialogueTurnId=latestDialogueTurnId=3;
      const changed=handleVoiceSearchConfirmation('Yes','Okay.',3);
      console.log(JSON.stringify({unrelated,changed,requests:mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).length}));
    ''')
    assert result == dict(unrelated=False, changed=False, requests=0)
