"""Desktop-speaker intake regressions from the reported four-turn journey."""
import sys
import json
import re
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from test_voice_search_journey import _run_voice_journey_js
from api import _extract_voice_context_fallback, PROVIDER_PRESETS
from contracts import UserContext


SETUP = r'''
await window.toggleSingleBrainVoice();
const socket = mockSockets[mockSockets.length - 1];
socket.simulateOpen();
socket.simulateMessage({type:'init_ack',status:'ready'});
const playbackContext = audioPlaybackContext;
const second = Buffer.from(new Int16Array(24000).buffer).toString('base64');
const reply = "Hello there. I'm ready to help you settle in for the night; what kind of mood are you leaning towards, and where are you watching so I can check availability?";
socket.simulateMessage({type:'transcript',role:'user',turn_id:1,text:'Hi Tony.'});
socket.simulateMessage({type:'audio',turn_id:1,data:second});
socket.simulateMessage({type:'speech_complete',turn_id:1,assistant_reply:reply});
const speechNode = activeAudioSourceNodes[0];
'''


def test_single_loud_mic_frame_does_not_cancel_speech():
    result = _run_voice_journey_js(SETUP + r'''
      const frame = new Float32Array(128).fill(0.1);
      audioWorkletOrProcessor.onaudioprocess({inputBuffer:{getChannelData:()=>frame}});
      console.log(JSON.stringify({stopped:speechNode.isStopped,
        interruptSent:socket.sentMessages.some(m=>m.type==='interrupt')}));
    ''')
    assert result == {'stopped': False, 'interruptSent': False}


def test_late_input_transcript_does_not_cancel_its_own_reply():
    result = _run_voice_journey_js(SETUP + r'''
      socket.simulateMessage({type:'transcript',role:'user',turn_id:1,text:' '});
      console.log(JSON.stringify({stopped:speechNode.isStopped,closed:playbackContext.isClosed}));
    ''')
    assert result == {'stopped': False, 'closed': False}


def test_new_user_turn_stops_speech_without_closing_unlocked_context():
    result = _run_voice_journey_js(SETUP + r'''
      socket.simulateMessage({type:'transcript',role:'user',turn_id:2,text:'A comedy please.'});
      console.log(JSON.stringify({stopped:speechNode.isStopped,closed:playbackContext.isClosed}));
    ''')
    assert result == {'stopped': True, 'closed': False}


def test_every_platform_expands_to_supported_market_services():
    ctx = UserContext(country='UK', service_access=[], intake_depth='a_couple_of_questions')
    ctx, _ = _extract_voice_context_fallback(
        "Something a bit silly. I'm from the UK and I've got access to every platform.", ctx)
    assert set(ctx.service_access) == {p['name'] for p in PROVIDER_PRESETS['UK']}


def test_negative_all_platforms_does_not_grant_access():
    ctx = UserContext(country='UK', service_access=['Netflix'], intake_depth='a_couple_of_questions')
    ctx, _ = _extract_voice_context_fallback("I don't have access to every platform.", ctx)
    assert ctx.service_access == ['Netflix']


def test_reported_conversation_displays_cta_without_automatic_search():
    ctx = UserContext(country='UK', service_access=[], intake_depth='a_couple_of_questions')
    # The structured extractor has retained the viewer's comedy preference.
    from contracts import TasteSignal, SignalType
    ctx.tonight_signals = [TasteSignal(name='preferred_genres', value=['comedy'],
                                     signal_type=SignalType.SOFT_SESSION_PREFERENCE)]
    user = "Something a bit silly. I'm from the UK and I've got access to every platform."
    ctx, _ = _extract_voice_context_fallback(user, ctx)
    events = json.dumps([
        {'type':'turn_complete', 'turn_id':2, 'user_text':user,
         'assistant_reply':"Perfect, sounds like fun! One last thing, any runtimes you want to stick to, or are you open? Then I can find what fits.",
         'updated_context':ctx.model_dump(), 'ready_to_recommend':False},
        {'type':'turn_complete', 'turn_id':3, 'user_text':"I'm open.",
         'assistant_reply':"Alright, I'll find what fits.",
         'updated_context':ctx.model_dump(), 'ready_to_recommend':False},
    ])
    result = _run_voice_journey_js(SETUP + f'''
      for (const event of {events}) socket.simulateMessage(event);
      const thread = document.getElementById('toni-chat-thread');
      console.log(JSON.stringify({{cta:thread.children.some(c=>c.id==='msg-step-ready'),
        access:chatState.service_access, autoSearch:autoRecommendationTimer!==null}}));
    ''')
    assert result['cta'] is True
    assert result['autoSearch'] is False
    assert set(result['access']) == {p['name'] for p in PROVIDER_PRESETS['UK']}


def test_microphone_continues_streaming_during_playback_and_confirmed_interrupt_stops_it():
    result = _run_voice_journey_js(SETUP + r'''
      const frame = new Float32Array(640).fill(0.01);
      audioWorkletOrProcessor.onaudioprocess({inputBuffer:{getChannelData:()=>frame}});
      const sent = socket.sentMessages.some(m=>m.type==='audio');
      const stoppedBeforeConfirmation = speechNode.isStopped;
      socket.simulateMessage({type:'interrupted'});
      console.log(JSON.stringify({sent,stoppedBeforeConfirmation,
        stoppedAfterConfirmation:speechNode.isStopped,closed:playbackContext.isClosed}));
    ''')
    assert result == {'sent':True, 'stoppedBeforeConfirmation':False,
                      'stoppedAfterConfirmation':True, 'closed':False}


def test_native_worklet_preserves_samples_in_40ms_frames():
    html = (Path(__file__).resolve().parents[1]/'static/index.html').read_text(encoding='utf-8')
    code = re.search(r'const workletCode = `(.*?)`;', html, re.S).group(1)
    script = r'''
      const sampleRate = 48000;
      const output = [];
      class AudioWorkletProcessor { constructor(){this.port={postMessage:a=>output.push([...a])}} }
      let Processor;
      function registerProcessor(name, cls) {Processor=cls}
    ''' + code + r'''
      const processor = new Processor();
      for(let n=0;n<30;n++) processor.process([[Float32Array.from({length:128},(_,i)=>n*128+i)]]);
      console.log(JSON.stringify({lengths:output.map(a=>a.length),samples:output.flat()}));
    '''
    result = json.loads(subprocess.check_output(['node','-e',script], text=True))
    assert result['lengths'] == [1920,1920]
    assert result['samples'] == list(range(3840))


def test_empty_interrupted_completion_cannot_expire_a_later_reply():
    result = _run_voice_journey_js(SETUP + r'''
      socket.simulateMessage({type:'interrupted'});
      socket.simulateMessage({type:'speech_complete',turn_id:2,assistant_reply:''});
      const hasUnownedTimer = pendingTranscriptTimer!==null;
      socket.simulateMessage({type:'audio',turn_id:3,data:second});
      socket.simulateMessage({type:'speech_complete',turn_id:3,assistant_reply:'Any runtime limits?'});
      console.log(JSON.stringify({hasUnownedTimer,secondsScheduled:activeAudioSourceNodes.reduce((s,n)=>s+n.buffer.duration,0)}));
    ''')
    assert result == {'hasUnownedTimer':False,'secondsScheduled':1}
