# Managed Auth / OIDC Foundation Update - 2026-06-19

This update closes the first practical slice of the production backlog item "managed auth/OIDC".

## Implemented

- Optional OIDC/JWKS bearer token verification.
- Existing local register/login/session auth remains available.
- If local session lookup fails and OIDC is enabled, backend validates the bearer token as an OIDC JWT.
- JWT validation checks:
  - issuer;
  - audience;
  - signature through JWKS;
  - algorithm allowlist;
  - required `exp`, `iat`, `iss`, and `sub` claims.
- External OIDC identity maps to a stable internal user id:
  - `user_<sha256(issuer:subject)[:12]>`
- OIDC users are upserted into the existing local user profile store.
- Personal organization is created automatically for first-time OIDC users.
- Existing project ownership, organizations/RBAC, usage quotas, consent, billing, and audit logic continue to use the internal `user_*` id.
- `/providers` and `/diagnostics` expose OIDC configuration metadata.

## Settings

```text
ENABLE_USER_AUTH=true
OIDC_ENABLED=true
OIDC_ISSUER_URL=https://issuer.example.com
OIDC_AUDIENCE=your-api-audience
OIDC_JWKS_URL=https://issuer.example.com/.well-known/jwks.json
OIDC_ALGORITHMS=RS256
OIDC_EMAIL_CLAIM=email
OIDC_NAME_CLAIM=name
```

## Supported Providers

Any provider that issues JWT access tokens or ID tokens with a JWKS endpoint can be used, including Auth0, Clerk, Supabase Auth, Cognito, Azure AD, Google Identity, Keycloak, and similar OIDC providers.

## Still Not Production-Complete

- Local users/sessions are still file-backed unless a future auth storage migration is added.
- There is no OIDC group/role claim mapping yet.
- There is no SCIM/user lifecycle sync yet.
- There is no organization auto-linking by domain/tenant claim yet.
- Logout/revocation for OIDC tokens remains provider-side.
- Production should ensure `OIDC_AUDIENCE` matches the API audience, not a frontend client id unless the provider documents that flow.
