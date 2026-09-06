"""
TONI - Tonight's Options, Narrowed Intelligently
Backend Vertical Slice Simulation Entrypoint

An interactive, highly polished terminal application that demonstrates
the complete end-to-end TONI recommendation pipeline. It orchestrates
user contexts, live availability lookups, critical review evidence gathering,
evidence profiling, and dynamic soft-weighted ranking, rendering everything
in beautiful, structured CLI card layouts.
"""

import sys
import time
from typing import Any
from pathlib import Path

# Ensure local imports work
sys.path.append(str(Path(__file__).resolve().parent))

from contracts import UserContext, IntakeDepth, TasteSignal, SignalType, OutputRole
from ranking import rank_movies, SEED_FILMS

# --- ANSI COLOR CODES ---
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
BLUE = "\033[34m"
PURPLE = "\033[35m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
WHITE = "\033[37m"
RED = "\033[31m"

# --- ASCII LOGO ---
TONI_LOGO = f"""
{BOLD}{CYAN}  ████████╗ ██████╗ ███╗   ██╗██╗
  ╚══██╔══╝██╔═══██╗████╗  ██║██║
     ██║   ██║   ██║██╔██╗ ██║██║
     ██║   ██║   ██║██║╚████║██║
     ██║   ╚██████╔╝██║ ╚███║██║
     ╚═╝    ╚═════╝ ╚═╝  ╚══╝╚═╝{RESET}
  {BOLD}{WHITE}Tonight's Options, Narrowed Intelligently{RESET}
  {YELLOW}The Agentic Cinema Discovery Guide | Hackathon MVP{RESET}
"""


