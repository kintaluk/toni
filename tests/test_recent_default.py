"""New sessions must not silently return to old-film defaults."""
from datetime import date
from types import SimpleNamespace
from contracts import UserContext, TasteSignal, SignalType, OutputRole
from ranking import recommendation_order, recent_role_order
from test_voice_search_journey import _run_voice_journey_js


def test_new_session_and_restart_search_recent_without_touching_filter():
    result = _run_voice_journey_js(r'''
      chatState.country_confirmed = true; chatState.service_access = ['Sky Go'];
      const initial = chatState.min_release_year;
      const voiceYear = buildVoiceTurnPayload('Comedy please','voice').current_context.min_release_year;
      renderReadyTurn(); confirmChoices();
      await handleReadyCTAClick(); await new Promise(r=>setTimeout(r,450));
      const first = mockFetchCalls.find(c=>c.url.includes('/api/recommend')).body;
      const selected = document.getElementById('results-quick-refine-bar').innerHTML.includes('Recent ('+initial+' onwards)');
      await quickRefine('year',''); await new Promise(r=>setTimeout(r,450));
      const cleared = chatState.min_release_year;
      restartConversation();
      console.log(JSON.stringify({initial,voiceYear,requestYear:first.min_release_year,selected,cleared,restarted:chatState.min_release_year}));
    ''')
    cutoff = date.today().year - 3
    assert result == dict(initial=cutoff,voiceYear=cutoff,requestYear=cutoff,selected=True,cleared=None,restarted=cutoff)


def candidate(title, year, score, genre='Comedy', stretch=None):
    return SimpleNamespace(metadata=SimpleNamespace(title=title,year=year,genres=[genre]),
                           personal_fit_score=score,stretch_signal=stretch,role=OutputRole.RANKED_ADDITIONAL)


def context(min_year=2023):
    return UserContext(country='UK',service_access=['Sky Go'],intake_depth='a_couple_of_questions',
        min_release_year=min_year,tonight_signals=[TasteSignal(name='preferred_genres',value=['Comedy'],signal_type=SignalType.SOFT_SESSION_PREFERENCE)])


def test_recent_ranking_and_roles_cannot_promote_older_award_favourite():
    films = [candidate('Older award favourite',2023,98,stretch='A stretch'),
             candidate('New comedy',2025,65),candidate('Newest comedy',2026,60),
             candidate('Other genre',2026,95,'Horror'),candidate('Poor fit',2026,5)]
    films.sort(key=lambda r:recommendation_order(r,context()),reverse=True)
    ranked = recent_role_order(films)
    assert [r.metadata.title for r in ranked[:3]] == ['Newest comedy','New comedy','Older award favourite']
    assert ranked[0].role == OutputRole.BEST_FIT and ranked[1].role == OutputRole.STRONG_ALTERNATIVE
    assert ranked[-1].metadata.title == 'Poor fit'
    assert ranked[0].personal_fit_score == 60  # Recency is not a fabricated fit score.


def test_explicit_any_year_can_rank_older_fit_first():
    films = [candidate('Older excellent match',1980,95),candidate('Newer match',2025,60)]
    films.sort(key=lambda r:recommendation_order(r,context(None)),reverse=True)
    assert films[0].metadata.year == 1980
