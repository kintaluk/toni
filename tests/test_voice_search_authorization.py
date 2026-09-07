"""Voice echo/readiness cannot authorize search, and recovery always has an exit."""
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
      if(button) throw new Error('Search must wait for confirmation');
      if(chatState.country_confirmed) {renderReadyTurn();confirmChoices();}
      await handleReadyCTAClick();
      await new Promise(resolve=>setTimeout(resolve,450));
      console.log(JSON.stringify({button,notice,view:currentView,step:chatState.step,
        requests:mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).length,
        services:chatState.service_access}));
    ''')
    assert result['button'] is False
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
