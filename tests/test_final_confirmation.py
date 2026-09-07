from test_voice_search_journey import _run_voice_journey_js


def test_single_action_requires_confirmation_and_reset_clears_all_preferences():
    result=_run_voice_journey_js(r'''
      restartConversation();
      const initial=!document.getElementById('persistent-results-action').classList.contains('hidden');
      chatState.country_confirmed=true; chatState.service_access=['Sky Go'];
      chatState.preferred_genres=['Horror']; chatState.reference_films=['Alien'];
      chatState.tonight_signals=[{name:'tone',value:'eerie'}];
      pendingIntakePanel='services'; syncReadinessUI();
      const before=!document.getElementById('persistent-results-action').classList.contains('hidden');
      retireIntakePanels(); renderReadyTurn(); confirmChoices();
      const after=!document.getElementById('persistent-results-action').classList.contains('hidden');
      await Promise.all([handleReadyCTAClick(),handleReadyCTAClick()]);
      await new Promise(r=>setTimeout(r,450));
      const calls=mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).length;
      restartConversation();
      console.log(JSON.stringify({initial,before,after,calls,genres:chatState.preferred_genres,
        refs:chatState.reference_films,signals:chatState.tonight_signals,
        resetVisible:!document.getElementById('persistent-results-action').classList.contains('hidden')}));
    ''')
    assert result==dict(initial=False,before=False,after=True,calls=1,genres=[],refs=[],signals=[],resetVisible=False)


def test_first_message_is_extracted_and_cannot_auto_search():
    result=_run_voice_journey_js(r'''
      mockFetchHandler=async(url,opts)=>{
        const body=opts.body?JSON.parse(opts.body):{};
        mockFetchCalls.push({url,body});
        return {ok:true,json:async()=>({assistant_reply:'Ready.',ready_to_recommend:true,
          updated_context:{country:'UK',country_confirmed:true,service_access:['Netflix'],
            tonight_signals:[{name:'preferred_genres',value:['Comedy']}]}})};
      };
      document.getElementById('chat-text-input').value='Comedy in the UK on Netflix, show me';
      handleUserTextInput({preventDefault(){}}); await turnQueue;
      await new Promise(r=>setTimeout(r,700));
      console.log(JSON.stringify({genres:chatState.preferred_genres,
        extraction:mockFetchCalls.filter(c=>c.url.includes('/api/voice/turn')).length,
        search:mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).length,
        confirmation:pendingIntakePanel}));
    ''')
    assert result==dict(genres=['Comedy'],extraction=1,search=0,confirmation='summary')


def test_dropdown_drafts_preserve_access_and_apply_together_from_empty_results():
    result=_run_voice_journey_js(r'''
      chatState.country_confirmed=true; chatState.service_access=['Sky Go'];
      chatState.max_runtime=90; chatState.tone='eerie';
      chatState.lastResults={recommendations:[]};
      lastSuccessfulPreferences=capturePreferences();
      renderDedicatedResultsPage(chatState.lastResults);
      stageRefinement('year',''); stageRefinement('tone','');
      const before=mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).length;
      await applyRefinements(); await new Promise(r=>setTimeout(r,450));
      await quickRefine('runtime'); await new Promise(r=>setTimeout(r,450));
      console.log(JSON.stringify({before,requests:mockFetchCalls.filter(c=>c.url.includes('/api/recommend')).map(c=>c.body)}));
    ''')
    assert result['before']==0 and len(result['requests'])==2
    for request in result['requests']:
        assert request['service_access']==['Sky Go'] and request['min_release_year'] is None
        assert not any(s['name']=='tone' for s in request['tonight_signals'])
    assert not any(s['name']=='max-runtime' for s in result['requests'][-1]['tonight_signals'])


def test_late_extraction_preserves_manual_channels_but_merges_other_signals():
    result=_run_voice_journey_js(r'''
      dialoguePreferenceSnapshots.set(1,editEpoch);
      chatState.service_access=['Netflix']; toggleService('Sky Go');
      syncContextToState({service_access:[],tonight_signals:[{name:'tone',value:'funny'}]},1);
      console.log(JSON.stringify({services:chatState.service_access,tone:chatState.tone}));
    ''')
    assert result==dict(services=['Netflix','Sky Go'],tone='funny')


def test_explicit_empty_services_still_clears_access():
    result=_run_voice_journey_js(r'''
      chatState.service_access=['Netflix']; dialoguePreferenceSnapshots.set(1,editEpoch);
      syncContextToState({service_access:[],tonight_signals:[]},1,'I have no subscriptions now');
      console.log(JSON.stringify({services:chatState.service_access}));
    ''')
    assert result==dict(services=[])
