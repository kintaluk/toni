# TONI Experience: Comprehensive User-Facing Copy Inventory

This document provides a complete extraction of all text and copy presented to users across every touchpoint of the **TONI (Tonight's Options, Narrowed Intelligently)** experience.

---

## 1. Global Navigation & Branding

### Page Metadata & Title
- **Page Title**: `TONI | What fits tonight?`
- **Meta Description**: `TONI (Tonight's Options, Narrowed Intelligently) - Your personal agentic guide to what's worth watching next.`
- **Screen Reader Anchor**: `Tonight's Options, Narrowed Intelligently`

### Top Navigation Bar
- **Brand Logo Alt**: `TONI Aperture Mark`
- **Brand Name**: `TONI`
- **Status Badge**: `Agent`
- **Navigation Buttons**:
  - `💬 Return to chat` *(visible when viewing results)*
  - `↺ New chat` *(restarts intake conversation)*

---

## 2. Conversational Intake Flow (Step-by-Step)

### Step 1: Effort Level (Intake Depth)
- **TONI Prompt**:
  > *"Good evening. I'm TONI, your agentic cinema guide. How much effort do you want to give right now?"*
- **Subtext**:
  > *"You can tap a suggested answer below or type directly in the chat bar."*
- **Option Buttons**:
  1. `Just give me something`
  2. `A couple of questions is fine`
  3. `Get to know what I want`

### Step 2: Country / Market & Rent/Buy Preference
- **TONI Prompt**:
  > *"Where are you streaming tonight, and should we include digital rentals or purchases?"*
- **Subtext**:
  > *"Catalogues differ significantly between countries."*
- **Form Labels & Options**:
  - **Market**:
    - `🇬🇧 United Kingdom`
    - `🇺🇸 United States`
  - **Rental / Purchase Option**:
    - `Included only`
    - `Rent & Buy OK`
  - **Action Button**: `Confirm location & continue →`
- **User Bubble Confirmation**:
  - e.g., `UK, Included only` or `US, Rent & Buy OK`

### Step 3: Streaming Platform Availability
- **TONI Prompt**:
  > *"Which streaming services do you have access to tonight?"*
- **Subtext**:
  > *"I will strictly verify availability against these services before ranking."*
- **Utility Actions**:
  - `Select All`
  - `Clear All`
- **Supported Provider Chips (UK)**:
  - `Netflix` | `Prime Video` | `Disney+` | `BBC iPlayer` | `ITVX` | `Channel 4` | `Paramount+` | `Apple TV+`
- **Supported Provider Chips (US)**:
  - `Netflix` | `Prime Video` | `Disney+` | `Max` | `Hulu` | `Paramount+` | `Pluto TV` | `Apple TV+`
- **Action Button**: `Confirm streaming access →`
- **User Bubble Confirmation**:
  - e.g., `3 services selected (Netflix, Prime Video, Disney+)` or `Rentals only`

### Step 4: Pacing & Emotional Tone
- **TONI Prompt**:
  > *"What cadence and emotional character are you seeking tonight?"*
- **Pacing Appetite**:
  - `⚡ Brisk (Fast, energetic)`
  - `⏱️ Measured (Deliberate)`
  - `🌿 Slow (Contemplative)`
- **Desired Tone**:
  - `Tense & suspenseful`
  - `Mind-bending & intellectual`
  - `Warm & heartfelt`
  - `Intense & gritty`
  - `Funny & witty`
- **Hard Exclusions (in "Get to know what I want" mode)**:
  - Label: `Hard Exclusions:`
  - Dropdown: `No exclusions` | `Exclude Horror` | `Exclude Crime` | `Exclude Sci-Fi` | `Exclude Comedy`
- **Action Button**: `Confirm taste preferences →`
- **User Bubble Confirmation**:
  - e.g., `brisk pacing, warm & heartfelt`

### Ready Turn: Transition to Shortlist
- **TONI Prompt**:
  > *"I have everything I need to synthesize tonight's shortlist!"*
- **Subtext**:
  > *"Have any specific mood or actors in mind? Type below or tap "Find what fits tonight" to open your shortlist."*
- **Primary CTA Button**:
  - `Find what fits tonight →`

---

## 3. Persistent Bottom Chat Bar & Voice Controls

### Input Bar Controls
- **Voice Mic Toggle**:
  - Default: `🎙️ Talk to TONI`
  - Listening state: `🎙️ Listening...`
  - Speaking state: `🎙️ TONI Speaking...`
- **Text Input Placeholder**:
  > `"Type a response or describe what you want tonight..."`
- **Send Button**: `Send →`
- **Helper Footnote**:
  > *"Talk to TONI by voice or text, or tap any suggested answer button above."*

### Dynamic Voice Banner Statuses
- **Listening (Silence)**:
  > **TONI Voice:** Listening to your viewing mood... Speak now.
- **Hearing (Speech Detected)**:
  > **TONI Voice:** Hearing your voice... Speak now.
- **Streaming Response**:
  > **TONI Voice:** Film-critic response streaming...
- **Dismiss Button**: `Done`

### Inline Readiness Callout (Turn 2+ / Mid-Dialogue)
- **Callout Heading**:
  > *"TONI is ready to curate your shortlist based on your criteria."*
- **Callout Button**:
  - `Find what fits tonight →`

---

## 4. Multi-Turn Conversational Fallbacks & Backend Prompts

### Rule-based / Cold-start Greetings & Fallbacks
- **Initial Fallback Greeting**:
  > *"I'm TONI, and I'm listening. Tell me what kind of emotional tone, pacing, or storytelling feels right for tonight."*
- **Signal Extraction Acknowledgement**:
  > *"Noted: {extracted signals}. What streaming services are we watching on tonight?"*
- **Readiness Confirmation**:
  > *"I've locked into your viewing mood. Let's find what fits tonight across your available services!"*
- **Voice Re-prompt Fallback**:
  > *"I had trouble hearing that clearly. Tell me what kind of mood or pacing feels right tonight."*

### System Persona Guidelines (Voice & Text Backend)
- **Name**: Strictly locked to **TONI**. Never exposes internal voice identifiers (e.g. Charon) or model engine names.
- **Persona Role**: Thoughtful, warm, discerning film-festival programmer / curator.
- **Turn Length**: 1 to 3 sentences maximum. Conversational, succinct, never lecturing or reciting long lists.

---

## 5. Loading & Generation View

- **Loader Header**:
  > *"Consulting Critical Consensus & Live Access"*
- **Loader Subtext**:
  > *"Synthesizing verified reviews via Parallel and verifying active catalogue availability for tonight..."*

---

## 6. Dedicated Results Page ("What fits tonight?")

### Page Header
- **Badge**: `Verified Shortlist`
- **Market Tag**: `Market: {UK/US} • {Selected Services}`
- **Page Title**:
  > *"What fits tonight?"*
- **Subtitle**:
  > *"Intelligently narrowed from verified critical consensus and your active streaming platforms."*
- **Top Action**: `← Adjust conversation`

### Recommendation Watchcards (Top 3)

#### Presentation Role Badges
1. **Best Fit**: `BEST FIT` *(Electric Lime badge)*
2. **Strong Alternative**: `Strong alternative` *(Deep Ink pill)*
3. **Worth a Stretch**: `Worth a stretch` *(Transparent bordered pill)*

#### Card Controls & Information
- **Trailer Button (Available)**: `▶ Watch trailer`
- **Trailer Button (Unavailable)**: `Trailer unavailable`
- **Services Tag**: `{Matched service list}` or `Available to Rent or Buy`
- **Monograph Fallback Poster Text**: `Monograph` / `Official IMDb page ↗`
- **Metadata Line**:
  > `[Year] • Dir. [Director] • [Runtime] mins • Rated [Age Rating] • Official IMDb page ↗`
- **Genre Pills**: e.g., `Drama`, `Crime`, `Mystery`
- **Rationale Quote**:
  > *“{Concise reason generated from critical evidence}”*

#### "Worth a Stretch" Callout Box
- **Heading**: `Why this is worth a stretch:`
- **Body**:
  > *"While more demanding ({demandingness}/5) than your preferred easy vibe, its masterful directing represents an incredibly rewarding stretch."*

#### Verified Critical Evidence & Sources
- **Heading**: `Verified critical reviews & evidence:`
- **Source Link**: `↗ {domain} ({full URL})`

#### Editorial Dimension Breakdown & Evidence Drawer
- **Drawer Summary**: `View editorial dimension breakdown & evidence ▼`
- **Evidence State Labels**:
  - `Broad critical consensus` *(Strong agreement)*
  - `Critics are divided on this film` *(Meaningful disagreement)*
  - `Limited review coverage` *(Sparse evidence)*
  - `Overview from official sources` *(Mainly official/factual)*
- **The Six Fixed Film Profile Dimensions**:
  1. `Story & Writing` *(percentage score, e.g. 90%)*
  2. `Pacing & Structure` *(percentage score, e.g. 84%)*
  3. `Performances` *(percentage score, e.g. 96%)*
  4. `Craft & Execution` *(percentage score, e.g. 92%)*
  5. `Demandingness` *(percentage score, e.g. 60%)*
  6. `Tone Adjectives` *(e.g. tense, gritty, dark)*

### Additional Ranked Candidates (Positions 4 to 7)
- **Section Heading**: `Ranked Candidates (4 to 7)`
- **Candidate Accordion Header**:
  - `[Rank Number: 4-7]`
  - `[Title] ([Year]) • [Genres]`
  - `▶ Trailer` or `Trailer unavailable`
  - `[Services badge]`
- **Accordion Body**:
  - *“{Concise reason}”*
  - `Director: [Director]`
  - `Runtime: [Runtime] mins`
  - `Evidence: [Evidence state label]`

### Empty / No Match State
- **Heading**:
  > *"No candidates matched tonight's constraints"*
- **Message**:
  > *"None of our verified candidates are currently available on your selected streaming services in {Country}. Try enabling digital rentals or adjusting genre exclusions."*
- **Button**: `← Adjust in Chat`

### Bottom Page Controls
- **Prompt**:
  > *"Not quite what you were in the mood for? Chat with TONI to refine your rhythm, actors, or genres."*
- **Action Buttons**:
  - `← Refine in chat`
  - `Start fresh`

---

## 7. On-Brand Modals & Dialogs

### TONI Notice Dialog (Brand Modal)
- **Modal Header**: `TONI Notice`
- **Sample Error / Validation Messages**:
  - **Streaming Required**:
    > *"Please choose at least one streaming service you have access to, or enable digital rentals."*
  - **Microphone Access**:
    > *"Your browser does not support or allow microphone capture in this context. Please check permissions."*
    > *"Please grant microphone permissions in your browser to speak with TONI."*
  - **Recommendation Error**:
    > *"Unable to generate recommendations."*
- **Dismiss Button**: `Understood`

### Watch Trailer Dialog
- **Modal Header**: `Trailer - {Movie Title} ({Year})`
- **Footer Text**: `Official Studio Trailer`
- **External Link**: `Watch on YouTube ↗`
- **Close Button**: `✕ Close`
- **Embedded Fallback Notice**:
  > *"Trailer could not be loaded directly. Watch on YouTube ↗"*

---

## 8. Demo Quick Test Personas (`?debug=true`)

- **Drawer Header**: `Quick Test Personas ▼`
- **Action**: `Load Persona →`
- **Persona Cards**:
  1. **Persona A: The Comedy & Fun Seeker**
     > *"Brisk pacing, light attention effort (2.0/5), seeking a funny tone in the UK with Netflix access and rent/buy allowed."*
  2. **Persona B: The Classic Drama & Crime Lover**
     > *"High attention effort (4.0/5), intense mood in the US with Paramount+ and Pluto TV (strictly included, no rent/buy)."*
  3. **Persona C: The Fantasy Adventurer**
     > *"Wants a magical tone in the US, hard excluding Sci-Fi and Crime genres, with Netflix access."*

---

## 9. Terminal / CLI Simulation Mode (`src/main.py`)

- **ASCII Banner**:
  > `TONI`  
  > `Tonight's Options, Narrowed Intelligently`  
  > `The Agentic Cinema Discovery Guide | Hackathon MVP`
- **Match Level Badges**:
  - `Exceptional Match` (Fit score ≥ 80)
  - `Strong Match` (Fit score ≥ 60)
  - `Good Match` (Fit score ≥ 40)
  - `Interesting Detour` (Fit score < 40)
- **Card Fields**:
  - `Why Tonight: {Concise reason}`
  - `Stream Match: {Services} ({Provider} / {Country})`
  - `Evidence State: {Evidence state}`
  - `* STRETCH SIGNAL: {Stretch reason}`