def render_card(rec: Any) -> None:
    """Render a single movie recommendation as a gorgeous, structured ASCII box card."""
    role = rec.role.value.upper()
    role_color = GREEN if rec.role == OutputRole.BEST_FIT else (BLUE if rec.role == OutputRole.STRONG_ALTERNATIVE else PURPLE)
    
    # Format metadata string
    meta_line = f"Director: {rec.metadata.director}  |  Runtime: {rec.metadata.runtime_minutes} min  |  Rating: {rec.metadata.age_rating}"
    genres_line = f"Genres: {', '.join(rec.metadata.genres)}"
    
    # Format availability string
    services_str = ", ".join(rec.availability.matched_services) if rec.availability.matched_services else "None matching"
    avail_line = f"Stream Match: {services_str} ({rec.availability.provider} / {rec.availability.country})"
    
    # Format Evidence State
    evidence_str = rec.evidence_state.value.replace("_", " ").title()
    evidence_line = f"Evidence State: {evidence_str}"
    
    width = 80
    border_char = "─"
    
    print(f"\n{role_color}┌{border_char * width}┐{RESET}")
    # Header line (Role + Score)
    header_text = f"  {role}"
    qual_label = "Exceptional Match" if rec.personal_fit_score >= 80 else ("Strong Match" if rec.personal_fit_score >= 60 else ("Good Match" if rec.personal_fit_score >= 40 else "Interesting Detour"))
    score_text = f"Match Level: {qual_label}  "
    spacing = width - len(header_text) - len(score_text)
    print(f"{role_color}│{RESET}{BOLD}{role_color}{header_text}{RESET}{' ' * spacing}{BOLD}{score_text}{role_color}│{RESET}")
    print(f"{role_color}├{border_char * width}┤{RESET}")
    
    # Movie Title Line
    title_line = f"  {rec.metadata.title.upper()} ({rec.metadata.year})"
    title_spacing = width - len(title_line) - 2
    print(f"{role_color}│{RESET}{BOLD}{WHITE}{title_line}{RESET}{' ' * title_spacing}{role_color}│{RESET}")
    
    # Movie Metadata Lines
    meta_spacing = width - len(f"  {meta_line}") - 2
    print(f"{role_color}│{RESET}  {meta_line}{' ' * meta_spacing}{role_color}│{RESET}")
    
    genres_spacing = width - len(f"  {genres_line}") - 2
    print(f"{role_color}│{RESET}  {genres_line}{' ' * genres_spacing}{role_color}│{RESET}")
    print(f"{role_color}├{border_char * width}┤{RESET}")
    
    # Availability & Evidence lines
    avail_spacing = width - len(f"  {avail_line}") - 2
    print(f"{role_color}│{RESET}  {avail_line}{' ' * avail_spacing}{role_color}│{RESET}")
    
    evidence_spacing = width - len(f"  {evidence_line}") - 2
    print(f"{role_color}│{RESET}  {evidence_line}{' ' * evidence_spacing}{role_color}│{RESET}")
    print(f"{role_color}├{border_char * width}┤{RESET}")
    
    # Rationale reason (Wrap words simple)
    reason_label = "  Why this fits: "
    reason_text = rec.concise_reason
    
    # Wrap ONLY the reason text (width - 19 to account for label prefix and borders)
    words = reason_text.split()
    lines = []
    current_line = []
    for w in words:
        if len(" ".join(current_line + [w])) < (width - 19):
            current_line.append(w)
        else:
            lines.append(" ".join(current_line))
            current_line = [w]
    if current_line:
        lines.append(" ".join(current_line))
        
    for idx, l in enumerate(lines):
        if idx == 0:
            print_line = f"{reason_label}{l}"
            line_spacing = width - len(print_line) - 2
            print(f"{role_color}│{RESET}{BOLD}{YELLOW}  Why this fits: {RESET}{YELLOW}{l}{RESET}{' ' * line_spacing}{role_color}│{RESET}")
        else:
            print_line = f"                 {l}"
            line_spacing = width - len(print_line) - 2
            print(f"{role_color}│{RESET}{YELLOW}                 {l}{RESET}{' ' * line_spacing}{role_color}│{RESET}")
            
    # Stretch reason if available
    if rec.stretch_signal:
        print(f"{role_color}├{border_char * width}┤{RESET}")
        stretch_line = f"  * STRETCH SIGNAL: {rec.stretch_signal}"
        stretch_words = stretch_line.split()
        st_lines = []
        curr_line = []
        for w in stretch_words:
            if len(" ".join(curr_line + [w])) < (width - 4):
                curr_line.append(w)
            else:
                st_lines.append(" ".join(curr_line))
                curr_line = [w]
        if curr_line:
            st_lines.append(" ".join(curr_line))
            
        for l in st_lines:
            line_spacing = width - len(l) - 2
            print(f"{role_color}│{RESET}{PURPLE}{l}{RESET}{' ' * line_spacing}{role_color}│{RESET}")
            
    print(f"{role_color}└{border_char * width}┘{RESET}")


def run_pipeline(context: UserContext) -> None:
    """Orchestrate and present the complete vertical slice pipeline execution."""
    print(f"\n{BOLD}{CYAN}>>> Executing TONI Pipeline Reasoning Loop...{RESET}")
    time.sleep(0.5)
    
    print(f"  {BOLD}Step A:{RESET} Parsing Active Session context ({context.country} market)...")
    print(f"  {BOLD}Step B:{RESET} Evaluating {len(SEED_FILMS)} movies on streaming availability & filters...")
    time.sleep(0.4)
    
    print(f"  {BOLD}Step C:{RESET} Retrieving critical reviews and evidence from Parallel...")
    time.sleep(0.6)
    
    print(f"  {BOLD}Step D:{RESET} Mapping canonical six-dimension Film Profiles and Evidence States...")
    time.sleep(0.5)
    
    print(f"  {BOLD}Step E:{RESET} Running personal fit scoring, weights, and stretch analysis...")
    time.sleep(0.4)
    
    # Rank movies
    res = rank_movies(context)
    
    if not res.recommendations:
        print(f"\n{BOLD}{RED}No recommendations could be matched. Please widen your streaming services or allow rent/buy.{RESET}\n")
        return
        
    print(f"\n{BOLD}{GREEN}=== TONI REVEALS: YOUR SHORTLIST FOR TONIGHT ==={RESET}")
    
    # Output the Top 3
    top_3 = [r for r in res.recommendations if r.role != OutputRole.RANKED_ADDITIONAL]
    for r in top_3:
        render_card(r)
        time.sleep(0.3)
        
    # Output the Suffix Watchlist
    additional = [r for r in res.recommendations if r.role == OutputRole.RANKED_ADDITIONAL]
    if additional:
        print(f"\n{BOLD}{WHITE}├─ ALSO WORTH CONSIDERING tonight (Expanded Watchlist) ───{RESET}")
        for idx, r in enumerate(additional):
            services_str = ", ".join(r.availability.matched_services) if r.availability.matched_services else "None matching"
            qual_label = "Exceptional" if r.personal_fit_score >= 80 else ("Strong" if r.personal_fit_score >= 60 else ("Good" if r.personal_fit_score >= 40 else "Detour"))
            print(f"  {idx+4}. {BOLD}{WHITE}{r.metadata.title}{RESET} ({r.metadata.year}) - Match: {YELLOW}{qual_label}{RESET} | Stream: {services_str}")
        print(f"{BOLD}{WHITE}└──────────────────────────────────────────────────────────{RESET}\n")


