# Artifact Storage Foundation Update - 2026-06-19

This update closes the first practical slice of the production backlog item "object storage instead of local files".

## Implemented

- Artifact access abstraction in `backend/app/services/artifact_store.py`.
- Backends:
  - `local`
  - `s3`
- New backend settings:
  - `ARTIFACT_STORAGE_BACKEND=local`
  - `ARTIFACT_STORAGE_BACKEND=s3`
  - `ARTIFACT_URL_TTL_SECONDS=3600`
  - `S3_BUCKET`
  - `S3_REGION`
  - `S3_ENDPOINT_URL`
  - `S3_ACCESS_KEY_ID`
  - `S3_SECRET_ACCESS_KEY`
  - `S3_PREFIX`
  - `S3_PUBLIC_BASE_URL`
- Centralized artifact behaviors:
  - public file URL construction;
  - artifact existence and size checks;
  - storage backend metadata on manifest artifact entries;
  - S3/R2-compatible upload through boto3;
  - public or presigned object URLs;
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

- GCS-native adapter is not implemented yet.
- Artifact lifecycle/retention policies are not implemented yet.
- Private artifact access audit events are not implemented yet.
- Existing generated files are still written locally by render/voice/visual services.
- S3 upload currently happens when artifact entries are materialized by result/manifest responses.

## Next Storage Step

Move upload calls closer to render/voice/visual generation steps and add lifecycle policies for generated objects.
