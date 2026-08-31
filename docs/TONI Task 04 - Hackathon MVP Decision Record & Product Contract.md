TONI Task 04 - Hackathon MVP Decision Record & Product Contract

Status: PASS

Purpose: Canonical product contract for the hackathon MVP. This document records the decisions made while cutting the ideal TONI experience into a buildable hackathon product. It is intended to be detailed enough that a designer, developer or agent can answer product questions without inventing new policy.

1. Product definition

TONI is a returning personal viewing guide that understands what a user wants tonight, uses what it already knows about their taste where available, researches films live, checks what they can actually watch, reasons across evidence and context, and gives a decisive shortlist with clear reasons.

The core promise remains: Personal fit + less effort.

For the hackathon, TONI is film-first. It is not a general entertainment assistant, review aggregator, streaming service, listings product or generic chatbot. It complements the services people already use.

The MVP must prove the complete reasoning loop:

understand the user -> gather live evidence -> build Film Profiles -> apply context and hard constraints -> verify availability -> rank -> recommend -> refine -> learn useful persistent signals where appropriate.

2. Audience contract

Primary audience: film-aware but time-poor viewers. They have meaningful taste, but do not want to research every viewing decision.

Primary need: Give me recommendations that actually fit my taste, without making me do all the work.

Secondary audience: choice-overloaded mainstream streamers. They want a simple recommendation quickly, with depth available rather than forced.

Tertiary audience: film enthusiasts and cinephiles. They are more likely to inspect evidence, critical disagreement, deeper reasoning and more adventurous discovery.

The MVP must serve all three without creating separate products. The default experience should optimise for primary and secondary users. Tertiary depth should be available on demand.

3. Experience principle

TONI is decisive first and refinement second.

The user should feel that TONI does the homework, gives a clear steer, explains why when needed, and leaves the final decision with them.

The product should not make the user configure a recommendation engine before receiving value. It should infer where safe, ask only what matters, and make correction easy.

4. Entry and conversational intake

The MVP uses a conversational hybrid rather than a form-first onboarding flow.

Natural-language conversation is used for mood, taste and tonight context. Structured controls are used where selection is materially faster or clearer, particularly country, service access and rent/buy eligibility.

The interface must not look like an empty generic chatbot. Chat is an input and refinement mechanism, not the whole product. Results should be presented as proper recommendation cards with editorial hierarchy.

5. User-controlled intake depth

At entry, TONI offers a lightweight choice that reflects how much time or effort the user wants to spend:

Just give me something

A couple of questions is fine

Get to know what I want

The choice controls intake length only. It does not reduce the quality, structure or richness of the result.

A user choosing the fastest mode still receives the same quality of shortlist, availability checking and reasoning. They simply contribute less information before TONI acts.

The user can explicitly change pace during the conversation, for example by asking TONI to speed up or ask more. TONI should not silently exceed the chosen conversational budget.

6. Fast-mode rule

Just give me something has a hard conversational budget.

TONI should infer as much as possible from the user's initial request. If the recommendation would otherwise be too weak or ambiguous, TONI may ask one genuinely essential clarification. After that, it must act.

Fast mode must not quietly turn into normal or deep intake because TONI could theoretically ask more questions.

More questions must earn their place.

7. Tonight context

TONI should be able to interpret natural language for the factors that matter to the recommendation, including where relevant:

mood

energy

wanted tone

runtime or time available

genre

pacing appetite

appetite for something demanding

specific exclusions or dislikes

recent likes or dislikes

something the user wants tonight's choice to feel like

The user does not need to answer every category. TONI should extract whatever is present and ask only for missing information that is likely to materially improve the shortlist.

8. Taste anchor

A taste anchor is important but adaptive rather than mechanically mandatory.

Useful anchors include:

a film the user loved recently

a film they disliked

something they want tonight's film to feel like

another strong example of what they mean

In Just give me something, TONI should not require an anchor if the initial request already provides enough signal. It may use its one essential clarification to request one only when it materially improves recommendation quality.

In medium and deeper intake modes, TONI should actively seek or derive at least one useful anchor when appropriate.

The anchor should be used for preference extraction, not simple title similarity. TONI should reason about which qualities of the anchor matter, such as tone, pacing, performances, story, craft or demandingness. If the intended quality is genuinely ambiguous, it can ask why the anchor matters.

9. Persistent taste versus tonight context

