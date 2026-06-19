# S3/R2 Artifact Storage Update - 2026-06-19

This update extends artifact storage from local-only URLs to an S3-compatible object storage backend.

## Implemented

- New backend:
  - `ARTIFACT_STORAGE_BACKEND=s3`
- New S3/R2 settings:
  - `S3_BUCKET`
  - `S3_REGION`
  - `S3_ENDPOINT_URL`
  - `S3_ACCESS_KEY_ID`
  - `S3_SECRET_ACCESS_KEY`
  - `S3_PREFIX`
  - `S3_PUBLIC_BASE_URL`
- Runtime dependency:
  - `boto3`
- `ArtifactStore` now supports:
  - local FastAPI `/files/...` URLs;
  - S3-compatible uploads through boto3;
  - presigned `get_object` URLs;
  - public CDN/base URLs when `S3_PUBLIC_BASE_URL` is configured;
  - S3 object keys in artifact manifest entries.
- R2/MinIO compatibility is supported through `S3_ENDPOINT_URL`.
- Existing local filesystem backend remains the default for development and tests.

## How To Enable

```text
ARTIFACT_STORAGE_BACKEND=s3
S3_BUCKET=your-bucket
S3_REGION=auto
S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_PREFIX=ai-video-studio
```

If the bucket is public behind a CDN/custom domain:

```text
S3_PUBLIC_BASE_URL=https://cdn.example.com
```

If `S3_PUBLIC_BASE_URL` is empty, backend returns presigned URLs with TTL from `ARTIFACT_URL_TTL_SECONDS`.

## Current Behavior

- Render/voice/visual services still write generated files to local `DATA_DIR`.
- When artifact entries are built for result/manifest responses, local files are uploaded to S3 and the response returns the object URL.
- Unsafe paths outside `DATA_DIR` are still rejected before upload.

## Still Not Production-Complete

- Upload should eventually move directly into generation steps instead of happening during artifact manifest materialization.
- There is no object lifecycle/retention policy automation yet.
- There is no private artifact access audit event yet.
- There is no GCS-native adapter yet.
