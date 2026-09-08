"""Opt-in live acceptance check; uses configured providers, never mock availability.

Run from the project root: python scripts/validate_unrestricted_voice.py
Writes a credential-free report to validation/unrestricted_voice/live_acceptance.json.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
for flag in ('TONI_TESTING', 'TONI_MOCK_GEMINI_LIVE'):
    os.environ.pop(flag, None)
os.environ['TONI_USE_MOCK_AVAILABILITY'] = 'false'

from api import extract_voice_context, _search_offer
from contracts import UserContext
from ranking import _rank_movies_live

request = 'I am in the UK, want something funny like Ted Lasso, with no restrictions and access to all channels.'
ctx = UserContext(country='UK', service_access=[], intake_depth='a_couple_of_questions')
started = time.monotonic()
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    ctx, _, extraction_mode = extract_voice_context(request, ctx, return_mode=True)
    confirmed, _ = extract_voice_context('Yes, please.', ctx)
    response = _rank_movies_live(confirmed, defer_reviews=True)
report = {
    'request': request, 'extraction_mode': extraction_mode,
    'context': ctx.model_dump(mode='json'), 'offer': _search_offer(ctx),
    'affirmation_preserved_context': confirmed == ctx,
    'elapsed_seconds': round(time.monotonic() - started, 2),
    'diagnostics': response.search_diagnostics,
    'recommendations': [{'title': r.metadata.title, 'year': r.metadata.year,
                         'genres': r.metadata.genres, 'availability': r.availability.model_dump(mode='json')}
                        for r in response.recommendations],
}
out = ROOT / 'validation' / 'unrestricted_voice' / 'live_acceptance.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
