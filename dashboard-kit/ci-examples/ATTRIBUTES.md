# Launch attribute tagging convention

Every CI job that reports to ReportPortal should tag its launch with three
attributes. These drive the **Team / Project Comparison** and **Org Quality
Overview** dashboards (`componentHealthCheck` widgets group by them) and will
also be useful for Jira linkage in Phase 2.

| Attribute key | Required | Example values                  | Used by                                   |
|---------------|----------|----------------------------------|--------------------------------------------|
| `team`        | yes      | `checkout`, `search`, `fraud`    | Umbrella "Org Quality Overview" grouping    |
| `layer`       | yes      | `api`, `ui`, `integration`, `unit` | Filtering/segmentation within a project   |
| `service`     | recommended | `checkout-api`, `checkout-web` | "Team / Project Comparison" `componentHealthCheck` |

Rules of thumb:
- Keys and values: lowercase, no spaces, hyphen-separated if multi-word
  (e.g. `service:order-service`).
- `team` should match the team name used in `dashboard-kit/config/teams.yml`
  under an umbrella project's `teams:` list, so the per-team drill-down
  filter (`Team: <name>`) lines up.
- `layer` should be one of `api | ui | integration | unit` to keep the
  convention consistent across dashboards company-wide.

## Repository secrets every onboarded repo needs

| Secret           | Value                                                        |
|-------------------|--------------------------------------------------------------|
| `RP_ENDPOINT`     | `https://<RP_DOMAIN>/api/v1` (or `/api/v2` per agent docs)   |
| `RP_API_KEY`      | Project- or service-account API token (Bearer)              |
| `RP_PROJECT`      | The team's ReportPortal project key, e.g. `payments_checkout` |

`RP_LAUNCH` (the launch *name* shown in the UI, e.g. "Checkout API Tests") is
typically not a secret — set it as a plain workflow env var.

## ⚠️ VERIFY per agent/version

The exact **property/env var name and format** for launch attributes differs
across ReportPortal client/agent versions and ecosystems:

- Java (`client-java` / `agent-java-junit5` / `agent-java-testng`): typically
  `rp.attributes=key:value;key2:value2` in `reportportal.properties`
  (or `RP_ATTRIBUTES` as an env var override, depending on client-java
  version). Newer client-java versions use `rp.api.key` instead of `rp.uuid`
  for the token property name.
- Python (`pytest-reportportal`): typically `rp_launch_attributes = key:value
  key2:value2` (space-separated) in `pytest.ini`/`pyproject.toml`.
- JS (`@reportportal/agent-js-jest`, `@reportportal/agent-js-cypress`):
  typically an `attributes: [{ "key": "...", "value": "..." }, ...]` array in
  the reporter's JS config object.

Each example workflow in this directory flags the exact line(s) to confirm
against that agent's current README before relying on it in production.