TONI must keep enduring preference separate from temporary context.

Examples:

"I hate jump-scare horror" can support a durable preference.

"Nothing heavy tonight" is session context and must not become a permanent dislike of serious films.

"I need something under two hours tonight" is a hard constraint for the current session unless the user clearly expresses it as a general preference.

The data model and reasoning layer must preserve this distinction. A temporary request must not silently rewrite the user's long-term taste profile.

10. Country identification and confirmation

TONI may identify a likely country automatically from available browser or location context, but it must confirm it before using country as part of availability eligibility.

Example interaction:

Looks like you're in the UK. Is that right?

Yes / Change

Hackathon support is limited to the United Kingdom and United States.

If the user is outside those markets, TONI must not silently map them to UK or US availability. It should state that the hackathon version currently supports the UK and US.

11. Service access UX

After country confirmation, TONI asks which services the user can access.

The service list must be country-specific and should include relevant free broadcaster/catch-up services as well as paid services.

No service is preselected by default.

This applies even to services that are free at the point of use or widely available. Country presence, popularity or zero marginal price does not prove that the user can or chooses to access that service. BBC iPlayer is a clear UK example because legal use depends on a TV Licence.

The UX should make confirmation extremely easy: large, obvious one-tap selected/unselected controls rather than typing service names or completing a subscription questionnaire.

The language is access, not ownership or payment. A user may have access through a household, bundle, telecoms package, shared account or other legitimate route.

12. Rent and buy preference

TONI separately asks whether extra-cost rental or purchase should count as available.

Example:

Include films I can rent or buy?

Yes / No

If no, only films available through the user's selected included-access services can qualify.

If yes, verified rental or purchase availability can also qualify.

This is a hard availability preference, not a minor ranking preference.

13. Availability policy

Availability is a hard eligibility constraint.

A candidate film can only become a TONI recommendation when availability is verified in the user's supported country through at least one service or transaction route the user has chosen to include.

If there is no qualifying availability match, the title is ineligible.

If reliable availability cannot be established, TONI must not guess. Unverified availability also fails eligibility.

Approved unverified wording:

Couldn't find reliable availability information for this title.

The availability requirement applies to every recommendation exposed to the user, including the additional recommendations behind Show my full recommendations. A title cannot bypass the rule simply because it is not in the initial Top 3.

14. Live availability scope

The hackathon uses live, country-specific availability data for UK and US.

The specific provider is an implementation choice as long as it can support the product contract: country-specific title availability, included/free versus rent/buy distinction, adequate request limits, acceptable attribution and enough reliability for the demo.

Availability lookup is separate from Parallel Search. Parallel provides live review/evidence intelligence; the availability source determines whether a candidate can actually be watched.

15. Recommendation architecture

The confirmed architecture is:

Evidence -> Film Profile -> contextual weighting -> Personal Fit Score -> shortlist role.

The Film Profile is evidence-led and stable for the film. Context affects how relevant those qualities are to the current user and session. The user's context must not rewrite the underlying assessment of the film.

16. Stable Film Profile dimensions

The Film Profile has six dimensions:

1. Story and writing: narrative coherence, screenplay, dialogue and character development.

2. Pacing and structure: rhythm, momentum, editing and whether the experience is brisk, measured, slow or uneven.

3. Performances: acting quality, chemistry and character credibility.

4. Tone and emotional character: qualities such as warm, bleak, funny, tense, frightening, celebratory or unsettling.

5. Craft and execution: direction, cinematography, production design, sound, music and technical execution.

6. Accessibility and demandingness: how much attention, patience or emotional commitment the film asks of the viewer.

The old seven-dimension Brief 1 spike rubric is not the product contract for post-Task-02 work.

17. Evidence State

Evidence quality is represented separately from film quality.

TONI should distinguish at least:

strong agreement

meaningful disagreement

sparse evidence

mainly official/factual evidence

Critical disagreement must not be flattened into false consensus. Where disagreement could materially change the user's decision, TONI should explain why it matters in concise, taste-relevant language.

Limited evidence is not the same as mixed evidence. Official information can support likely-fit assessment when reviews are sparse, but TONI must be clear about the evidence basis and must not present marketing as independent validation.

18. Hard constraints and soft preferences

Hard constraints can remove a film before final ranking. These include:

verified availability

explicit runtime limits

age/certification restrictions

explicit content or genre exclusions

watched titles when the user says they do not want repeats

