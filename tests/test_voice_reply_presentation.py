"""Keep voice text synchronized with playback and retain the search action."""
import json
import pytest
from test_voice_search_journey import _run_voice_journey_js
from api import _extract_voice_context_fallback, PROVIDER_PRESETS
from contracts import UserContext

SETUP = r'''
await window.toggleSingleBrainVoice();
const socket = mockSockets[mockSockets.length-1];
socket.simulateOpen(); socket.simulateMessage({type:'init_ack',status:'ready'});
const second = Buffer.from(new Int16Array(24000).buffer).toString('base64');
const reply = 'Which country are you in?';
socket.simulateMessage({type:'transcript',role:'user',turn_id:1,text:'Comedy please.'});
socket.simulateMessage({type:'audio',turn_id:1,data:second});
socket.simulateMessage({type:'transcript',role:'assistant',turn_id:1,text:reply});
const record = turnTranscripts.get(currentAudioTurnId);
'''


def test_thinking_indicator_hides_transcript_until_playback():
    result = _run_voice_journey_js(SETUP + r'''
      audioWorkletOrProcessor.onaudioprocess({inputBuffer:{getChannelData:()=>new Float32Array(640)}});
      const before = {thinking:record.bubble.innerHTML.includes('Thinking'),
        leaked:record.bubble.innerHTML.includes(reply),revealed:record.revealed,
        status:document.getElementById('voice-status-text').innerText};
      socket.simulateMessage({type:'speech_complete',turn_id:1,assistant_reply:reply});
      console.log(JSON.stringify({before,after:record.textElement.textContent,
        revealed:record.revealed,scheduled:activeAudioSourceNodes.length}));
    ''')
    assert result['before'] == {'thinking':True, 'leaked':False, 'revealed':False,'status':'Thinking...'}
    assert result['after'] == 'Which country are you in?'
    assert result['revealed'] and result['scheduled'] == 1


def test_text_waits_for_scheduled_audio_clock():
    result = _run_voice_journey_js(SETUP + r'''
      nextAudioPlaybackTime = 2;
      socket.simulateMessage({type:'speech_complete',turn_id:1,assistant_reply:reply});
      const before = record.revealed;
      audioPlaybackContext.currentTime = 2;
      await new Promise(resolve=>setTimeout(resolve,40));
      console.log(JSON.stringify({before,after:record.revealed,text:record.textElement.textContent}));
    ''')
    assert result == {'before':False, 'after':True, 'text':'Which country are you in?'}


def test_suspended_context_does_not_reveal_before_sound_can_start():
    result = _run_voice_journey_js(SETUP + r'''
      audioPlaybackContext.state = 'suspended';
      socket.simulateMessage({type:'speech_complete',turn_id:1,assistant_reply:reply});
      const before = record.revealed;
      audioPlaybackContext.state = 'running';
      await new Promise(resolve=>setTimeout(resolve,40));
      console.log(JSON.stringify({before,after:record.revealed}));
    ''')
    assert result == {'before':False,'after':True}


def test_interrupted_reply_clears_thinking_without_late_text():
    result = _run_voice_journey_js(SETUP + r'''
      nextAudioPlaybackTime = 2;
      socket.simulateMessage({type:'speech_complete',turn_id:1,assistant_reply:reply});
      socket.simulateMessage({type:'interrupted'});
      audioPlaybackContext.currentTime = 3;
      await new Promise(resolve=>setTimeout(resolve,40));
      console.log(JSON.stringify({cancelled:record.cancelled,revealed:record.revealed,
        removed:record.bubble.parentElement===null}));
    ''')
    assert result == {'cancelled':True,'revealed':False,'removed':True}


@pytest.mark.parametrize('utterance', [
    "I'm in the UK and I have access to everything.",
    'I have access to all of them.', 'I subscribe to everything.',
])
def test_everything_access_shows_button(utterance):
    ctx = UserContext(country='UK',service_access=[],intake_depth='a_couple_of_questions')
    ctx,_ = _extract_voice_context_fallback('Comedy please.',ctx)
    ctx,_ = _extract_voice_context_fallback(utterance,ctx)
    assert set(ctx.service_access) == {p['name'] for p in PROVIDER_PRESETS['UK']}
    result = _run_voice_journey_js(SETUP + f'''
      socket.simulateMessage({json.dumps({'type':'turn_complete','turn_id':1,
        'user_text':"I'm in the UK. " + utterance,
        'assistant_reply':'Tap Find what fits whenever you are ready.',
        'updated_context':ctx.model_dump(),'ready_to_recommend':False})});
      console.log(JSON.stringify({{cta:document.getElementById('toni-chat-thread').children.some(c=>c.id==='msg-step-ready')}}));
    ''')
    assert result['cta']


@pytest.mark.parametrize('utterance', [
    "I don't have access to everything.", 'I have no access to everything.',
    'I have everything I need.', 'I want to watch everything.',
])
def test_unrelated_or_negated_everything_does_not_grant_access(utterance):
    ctx = UserContext(country='UK',service_access=['Netflix'],intake_depth='a_couple_of_questions')
    ctx,_ = _extract_voice_context_fallback(utterance,ctx)
    assert ctx.service_access == ['Netflix']


def test_explicit_button_offer_cannot_leave_viewer_without_a_button():
    ctx = UserContext(country='UK',service_access=['Netflix'],intake_depth='a_couple_of_questions')
    result = _run_voice_journey_js(SETUP + f'''
      socket.simulateMessage({json.dumps({'type':'turn_complete','turn_id':1,
        'user_text':"I'm in the UK and I'm open.",
        'assistant_reply':'Tap "Find what fits" whenever you are ready.',
        'updated_context':ctx.model_dump(),'ready_to_recommend':False})});
      const cta = document.getElementById('toni-chat-thread').children.some(c=>c.id==='msg-step-ready');
      console.log(JSON.stringify({{cta,autoSearch:autoRecommendationTimer!==null}}));
    ''')
    assert result == {'cta':True,'autoSearch':False}
