# Voice/Avatar Consent Foundation Update - 2026-06-19

This update closes the first practical slice of the production backlog item "legal consent for voice/avatar".

## Implemented

- File-backed consent ledger in `backend/app/services/consent_service.py`.
- Consent models:
  - `ConsentType`: `voice`, `avatar`
  - `ConsentCreate`
  - `ConsentRecord`
- Consent API endpoints:
  - `GET /consents`
  - `POST /consents`
- Consent records can be scoped to:
  - actor/user
  - organization
  - project
  - voice_id for voice consent
- Consent records support grant and revoke by storing `granted=true/false`; the latest applicable record wins.
- Audit event `consent.record` is written for every consent grant/revoke.
- Enforcement was added before sensitive operations:
  - non-placeholder voice provider requires `voice` consent before `generate_voice`, `render`, and `generate_all`;
  - `avatar_enabled=true` requires `avatar` consent before `generate_slides`, `regenerate_scene_slide`, `prepare_avatar`, `render`, and `generate_all`;
  - queued jobs are checked at job start, so sensitive features cannot be bypassed through `/projects/{id}/jobs/{job_type}`.
- Mobile TypeScript types and API wrappers:
  - `ConsentType`
  - `ConsentRecord`
  - `listConsents`
  - `recordConsent`
- Backend tests cover avatar consent and AI voice consent flows.

## Verified

- `python -m pytest backend\tests\test_pipeline.py -q --maxfail=1`
  - Result: `51 passed, 1 warning`
- `npm.cmd run check:ci`
  - Result: passed.
  - Note: npm still reports moderate `js-yaml` advisories through React Native/Metro/Jest, but the configured high-severity production audit passes.

## Still Not Production-Complete

- Consent storage is still local JSON, not PostgreSQL/immutable storage.
- Consent language is a default MVP statement, not jurisdiction-specific legal copy.
- There is no dedicated UI for viewing/revoking consents yet.
- There is no identity verification for the person whose likeness/voice is being used.
- There is no provider-side consent sync with avatar/voice vendors.
- There is no admin/support workflow for consent disputes, deletion requests, or retention policy.
