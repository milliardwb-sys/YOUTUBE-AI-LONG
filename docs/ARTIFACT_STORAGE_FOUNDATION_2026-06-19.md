# Artifact Storage Foundation Update - 2026-06-19

This update closes the first practical slice of the production backlog item "object storage instead of local files".

## Implemented

- Artifact access abstraction in `backend/app/services/artifact_store.py`.
- Current backend:
  - `local`
- New backend settings:
  - `ARTIFACT_STORAGE_BACKEND=local`
  - `ARTIFACT_URL_TTL_SECONDS=3600`
- Centralized artifact behaviors:
  - public file URL construction;
  - artifact existence and size checks;
  - storage backend metadata on manifest artifact entries;
  - safe resolution of `/files/{path}`;
  - path escape protection through the existing `DATA_DIR` guard.
- `/providers` now reports artifact storage metadata.
- `/stats` now reports artifact storage metadata.
- Project manifest artifact entries now include `storage_backend`.
- Backend test covers:
  - public URL generation;
  - artifact entry metadata;
  - path escape blocking.

## Verified

- Targeted artifact test added and included in full backend suite.

## Still Not Production-Complete

- The only implemented backend is still local filesystem storage.
- S3/R2/GCS upload/download adapters are not implemented yet.
- Signed URLs are not implemented yet.
- Artifact lifecycle/retention policies are not implemented yet.
- Private artifact access audit events are not implemented yet.
- Existing generated files are still written locally by render/voice/visual services.

## Next Storage Step

Implement an S3-compatible adapter behind `ArtifactStore`:

- upload generated files after each pipeline step;
- store object keys in project artifacts;
- return signed URLs instead of `/files/{path}`;
- preserve local backend for development and tests.