rent/buy eligibility

Soft preferences change ranking rather than eligibility. These include:

genre preference

mood

pacing appetite

tone

demandingness

taste history

light season/cultural context

intelligent stretch

Dynamic weights must genuinely affect ranking. They cannot be decorative values beside an essentially unweighted verdict.

19. Personal Fit Score

TONI uses an internal normalised Personal Fit Score for ranking and comparison.

The raw numerical score is not shown to customers by default.

Customer-facing explanations should translate the weighted fit into natural language: why the tone, pacing, performances, craft, story or demandingness suits this person tonight.

20. Candidate generation and recommendation depth

TONI is not limited internally to three candidates.

The product should build a broader credible candidate pool, research/filter/rank enough of that pool to know what the strongest choices are, and fully prepare the initial recommendations.

The exact candidate-pool size is an engineering and performance parameter rather than a new product decision. It should be large enough to support strong ranking, seven eligible recommendations where possible and sensible refinement without causing unnecessary latency or cost.

21. Initial output: Top 3 for tonight

The first result view is labelled Top 3 for tonight.

The three roles are:

Best fit

Strong alternative

Worth a stretch

Best fit is the strongest direct recommendation for this user and session.

Strong alternative is deliberately distinct rather than a near-duplicate of Best fit. It should give the user a credible alternative path that still fits the brief.

Worth a stretch is not random novelty. It uses a separate stretch signal so a slightly less obvious title can surface when there is a strong, evidence-based adjacent reason to broaden the user's usual choices.

22. Recommendation card content

Top 3 cards stay minimal by default and should include:

artwork

title

concise reason

runtime

where to watch

The recommendation explanation should be specific and personal rather than generic plot summary.

Deeper evidence and source reasoning are available on demand through a control such as Why this?

The default experience should not expose raw rubric numbers or overwhelm the user with evidence detail.

TONI is spoiler-free by default.

23. Full recommendation set

TONI is not a three-result-only product.

The initial Top 3 deliberately reduces decision effort, but the user can choose Show my full recommendations.

The full set contains seven ranked recommendations in total where sufficient eligible candidates exist.

The first three retain their named roles. The additional four remain ranked but do not require artificial role labels.

The interaction principle is: narrow first, expand on demand.

24. Refinement model

After recommendations, the user can choose, expand or refine without restarting onboarding.

Default lightweight actions can include:

Something lighter

Something shorter

More like this

None of these

The user must also be able to refine in natural language, for example:

Actually, make it less intense and a bit more fun.

This is intentionally a blend of guided controls and free conversational refinement. The product should not become an unrestricted general-purpose chatbot.

25. Refinement behaviour depends on intent

TONI should not perform the same technical action for every refinement.

More like this:

Preserve the current taste/session model and expand around the selected recommendation. Bring in additional related candidates when needed.

Something shorter, lighter, less intense or similar bounded change:

Re-filter or re-rank the existing candidate pool first. Fetch new films only if the pool cannot satisfy the request strongly enough.

None of these:

Treat this as meaningful negative feedback. Reassess the existing pool and what may have been misunderstood, then use a hybrid of re-ranking and fresh research where needed.

Free-text refinement:

Interpret whether the request is a re-ranking request, expansion request or broader reset, then choose the appropriate behaviour.

This is part of the agentic product logic. TONI should decide the correct operation based on user intent rather than routing every control to the same search.

26. Refinement acknowledgement

TONI briefly acknowledges what it changed without exposing scoring machinery.

Examples:

Got it, I'll prioritise shorter options and keep the rest of your preferences.

I'll go broader this time and bring in some new possibilities.

I'll keep the same vibe, but look for more films like this one.

The acknowledgement should be short, useful and consistent with TONI's warm, film-aware, not-over-chatty voice.

27. Generate depth before display depth

The preferred recommendation-generation approach is hybrid.

TONI should build and rank a broader eligible candidate pool before displaying results. It should fully prepare the Top 3 first and keep enough ranked depth available that Show my full recommendations feels fast.

The additional four do not need the same level of up-front presentation preparation as the Top 3, but they should not require TONI to restart the recommendation process from zero.

Additional research can be triggered when refinement materially changes the brief or the current candidate pool is too weak.

28. Account timing

A first-time user is not forced to create an account before receiving recommendations.

The MVP follows recommend first, save afterwards.

