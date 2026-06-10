# Launch attribute tagging convention

Every CI job that reports to ReportPortal should tag its launch with three
attributes. These drive the **Team / Project Comparison** and **Org Quality
Overview** dashboards (`componentHealthCheck` widgets group by them) and will
also be useful for Jira linkage in Phase 2.

| Attribute key | Required | Example values                  | Used by                                   |
|---------------|----------|----------------------------------|--------------------------------------------|
| `team`        | yes      | `checkout`, `search`, `fraud`    | Umbrella "Org Quality Overview" grouping    |
| `layer`       | yes      | `api`, `ui`, `integration`, `unit` | "Test Layer Breakdown" `componentHealthCheck`, filtering/segmentation within a project |
| `service`     | recommended | `checkout-api`, `checkout-web` | "Team / Project Comparison" `componentHealthCheck` |
| `version` (or `build`) | optional | `2026.06.1`, `build:4821` | "Release / Sprint Report" dashboard |

Rules of thumb:
- Keys and values: lowercase, no spaces, hyphen-separated if multi-word
  (e.g. `service:order-service`).
- `team` should match the team name used in `dashboard-kit/config/teams.yml`
  under an umbrella project's `teams:` list, so the per-team drill-down
  filter (`Team: <name>`) lines up.
- `layer` should be one of `api | ui | integration | unit` to keep the
  convention consistent across dashboards company-wide.
- `version`/`build` is optional but unlocks the **Release / Sprint Report**
  dashboard (`dashboard-kit/config/dashboards/dashboard_release_sprint_report.json`),
  which scopes its widgets to the most recent launches carrying this
  attribute. Use whichever key matches your release process (`version:2026.06.1`
  for versioned releases, `build:4821` for CI build numbers); set the
  matching `build_attribute_key` in `config/teams.yml` for that project (see
  `config/teams.example.yml`).

## Onboarded frameworks

| Framework                  | Layer(s)              | Example workflow                              |
|-----------------------------|------------------------|-----------------------------------------------|
| JUnit5 (Maven)              | unit / integration     | `java-junit5-reportportal.yml`                |
| TestNG (Maven)              | ui / integration       | `java-testng-reportportal.yml`                |
| pytest                      | unit                    | `python-pytest-reportportal.yml`              |
| Jest                        | unit                    | `js-jest-reportportal.yml`                    |
| Cypress                     | ui                      | `js-cypress-reportportal.yml`                 |
| Postman / Newman            | api                     | `postman-newman-reportportal.yml`             |
| Playwright                  | ui                      | `playwright-reportportal.yml`                 |
| .NET (NUnit)                | unit / integration      | `dotnet-nunit-reportportal.yml`               |
| Robot Framework             | integration             | `robotframework-reportportal.yml`             |

Don't see your framework? Check the [ReportPortal agents list](https://github.com/reportportal?q=agent-) —
most follow the same pattern: install the agent, configure
endpoint/token/project/launch + the `team`/`layer`/`service` (and optionally
`version`/`build`) attributes per this convention, and add the secrets from
the table below.

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
