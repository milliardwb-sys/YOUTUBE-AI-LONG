# Stripe Billing Foundation Update - 2026-06-19

This update closes the first practical slice of the production backlog item "Stripe subscriptions / billing".

## Implemented

- Stripe Billing foundation using Checkout Sessions for subscriptions.
- Stripe Customer Portal session endpoint for self-service subscription management.
- Stripe webhook endpoint for subscription status updates.
- File-backed local billing account state in `DATA_DIR/_billing`.
- Billing entitlements now feed existing quota checks:
  - free plan uses `USAGE_MAX_PROJECTS_PER_USER` and `USAGE_MAX_ACTIVE_JOBS_PER_USER`;
  - pro plan uses `BILLING_PRO_MAX_PROJECTS` and `BILLING_PRO_MAX_ACTIVE_JOBS`.
- Billing metadata appears in `/providers`, `/diagnostics`, and `/admin/overview`.
- New authenticated endpoints:
  - `GET /billing/me`
  - `POST /billing/checkout`
  - `POST /billing/portal`
- Public Stripe webhook endpoint:
  - `POST /billing/stripe/webhook`
- Stripe SDK dependency:
  - `stripe==15.2.1`
- Default Stripe API version:
  - `2026-02-25.clover`

## How To Enable

```text
STRIPE_API_KEY=...
STRIPE_PRO_PRICE_ID=price_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_SUCCESS_URL=https://app.example.com/billing/success
STRIPE_CANCEL_URL=https://app.example.com/billing/cancel
STRIPE_PORTAL_RETURN_URL=https://app.example.com/billing
BILLING_PRO_MAX_PROJECTS=250
BILLING_PRO_MAX_ACTIVE_JOBS=10
```

If `STRIPE_API_KEY` is empty, billing endpoints still report free entitlements and checkout/portal creation returns `503`.

## Webhook Events Handled

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`

## Still Not Production-Complete

- Billing account state is still file-backed, not PostgreSQL.
- No seat-based billing yet.
- No metered usage reporting to Stripe yet.
- No invoice/payment failure UX yet beyond stored subscription status.
- No admin billing console beyond overview metadata.
- Webhook endpoint is public as required by Stripe, but should be protected with `STRIPE_WEBHOOK_SECRET` in production.