def custom_intake_flow() -> None:
    """Highly interactive custom onboarding flow allowing judges to specify custom inputs."""
    print(f"\n{BOLD}{CYAN}=== TONI CUSTOM INTAKE FORM ==={RESET}")
    
    # 1. Country Selection
    country = ""
    while country not in ("UK", "US"):
        country = input(f"Enter viewing country ({BOLD}UK{RESET} or {BOLD}US{RESET}): ").upper().strip()
        
    # 2. Services Access
    services = []
    while not services:
        print(f"\nSelect streaming platforms you pay for/access ({BOLD}comma-separated list{RESET}):")
        print("Example options: Netflix, Prime Video, Disney+, Max, Paramount+, Pluto TV, Channel 4")
        services_input = input("Your Services: ").strip()
        services = [s.strip() for s in services_input.split(",") if s.strip()]
        if not services:
            print(f"{RED}Error: You must select at least one streaming service.{RESET}")
        
    # 3. Rent/Buy opt-in
    rent_buy_input = input("\nAllow rent/purchase options? (yes/no, default no): ").lower().strip()
    allow_rent_buy = rent_buy_input in ("yes", "y", "true")
    
    # 4. Pacing Preference
    print(f"\nSelect your pacing preference:")
    print("1. Brisk (Fast, engaging)")
    print("2. Measured (Moderate pacing)")
    print("3. Slow (Slow-burning, cinematic space)")
    pacing_choice = input("Pacing Choice (1/2/3, default measured): ").strip()
    pacing_val = "brisk" if pacing_choice == "1" else ("slow" if pacing_choice == "3" else "measured")
    
    # 5. Demandingness Preference
    print(f"\nSelect your attention/effort budget (1 to 5 scale):")
    print("1 = Extremely light, mindless viewing")
    print("3 = Balanced commitment")
    print("5 = Highly demanding, artistic or emotionally heavy")
    dem_input = input("Attention Level (1-5, default 3): ").strip()
    try:
        demandingness = float(dem_input)
        if not (1.0 <= demandingness <= 5.0):
            demandingness = 3.0
    except ValueError:
        demandingness = 3.0
        
    # 6. Preferred Tone
    print(f"\nSelect a preferred tone adjective (or press enter to skip):")
    print("Example: funny, magical, tense, intense, bleak, mind-bending, emotional")
    tone_val = input("Preferred Tone: ").strip().lower()
    
    # 7. Exclude Genre
    print(f"\nSpecify any genre you want to ABSOLUTELY EXCLUDE tonight (or press enter to skip):")
    print("Example: Horror, Sci-Fi, Crime")
    exclude_val = input("Exclude Genre: ").strip()
    
    # Build tonight signals
    tonight_signals = [
        TasteSignal(name="pacing", value=pacing_val, signal_type=SignalType.SOFT_SESSION_PREFERENCE),
        TasteSignal(name="demandingness", value=demandingness, signal_type=SignalType.SOFT_SESSION_PREFERENCE),
    ]
    if tone_val:
        tonight_signals.append(TasteSignal(name="tone", value=tone_val, signal_type=SignalType.SOFT_SESSION_PREFERENCE))
    if exclude_val:
        tonight_signals.append(TasteSignal(name="exclude-genre", value=[exclude_val], signal_type=SignalType.HARD_CONSTRAINT))
        
    context = UserContext(
        country=country,
        service_access=services,
        allow_rent_buy=allow_rent_buy,
        intake_depth=IntakeDepth.GET_TO_KNOW_ME,
        tonight_signals=tonight_signals
    )
    
    run_pipeline(context)


