# Job worker execution foundation

Date: 2026-06-19

## What changed

- Added `EXECUTE_JOBS_IN_API=true|false`.
- When `EXECUTE_JOBS_IN_API=false`, the API creates queued jobs but does not submit them to the in-process `ThreadPoolExecutor`.
- Added `backend/job_worker.py` to drain queued jobs outside the API process.
- Added a `worker` service to `docker-compose.yml`.
- `/diagnostics` and `/providers` now expose whether jobs execute inside the API process.

## Local mode

Default development behavior is unchanged:

```env
RUN_JOBS_INLINE=false
EXECUTE_JOBS_IN_API=true
JOB_STORAGE_BACKEND=local
```

## Production split

Production compose now runs the API and worker as separate services:

```env
RUN_JOBS_INLINE=false
EXECUTE_JOBS_IN_API=false
JOB_STORAGE_BACKEND=postgres
```

The worker runs:

```powershell
python backend\job_worker.py --poll-interval 5 --limit 1
```

For automatic HeyGen avatar polling:

```powershell
python backend\job_worker.py --auto-avatar-sync --poll-interval 10 --limit 2
```

Or enable it through environment:

```env
AVATAR_AUTO_SYNC_ENABLED=true
AVATAR_AUTO_SYNC_INTERVAL_SECONDS=60
AVATAR_AUTO_RENDER_AFTER_SYNC=true
```

`auto-avatar-sync` only queues `sync_avatar` for projects that already have HeyGen `avatar_video_id` values and missing local MP4 files. It does not create new HeyGen avatar jobs. When all avatar MP4s, scene visuals and scene audio are ready, `AVATAR_AUTO_RENDER_AFTER_SYNC=true` lets the `sync_avatar` job run `render` automatically.

For a single polling pass:

```powershell
python backend\job_worker.py --once
```

## Current limits

- This is a separate worker process foundation, not Redis/Celery/Temporal yet.
- There is no atomic multi-worker lease with expiration yet.
- There is no dead-letter queue or retry backoff policy yet.
- Already running long FFmpeg/provider steps remain cooperative and cannot be force-cancelled mid-step.
