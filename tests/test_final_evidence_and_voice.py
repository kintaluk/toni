import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from test_voice_search_journey import _run_voice_journey_js
from test_desktop_voice_regressions import SETUP
from src import evidence
import api
from contracts import UserContext


def test_extract_excerpts_survive_missing_full_page_but_thin_content_does_not(monkeypatch, tmp_path):
    monkeypatch.setenv('PARALLEL_API_KEY', 'test')
    monkeypatch.setattr(evidence, 'TRACE_LOG_PATH', tmp_path/'trace.jsonl')
    monkeypatch.setattr(evidence, 'CACHE_PATH', tmp_path/'cache.json')
    urls=['https://example.com/review/one','https://example.com/review/two','https://example.com/review/three']
    client=MagicMock()
    client.search.return_value=SimpleNamespace(search_id='search',session_id='session',results=[SimpleNamespace(url=u) for u in urls])
    excerpt='The performances anchor a thoughtful, funny film, with a deliberately measured pace. '*8
    client.extract.return_value=SimpleNamespace(extract_id='extract',errors=[],results=[
        SimpleNamespace(url=urls[0],title='Review',full_content=None,excerpts=[excerpt]),
        SimpleNamespace(url=urls[1],title='Review',full_content='',excerpts=['Subscribe now']),
        SimpleNamespace(url=urls[2],title='Review',full_content=excerpt+' Full page.',excerpts=['short'])])
    monkeypatch.setattr(evidence,'Parallel',lambda **kwargs:client)
    rows=evidence.get_film_evidence('Example',2024,'Director',force_live=True,timeout=5)
    assert len(rows)==2
    assert rows[0]['content']==excerpt and rows[0]['retrieval_kind']=='extract_excerpts'
    assert rows[1]['retrieval_kind']=='full_content'
    assert 0 < client.extract.call_args.kwargs['timeout'] <= 5


def test_late_canonical_transcript_replaces_partial_and_repeated_turn_is_kept():
    result=_run_voice_journey_js(SETUP+r'''
      const event={type:'turn_complete',turn_id:1,user_text:'Hi TONI.',assistant_reply:reply,
        updated_context:{country:'UK',country_confirmed:true,service_access:['Netflix']}};
      socket.simulateMessage(event); socket.simulateMessage(event);
      socket.simulateMessage({type:'transcript',role:'user',turn_id:1,text:'late fragment'});
      socket.simulateMessage({...event,turn_id:2});
      console.log(JSON.stringify({users:chatState.conversation_history.filter(m=>m.role==='user').map(m=>m.content)}));
    ''')
    assert result['users']==['Hi TONI.','Hi TONI.']


def test_manual_context_update_wins_over_inflight_voice_snapshot(monkeypatch):
    async def run():
        started=asyncio.Event(); release=asyncio.Event(); completed=asyncio.Event()
        messages=[]
        class Socket:
            async def send_json(self,data):
                messages.append(data); completed.set()
        async def delayed(**kwargs):
            previous=kwargs['current_context'].model_copy(deep=True)
            started.set(); await release.wait()
            return previous,False,'llm'
        monkeypatch.setattr(api,'extract_voice_context_async',delayed)
        monkeypatch.setattr(api,'log_conversation_turn',lambda **kwargs:None)
        ctx=UserContext(country='UK',service_access=['Netflix'],intake_depth='a_couple_of_questions')
        pipeline=api.LiveExtractionPipeline(Socket(),ctx,[])
        try:
            pipeline.enqueue_turn(1,'Something funny','Of course.',[])
            await asyncio.wait_for(started.wait(),1)
            updated=ctx.model_copy(update={'service_access':['Sky Go']},deep=True)
            pipeline.update_context(updated)
            release.set(); await asyncio.wait_for(completed.wait(),1)
            assert messages[-1]['updated_context']['service_access']==['Sky Go']
            assert pipeline.session_ctx.service_access==['Sky Go']
        finally:
            await pipeline.shutdown()
    asyncio.run(run())


def test_bare_genre_is_retained_without_turning_negation_positive():
    ctx=UserContext(country='UK',service_access=['Netflix'],intake_depth='a_couple_of_questions')
    updated,_=api._extract_voice_context_fallback('Comedy',ctx)
    assert any(s.name=='preferred_genres' and 'Comedy' in s.value for s in updated.tonight_signals)
    updated,_=api._extract_voice_context_fallback('No horror',ctx)
    assert not any(s.name=='preferred_genres' and 'Horror' in s.value for s in updated.tonight_signals)


def test_channel_edit_updates_the_open_voice_session():
    result=_run_voice_journey_js(SETUP+r'''
      chatState.service_access=['Netflix'];
      toggleService('Sky Go'); await Promise.resolve();
      const message=socket.sentMessages.find(m=>m.type==='context_update');
      console.log(JSON.stringify({services:message?.context.service_access}));
    ''')
    assert result['services']==['Netflix','Sky Go']