TONI should demonstrate value first, then offer a lightweight account/sign-in step such as:

Save your taste and recommendations?

Creating or signing into an account enables persistent learning and continuity across sessions.

29. Returning-user product intent

TONI is designed to become something the user comes back to. Persistent memory is therefore part of the MVP product direction, not merely a distant future concept.

However, the profile must be lightweight. TONI should not force a long preference questionnaire or complex preference management before it becomes useful.

The product should feel like conversational memory that builds over time, not a static recommendation-settings form.

30. Persistent memory model

TONI should persist useful structured context including:

enduring taste signals

service access

films TONI recommended

films the user says they watched

likes

dislikes

rejections and corrections

Full historical conversation storage is not required as the recommendation memory model. Useful signals should be extracted into structured memory where appropriate.

31. What TONI may save automatically

The rule is high-confidence inference.

TONI may add a long-term memory automatically when a preference is repeated, strongly expressed or supported by sufficiently strong behaviour.

Weaker signals and one-off requests stay session-specific until there is enough evidence.

Examples:

I hate jump-scare horror can become durable quickly.

Repeated selection of slow, character-led dramas can gradually support a preference signal.

Nothing heavy tonight remains tonight context.

The implementation needs a confidence/provenance concept so the system can distinguish explicit statement, repeated behaviour and tentative inference. Exact thresholds are an implementation and validation decision.

32. User control over memory

Persistent memory must be visible and editable.

A lightweight area such as My taste should let the user:

see what TONI currently remembers

edit a memory

remove a memory

correct an incorrect inference

adjust service access

The product should not expose dozens of sliders or ask the user to manually maintain the model. TONI learns progressively; the user retains control.

33. Viewing and recommendation history

The MVP remembers recommendation and viewing signals that can improve future decisions:

what TONI recommended

what the user says they watched

likes and dislikes

rejections/corrections

Choosing or opening a recommendation is useful interaction evidence but must not automatically be treated as proof that the user watched or liked the film.

The system should distinguish recommendation, selection/intent, confirmed watch state and explicit reaction where those states are captured.

34. Group viewing

Group viewing is explicitly outside the hackathon MVP.

The solo experience is rich enough to prove TONI's core value and agentic reasoning. Group mode would add second-person intake, additional weighting behaviour, extra branching and more test states that are not required for the core demonstration.

Group viewing is moved to Future Development Opportunities rather than discarded.

35. Other explicit hackathon exclusions

The following must not silently creep back into the MVP without a new decision:

television recommendations

WhatsApp or Messenger distribution

TONI avatar or animated companion

full household profiles

streaming-account logins

automatic bundle/add-on entitlement detection

universal market coverage

deep cinema/theatrical availability

live TV scheduling

rich social/sharing system

Letterboxd import

Trakt integration

price comparison

live cultural-event intelligence

elaborate preference questionnaires

unrestricted general chatbot behaviour

36. Hackathon runtime requirements

The submitted product must genuinely run the required Google and partner integrations rather than only describing them.

Parallel Search must be actively called at runtime as part of an actual user session. A one-off development script whose output is later read from a cache is not sufficient for the Parallel-track requirement.

Gemini/Google agent tooling must remain part of the submitted runtime architecture in line with the hackathon requirements.

Availability is a separate non-AI data function. Do not conflate Parallel evidence search with the availability provider unless a future provider genuinely supplies both and the product contract remains intact.

37. Recommended runtime story

The clean product/architecture story is:

user context and memory

-> candidate discovery

-> live Parallel evidence

-> Film Profile

-> hard constraints including live availability

-> contextual weighting and Personal Fit Score

-> shortlist roles

-> user refinement

-> selective memory update

The interface may communicate progress in simple product language such as:

Researching the films

Checking what you can watch

Matching them to tonight

Do not turn the consumer interface into a technical dashboard. The detailed architecture belongs in the submission video and technical documentation.

38. Build-order principle

Persistent memory is now part of the MVP, but it must not block the qualifying recommendation loop.

Implementation order should be:

1. Anonymous end-to-end TONI recommendation loop works.

2. Account can save that state.

3. Returning TONI can use saved state.

4. Memory editing and learning behaviour are layered on and validated.

Do not build a sophisticated account/profile system first and hope the core recommendation loop works later.

39. Validation requirements

Before implementation is considered product-correct, the recommendation framework must be sanity-tested against materially different cases using the same candidate set.

