# Landing Page Audit Note - 2026-06-19

## What was added

- Static landing page in `landing/index.html`.
- Responsive CSS in `landing/styles.css`.
- Generated dashboard hero asset in `landing/assets/hero-dashboard.png`.
- Local publishing instructions in `landing/README.md`.
- GitHub Pages workflow in `.github/workflows/deploy-landing.yml`.

## Product message

The landing positions the project as `YOUTUBE AI LONG`: an operator-facing AI
video studio for long-form YouTube production. It explains the main workflow:
research, script, voice and avatar preparation, slides, render and publish
handoff.

## Integration message

The page documents the production-facing surfaces already represented in the
codebase: OpenAI, voice/avatar providers, media search, YouTube, PostgreSQL,
S3-compatible object storage, worker queues, OIDC/RBAC and Stripe billing.

## Remaining landing work

- Replace local API links with the deployed backend URL after hosting is chosen.
- Add real screenshots after the backend and mobile client are connected to live
  providers.
- Add analytics only after privacy and consent requirements are finalized.
