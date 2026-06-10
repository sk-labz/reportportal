# SSO Setup (SAML / LDAP / Active Directory)

This is the Phase 2 implementation of the SSO item from `PHASE2_ROADMAP.md`.
It's written so it can be followed as soon as you have IdP details in hand —
nothing here requires code changes beyond the optional
`docker-compose.sso.yml` overlay.

> **Where this configuration lives:** unlike the dashboard kit, RP's
> authorization providers (SAML, LDAP, Active Directory, OAuth) are
> configured through the **Admin UI** (Administrate → Authorization
> Configuration) and stored in the database — not via environment variables
> or compose files. `docker-compose.sso.yml` adds the one exception
> (`RP_AUTH_SAML_ENTITYID`, the SAML SP entity ID) and is otherwise
> documentation. No `uat` restart is needed after UI-based configuration
> changes (only when applying the compose overlay itself).

## 0. Apply the SSO overlay (optional, SAML only)

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.sso.yml \
  --profile core up -d
```

This sets `RP_AUTH_SAML_ENTITYID` on the `uat` service to
`https://<RP_DOMAIN>` so IdP admins have a stable entity ID to register.
Skip this step if you're only configuring LDAP/Active Directory.

## 1. SAML

### 1a. Generic steps (any IdP)

1. Log in to RP as `superadmin` → **Administrate → Authorization
   Configuration → SAML**.
2. ReportPortal's SP metadata is at:
   ```
   https://<RP_DOMAIN>/uat/saml/sp/SSO/alias/report-portal-sp
   ```
   Provide this URL (or the entity ID set via `RP_AUTH_SAML_ENTITYID`) to
   your IdP admin.
3. Add a new SAML provider in RP with:
   - **Identity provider name ID** / **Provider name**: a short label
     shown on the RP login page (e.g. `Company SSO`).
   - **Metadata URL** (or upload the IdP's metadata XML).
   - **RP callback URL**: `https://<RP_DOMAIN>/uat/saml/sp/SSO/alias/report-portal-sp`
4. **Attribute mapping** — the IdP must send these claims (exact claim
   names depend on the IdP, mapped in RP's SAML config form):
   - `email` → RP `Email` (required, used as the unique user identifier)
   - `firstName` → RP `FirstName`
   - `lastName` → RP `LastName`
5. **JIT (just-in-time) provisioning**: enabled by default for SAML — a new
   RP user is created on first SSO login. **Caveat**: if an internal RP user
   already exists with the same email but a different login, JIT
   provisioning will fail for that user — pre-audit for email collisions
   before rollout (especially for any admin/service accounts created during
   Phase 1).

### 1b. Okta SAML specifics

Reference: https://reportportal.io/docs/reportportal-configuration/authorization/SAMLProvider/OktaSAML/

- In Okta: create a new SAML 2.0 app integration.
  - **Single sign-on URL**: `https://<RP_DOMAIN>/uat/saml/sp/SSO/alias/report-portal-sp`
  - **Audience URI (SP Entity ID)**: same as `RP_AUTH_SAML_ENTITYID`
    (`https://<RP_DOMAIN>` if using the overlay above).
  - **Attribute statements**: map `email`, `firstName`, `lastName` from Okta
    user profile attributes.
- In RP: use Okta's metadata URL (Okta app → Sign On → "Identity Provider
  metadata" link) as the **Metadata URL**.

### 1c. Azure AD SAML specifics

Reference: https://reportportal.io/docs/plugins/authorization/SamlProviders/AzureSaml/

- In Azure AD: create an Enterprise Application → Single sign-on → SAML.
  - **Identifier (Entity ID)**: `RP_AUTH_SAML_ENTITYID` value.
  - **Reply URL (ACS URL)**: `https://<RP_DOMAIN>/uat/saml/sp/SSO/alias/report-portal-sp`
  - **Attributes & claims**: Azure AD's default claim names differ from
    RP's expected `email`/`firstName`/`lastName` — add custom claims (or
    edit the existing ones) to emit those exact names.
- In RP: use the "App Federation Metadata Url" from Azure AD's SAML setup
  page as the **Metadata URL**.

## 2. LDAP

Reference: https://reportportal.io/docs/plugins/authorization/

1. **Administrate → Authorization Configuration → LDAP**.
2. Required fields:
   - **URL**: e.g. `ldaps://ldap.example.com:636`
   - **Base DN**: e.g. `dc=example,dc=com`
   - **User DN pattern** or **User search filter**: how RP finds a user by
     login (e.g. `(&(objectClass=person)(uid={0}))`)
   - **Manager DN / password**: a bind account with read access, if
     anonymous bind isn't allowed.
   - **Email attribute**, **Full name attribute** (and optionally **Photo
     attribute**).
3. Submit. Users authenticate with their directory login/password; RP
   creates accounts on first login (JIT, same caveat as SAML re: email
   collisions).

## 3. Active Directory

Reference: https://reportportal.io/docs/plugins/authorization/ActiveDirectory/

1. **Administrate → Authorization Configuration → Active Directory**.
2. Required fields: **Domain**, **URL** (e.g. `ldap://ad.example.com:389`),
   **Base DN**, **Email attribute**. Optional: **Full name attribute**,
   **Photo attribute**, **User search filter** (same syntax as LDAP).
3. Submit. **All AD users in the configured domain/base DN gain access to
   RP** — there's no group-based allow-list at this layer. Restrict via RP
   project membership (step 4) instead.

## 4. Role / project mapping

RP project access is independent of the SSO provider — JIT-provisioned users
land with whatever default role your instance is configured for, and must
still be added to each project (or an org-level role) to see its dashboards.
Use this table (fill in for your org) to plan the mapping from IdP
groups/teams to the projects defined in `dashboard-kit/config/teams.yml`:

| IdP group              | RP project(s)        | RP project role |
|-------------------------|------------------------|------------------|
| `team-checkout`          | `payments_checkout`   | Member            |
| `team-fraud`             | `payments_fraud`      | Member            |
| `qa-leads`               | all team projects      | Project Admin     |
| `exec-stakeholders`      | `payments_overview` (umbrella) | Viewer  |

For instances without a "viewer can see all projects" setting, consider
adding `exec-stakeholders` (or equivalent) to every project at Viewer level
so the "switch project, same dashboards" experience from
`dashboard-kit/README.md` works for them too.

## 5. Rollout checklist

- [ ] Apply `docker-compose.sso.yml` if using SAML.
- [ ] Configure the chosen provider(s) via Admin UI (sections 1–3).
- [ ] Audit existing internal accounts for email collisions with the IdP
      (JIT provisioning caveat).
- [ ] Map IdP groups to RP projects/roles (section 4) for every project in
      `dashboard-kit/config/teams.yml`.
- [ ] Pilot with one team before disabling internal-account login
      (Administrate → Authorization Configuration → toggle internal auth).
- [ ] Communicate the new login flow + SSO URL to all teams.
