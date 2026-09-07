# TONI production release — 7 September 2026

The user authorised production promotion after candidate review. Cloud Run revision
`toni-app-00032-sal` now serves 100% of production traffic. Previous revision
`toni-app-00030-xow` remains available for rollback.

Production: https://toni-app-38088879709.us-central1.run.app/

## Released behavior

- One Find my results action, available after choices are confirmed; no automatic search from a partial or ambiguous voice response.
- First-message preferences are retained, redundant intake questions are skipped, and Start fresh resets the full conversation.
- Results-only refinements preserve channels and unrelated preferences. Dropdown changes wait for Update results; runtime, tone, exclusions and film references can be cleared.
- UK Sky Go/NOW coverage and recent-film defaults are retained.
- Voice context changes preserve newer edits; canonical transcripts reconcile without duplicate completion entries. Voice remains labelled Beta.
- Usable extracted review excerpts are retained when full-page content is unavailable. Baseline review dimensions are labelled Not assessed.
- Runtime deadlines, deployment provenance and versioned frontend assets are included.

## Verification and provenance

- 236 automated tests passed; four opt-in network tests were skipped.
- Real Edge browser checks passed for confirmation, search, empty/populated result refinements, channel retention and reset.
- Live candidate searches returned seven films each. Two concurrent requests completed in 13.31s and 11.22s.
- Generated PCM exercised three live voice turns. Served-JavaScript event replay verified transcript/audio ordering and one confirmed search request.
- Production health and served HTML were checked after promotion and matched the verified candidate source.
- Physical microphone/speaker acoustics and broad load/accent coverage were not independently verified. Review fallbacks remain possible and labelled.

Image digest: `sha256:116c0ce211e511e37d60293a302e6953ed967ffebfc120c37c6e2a3abf36e27c`

Packaged source fingerprint: `sha256:ef8728731f13ce5f908cacdd090a5a8b728d4e76a7c6b174a8e237369cbf2517`

Cloud Build: `88229b1e-b100-4366-8cfa-3e6e4bf665e0`

The image was built from the tested working tree before the release commit. Its
manifest therefore records base commit `e1b14c748273bf309b1790571ecf768cd96c3103`
and dirty status. The source fingerprint identifies the packaged build; the commit
containing this note publishes that released application code. Git may normalize
text line endings. Generate a fresh manifest for any future build using the
deployment script; do not reuse the packaged manifest as a new build identity.