def main() -> None:
    print(TONI_LOGO)
    
    while True:
        print(f"\n{BOLD}{WHITE}=== CHOOSE A SCENARIO TO SIMULATE TONIGHT ==={RESET}")
        print(f"1. {BOLD}Persona A:{RESET} Light, fun comedy lover (UK, Netflix access, allow Rent/Buy)")
        print(f"2. {BOLD}Persona B:{RESET} Heavy, demanding crime/drama classic lover (US, Paramount+/Pluto TV, no Rent/Buy)")
        print(f"3. {BOLD}Persona C:{RESET} Wondrous fantasy seeker (US, Netflix, excludes Sci-Fi & Crime)")
        print(f"4. {BOLD}Custom Intake:{RESET} Enter your own live mood and streaming parameters!")
        print(f"5. Exit")
        
        choice = input("\nEnter choice (1-5): ").strip()
        
        if choice == "1":
            # Persona A Context
            context = UserContext(
                country="UK",
                service_access=["Netflix"],
                allow_rent_buy=True,
                intake_depth=IntakeDepth.JUST_GIVE_ME_SOMETHING,
                tonight_signals=[
                    TasteSignal(name="pacing", value="brisk", signal_type=SignalType.SOFT_SESSION_PREFERENCE),
                    TasteSignal(name="demandingness", value=2.0, signal_type=SignalType.SOFT_SESSION_PREFERENCE),
                    TasteSignal(name="tone", value="funny", signal_type=SignalType.SOFT_SESSION_PREFERENCE),
                ]
            )
            run_pipeline(context)
            
        elif choice == "2":
            # Persona B Context
            context = UserContext(
                country="US",
                service_access=["Paramount+", "Pluto TV"],
                allow_rent_buy=False,
                intake_depth=IntakeDepth.A_COUPLE_OF_QUESTIONS,
                tonight_signals=[
                    TasteSignal(name="demandingness", value=4.0, signal_type=SignalType.SOFT_SESSION_PREFERENCE),
                    TasteSignal(name="tone", value="intense", signal_type=SignalType.SOFT_SESSION_PREFERENCE),
                ]
            )
            run_pipeline(context)
            
        elif choice == "3":
            # Persona C Context
            context = UserContext(
                country="US",
                service_access=["Netflix"],
                allow_rent_buy=True,
                intake_depth=IntakeDepth.GET_TO_KNOW_ME,
                tonight_signals=[
                    TasteSignal(name="exclude-genre", value=["Sci-Fi", "Crime"], signal_type=SignalType.HARD_CONSTRAINT),
                    TasteSignal(name="tone", value="magical", signal_type=SignalType.SOFT_SESSION_PREFERENCE),
                ]
            )
            run_pipeline(context)
            
        elif choice == "4":
            custom_intake_flow()
            
        elif choice == "5":
            print(f"\n{BOLD}{CYAN}Thank you for experiencing TONI! Have an exceptional movie night! 🎬{RESET}\n")
            break
        else:
            print(f"\n{BOLD}{RED}Invalid choice, please select 1 to 5.{RESET}")


if __name__ == "__main__":
    main()
