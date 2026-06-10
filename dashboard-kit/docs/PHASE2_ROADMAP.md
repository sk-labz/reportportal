# Phase 2 Roadmap: SSO, Jira Integration, Dashboard Cleanup

Phase 1 (production hosting + standard dashboards + CI onboarding) and most
of Phase 2 (SSO/Jira scaffolding, extended dashboards, more CI examples,
tooling hardening) are now implemented. This doc tracks what's done, what's
**ready but needs your inputs to execute**, and what's still genuinely
future work.

## SSO (SAML / LDAP / Active Directory) — ready, needs IdP details

**Implemented**: `docker-compose.sso.yml` (SAML SP entity ID overlay) and
`dashboard-kit/docs/SSO_SETUP.md` (step-by-step for SAML — generic/Okta/Azure
AD — LDAP, and Active Directory via the Admin UI, plus a role-mapping table
template).

**What's needed from you to execute**:
- **Identity provider type and details**:
  - SAML: IdP metadata URL/XML.
  - LDAP/Active Directory: server URL, bind DN/credentials, user/group search
    bases and filters.
- **Role/permission mapping**: fill in `SSO_SETUP.md` section 4's table —
  which IdP groups map to which RP project roles, for each project in
  `dashboard-kit/config/teams.yml`.
- An audit of existing internal RP accounts for email collisions with the
  IdP (JIT provisioning caveat, see `SSO_SETUP.md` section 1a).

Once those are in hand, `SSO_SETUP.md` is a direct, no-further-planning
runbook.

## Jira integration (`plugin-bts-jira`) — ready, needs Jira details

**Implemented**: `dashboard-kit/docs/JIRA_INTEGRATION.md` (plugin install,
global-vs-per-project trade-offs, mapping table templates, defect-type →
issue-type mapping) and an optional automation script
`dashboard-kit/configure_bts_jira.py` + `config/jira.example.yml`.

**What's needed from you to execute**:
- Jira instance URL(s) (Cloud or Server/Data Center) and a service-account
  API token/credentials per Jira project.
- Mapping of RP projects (`dashboard-kit/config/teams.yml`) to Jira project
  keys — fill in `JIRA_INTEGRATION.md` section 4's table (and
  `config/jira.yml` if using the automation script).
- Agreement on the defect-type → Jira issue-type mapping
  (`JIRA_INTEGRATION.md` section 5).

⚠️ `configure_bts_jira.py`'s API endpoint/payload is **unverified** against a
live instance — run with `--dry-run` and check against your instance's
Swagger UI first; the manual UI flow in `JIRA_INTEGRATION.md` always works as
a fallback.

## Dashboard cleanup on a live instance — partially implemented

**Implemented**: `provision_dashboards.py --list-existing` (read-only audit
of existing filters/widgets/dashboards per project — added in Phase 2).

**Still future work**, for when this kit is applied to a company's *existing*
RP instance that already has ad-hoc dashboards:

1. Use `--list-existing` to produce the audit output, so stakeholders can
   sign off on what gets removed.
2. Decide per-project: archive (rename with an `[ARCHIVED]` prefix) vs.
   delete outright. Archiving is safer and reversible. A `--archive` mode
   (renaming non-kit dashboards rather than deleting) would be the natural
   next addition to `provision_dashboards.py`.
3. Run `provision_dashboards.py` to lay down the standard + extended kit
   alongside/after cleanup, using `--force` only where intentional updates to
   existing same-named items are wanted.
4. Re-run `--list-existing` afterward to confirm the end state matches the
   intended dashboard kit per `dashboard-kit/README.md`.

## Forward-compatibility notes

- The `team:`/`layer:`/`service:`/`version:` (or `build:`) attribute
  convention (`dashboard-kit/ci-examples/ATTRIBUTES.md`) is designed to also
  work as Jira component/label hints once the BTS integration is configured.
- Per-project access control (today: manual via RP UI, or SSO group mapping
  per `SSO_SETUP.md` section 4) is unaffected by the extended dashboards or
  new CI examples added in Phase 2.
- The umbrella-project pattern (`dashboard-kit/config/teams.yml`,
  `mode: umbrella`) scales to additional business units by adding more
  entries; no script changes required.
- `provision_dashboards.py --create-project` / `create: true` (Phase 2) means
  new team onboarding can go: add an entry to `teams.yml` with `create: true`
  → run the script → project + all dashboards exist → team copies a
  `ci-examples/*.yml` template. No manual "Add Project" click required
  (pending the VERIFY note on the project-creation endpoint).