At minimum include:

a viewer wanting something challenging

a tired viewer wanting something easy

a seasonal or other contextual case that should materially change ranking without changing Film Profiles

The rankings should move for understandable, traceable reasons.

Task 04 additionally requires UX/behaviour validation of:

fast mode respecting its question budget

country confirmation before availability filtering

no assumed service access

Top 3 plus Show my full recommendations

refinement choosing the correct re-rank/expand/reset behaviour

persistent memory not confusing tonight context with durable preference

manual memory correction being possible

40. Product voice and explanation rules

TONI should be warm, not clinical; lightly witty, not jokey; film-aware, not snobbish; confident but reasoned; specific rather than generic; helpful without becoming over-chatty; honest about evidence limits; respectful of the user's taste.

TONI can make recommendations confidently, but must not pretend to have personal taste or first-hand viewing experience.

Reasons should explain fit for this person and situation, not simply repeat synopsis or critical consensus.

41. Builder questions that are already answered

Should we show exactly three recommendations? No. Show Top 3 first, with seven total available through Show my full recommendations.

Can unavailable films appear in positions four to seven? No. Availability is a hard constraint for every exposed recommendation.

Should free services be selected automatically? No.

Can TONI infer country? It can identify a likely country, but must confirm before availability filtering.

Does fast mode mean lower-quality results? No. It means less intake.

Can fast mode ask lots of questions if confidence is low? No. One essential clarification maximum.

Is a taste anchor mandatory? No. It is adaptive; actively seek/derive one in deeper intake when useful.

Does a request such as "nothing heavy tonight" change long-term taste memory? No.

Should all refinement trigger a fresh search? No. Behaviour depends on intent.

Should we require login before recommending? No. Recommend first, save afterwards.

Is persistent memory in MVP? Yes, as lightweight progressive structured memory.

Should full historic chats be the memory store? No. Persist useful structured taste/access/history signals.

Can memory be edited? Yes.

Is group mode in MVP? No.

Are messaging channels in MVP? No.

42. Decisions deliberately left to implementation

The following do not require another product decision unless implementation exposes a contradiction:

authentication method

database/storage technology

exact memory schema and confidence thresholds

exact candidate-pool size

caching strategy

specific live availability vendor/API

technical retry strategy

service ordering within country lists

exact component design

exact microcopy of every prompt

exact medium/deep question sequence

orchestration mechanics between Gemini, Parallel and availability lookup

whether recommendation cards deep-link directly to a provider

exact My taste screen layout

Implementers should choose these in service of the product rules above, not use them as a reason to reopen settled product decisions.

43. Mandatory reconciliation with older records

Some earlier documents contain now-superseded hackathon assumptions. This Task 04 record is authoritative for the MVP cut.

Specifically superseded:

- the earlier statement that persistent viewing-history learning and long-term taste learning are outside the hackathon. Task 04 promotes a bounded progressive memory model into MVP.

- the earlier statement that full conversational recommendation is outside the hackathon. Task 04 promotes conversational intake and bounded free-text refinement, while still rejecting an unrestricted general chatbot.

- the earlier implication that TONI only returns three recommendations. Task 04 defines Top 3 first and seven total recommendations.

- any wording that suggests common/free services may be treated as confirmed by default. No service is preselected; the user confirms access.

- the old seven-dimension Brief 1 rubric as a continuing product contract. The six-dimension Task 02 Film Profile is authoritative for post-Task-02 product work.

Task 03's live availability model, UK/US boundary, rent/buy rule, unverified failure behaviour and honest coverage principles remain fully in force.

44. Gate review

Status: PASS.

Confirmed: the MVP experience, intake-depth model, availability interaction, recommendation depth, Top 3/full-seven output, refinement behaviour, progressive account/memory model and scope exclusions are sufficiently defined for implementation.

Rejected: form-first onboarding; account wall before value; assumed service access; exactly-three-only output; seven recommendations shown immediately; generic chatbot-only experience; identical refinement behaviour for every request; full-chat-history memory as the core model; group mode; messaging channels; TV and other scope expansion for the hackathon.

Still open: implementation details and visual/microcopy decisions listed above. They are not product-strategy blockers.

Gate judgement: Task 04 has completed the hackathon MVP cut. Further product questioning at this level should stop unless build validation exposes a real contradiction or missing rule. The next stage is implementation planning, UX execution and end-to-end validation against this contract.