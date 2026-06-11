#!/usr/bin/env python3
"""Provision the ReportPortal Dashboard Kit (filters, widgets, dashboards).

Reads JSON templates from config/{filters,widgets,dashboards}/ and a
config/teams.yml describing which projects to provision (see
config/teams.example.yml), then creates or updates the corresponding
filters/widgets/dashboards in ReportPortal via its REST API.

This script (request/response shapes for filters, widgets, dashboards, and
project creation) has been validated end-to-end against a live RP 5.15.x
instance. A few data-level details remain environment-specific and are
flagged as "VERIFY" inline: the `statistics$defects$<type>$total` sub-type
tokens (Project Settings -> Defect Types is per-project configurable), and
whether `compositeAttribute` filter conditions ("ex"/"has") behave as
expected once real launches with attributes exist. See
dashboard-kit/README.md for details.

Usage:
    python3 provision_dashboards.py --dry-run
    python3 provision_dashboards.py
    python3 provision_dashboards.py --list-existing

    python3 provision_dashboards.py --project payments_checkout --mode team
    python3 provision_dashboards.py --project payments_overview --mode umbrella \\
        --group-by-attribute team --teams checkout,fraud
    python3 provision_dashboards.py --project payments_checkout --create-project \\
        --project-description "Checkout team test results"
    python3 provision_dashboards.py --project payments_checkout --no-extended-dashboards
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests
import yaml

CONFIG_DIR = Path(__file__).resolve().parent / "config"

# (dashboard template, widget-set template) pairs provisioned into every
# project, regardless of mode. These are the Phase 1 "core" dashboards.
STANDARD_DASHBOARDS = [
    ("dashboards/dashboard_pass_fail_trends.json", "widgets/overall_pass_fail_trends.json"),
    ("dashboards/dashboard_failure_defect_breakdown.json", "widgets/failure_defect_breakdown.json"),
    ("dashboards/dashboard_team_comparison.json", "widgets/team_project_comparison.json"),
]

# Additional pairs provisioned for every project unless a teams.yml entry
# sets `extended_dashboards: false` (or --no-extended-dashboards is passed
# with --project). Added in Phase 2.
EXTENDED_DASHBOARDS = [
    ("dashboards/dashboard_test_layer_breakdown.json", "widgets/test_layer_breakdown.json"),
    ("dashboards/dashboard_release_sprint_report.json", "widgets/release_sprint_report.json"),
    ("dashboards/dashboard_duration_flakiness_trends.json", "widgets/duration_flakiness_trends.json"),
]

# Additional pairs provisioned only for projects with mode: umbrella.
UMBRELLA_DASHBOARDS = [
    ("dashboards/dashboard_umbrella_overview.json", "widgets/umbrella_component_health.json"),
]

# Filters shared by every STANDARD_DASHBOARDS widget set, keyed by the "name"
# field used inside the widget templates' "filter" attribute.
FILTER_FILES = {
    "Last 50 Launches": "filters/filter_last_50_launches.json",
    "Launches With Failures (recent)": "filters/filter_failed_last_14_days.json",
}

# Per-team drill-down filter, only created for mode: umbrella projects.
TEAM_FILTER_FILE = "filters/filter_by_team_attribute.json"

# Templated filter used by EXTENDED_DASHBOARDS' "Release / Sprint Report"
# widgets. Rendered once per project with BUILD_ATTRIBUTE_KEY (see
# `provision_project`); its rendered "name" becomes the filter_ids key those
# widgets look up.
BUILD_FILTER_FILE = "filters/filter_by_build_attribute.json"

DEFAULT_WIDGET_SIZE = {"width": 6, "height": 8}


def strip_comments(obj):
    """Recursively drop "_comment" keys used as inline documentation."""
    if isinstance(obj, dict):
        return {k: strip_comments(v) for k, v in obj.items() if k != "_comment"}
    if isinstance(obj, list):
        return [strip_comments(v) for v in obj]
    return obj


def load_json(relative_path):
    with open(CONFIG_DIR / relative_path) as f:
        return json.load(f)


def render(obj, context):
    """Substitute {{PLACEHOLDER}} tokens throughout a JSON-able structure."""
    text = json.dumps(obj)
    for key, value in context.items():
        text = text.replace("{{%s}}" % key, value)
    return json.loads(text)


def extract_list(resp):
    """RP list endpoints return {"content": [...], "page": {...}}.

    `content` may hold objects (filters, dashboards) or plain strings
    (/widget/names/all) -- both are returned as-is.
    """
    if resp is None:
        return []
    if isinstance(resp, list):
        return resp
    return resp.get("content", [])


def find_by_name(items, name):
    for item in items:
        if item.get("name") == name:
            return item
    return None


class RPClient:
    """Thin wrapper around the ReportPortal v1 API.

    api_base = {api_url}/v1, e.g. https://rp.example.com/api/v1
    base     = {api_base}/{project}, e.g. .../v1/payments_checkout

    get/post/put are relative to `base` (project-scoped endpoints). Project
    existence/creation uses `api_base` directly (instance-scoped endpoints).
    """

    def __init__(self, api_url, token, project, dry_run=False):
        self.project = project
        self.api_base = f"{api_url.rstrip('/')}/v1"
        self.base = f"{self.api_base}/{project}"
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.dry_run = dry_run

    def _request(self, method, url, **kwargs):
        if self.dry_run and method in ("POST", "PUT", "DELETE"):
            body = json.dumps(kwargs.get("json", {}))
            print(f"  [dry-run] {method} {url}\n            body: {body}")
            return None
        resp = self.session.request(method, url, timeout=30, **kwargs)
        if not resp.ok:
            raise RuntimeError(f"{method} {url} -> {resp.status_code}: {resp.text[:1000]}")
        return resp.json() if resp.content else None

    def get(self, path, **kwargs):
        return self._request("GET", f"{self.base}{path}", **kwargs)

    def post(self, path, **kwargs):
        return self._request("POST", f"{self.base}{path}", **kwargs)

    def put(self, path, **kwargs):
        return self._request("PUT", f"{self.base}{path}", **kwargs)

    def project_exists(self):
        """CONFIRMED: GET {api_base}/project/{name} -> 200 (exists) / 404 (not found).

        Read-only call, performed even under --dry-run.
        """
        url = f"{self.api_base}/project/{self.project}"
        resp = self.session.get(url, timeout=30)
        if resp.status_code == 200:
            return True
        if resp.status_code == 404:
            return False
        raise RuntimeError(f"GET {url} -> {resp.status_code}: {resp.text[:500]}")

    def create_project(self, description=""):
        """CONFIRMED: POST {api_base}/project with projectName/entryType/configuration.description -> 201 {"id": N}."""
        payload = {
            "projectName": self.project,
            "entryType": "INTERNAL",
            "configuration": {"description": description},
        }
        return self._request("POST", f"{self.api_base}/project", json=payload)


def ensure_project_exists(client, create, description):
    """If `create` is set, create the project when it doesn't already exist."""
    if not create:
        return
    if client.project_exists():
        print(f"  project '{client.project}' exists - reusing")
        return
    print(f"  creating project '{client.project}'")
    client.create_project(description)


def list_existing(client):
    """--list-existing audit mode: print existing filters/dashboards (with
    their attached widgets) and known widget names.

    Read-only (uses client.get only); does not create or modify anything.
    Useful for sanity-checking a fresh provisioning run, and as a starting
    point for the future dashboard-cleanup tooling described in
    docs/PHASE2_ROADMAP.md.

    NOTE: RP has no "list all widgets with IDs" endpoint
    (GET /v1/{project}/widget is 405; /widget/names/all returns names only,
    no IDs -- see the Dashboards section below for widget IDs).
    """
    print(f"\n=== Project '{client.project}': existing items ===")

    filters = extract_list(client.get("/filter", params={"page.size": 300}))
    print(f"  Filters ({len(filters)}):")
    for f in filters:
        print(f"    id={f.get('id')!s:<8} name={f.get('name')!r}")

    dashboards = extract_list(client.get("/dashboard", params={"page.size": 300}))
    print(f"  Dashboards ({len(dashboards)}):")
    for db in dashboards:
        print(f"    id={db.get('id')!s:<8} name={db.get('name')!r}")
        details = client.get(f"/dashboard/{db['id']}") or {}
        for w in details.get("widgets", []):
            print(f"        widget id={w.get('widgetId')!s:<8} name={w.get('widgetName')!r} type={w.get('widgetType')}")

    widget_names = extract_list(client.get("/widget/names/all", params={"page.size": 300}))
    print(f"  Widget names known to project ({len(widget_names)}, IDs not exposed by this endpoint):")
    for wn in widget_names:
        print(f"    {wn!r}")


def ensure_filter(client, filter_def, force):
    """GET-by-name, then POST (create) or PUT (update if --force). Returns the filter id."""
    name = filter_def["name"]
    existing = extract_list(client.get("/filter", params={"filter.eq.name": name, "page.size": 50}))
    found = find_by_name(existing, name)

    if found and not force:
        print(f"  filter '{name}' exists (id={found.get('id')}) - reusing")
        return found["id"]
    if found and force:
        print(f"  filter '{name}' exists (id={found.get('id')}) - updating (--force)")
        client.put(f"/filter/{found['id']}", json=filter_def)
        return found["id"]

    print(f"  creating filter '{name}'")
    result = client.post("/filter", json=filter_def)
    return f"DRYRUN-FILTER-{name}" if client.dry_run else result["id"]


def ensure_dashboard_with_widgets(client, dashboard_def, widget_defs, filter_ids, force):
    """GET-or-create the dashboard, then create-or-reuse+attach each widget.

    Widget identity/reuse is determined by what's already attached to THIS
    dashboard (matched by `widgetName`) -- RP has no "get widget id by name"
    endpoint outside of a dashboard's widget list (GET /v1/{project}/widget
    is 405; /widget/names/all returns names only, without IDs). New widgets
    are created and appended in a 12-column grid, stacking rows as needed,
    starting below any existing widgets.
    """
    name = dashboard_def["name"]
    existing = extract_list(client.get("/dashboard", params={"filter.eq.name": name, "page.size": 50}))
    found = find_by_name(existing, name)

    if found:
        dashboard_id = found["id"]
        print(f"  dashboard '{name}' exists (id={dashboard_id}) - reusing")
        details = client.get(f"/dashboard/{dashboard_id}") or {}
        existing_widgets = details.get("widgets", [])
    else:
        print(f"  creating dashboard '{name}'")
        result = client.post("/dashboard", json={"name": name, "description": dashboard_def.get("description", "")})
        dashboard_id = f"DRYRUN-DASHBOARD-{name}" if client.dry_run else result["id"]
        existing_widgets = []

    existing_by_name = {w.get("widgetName"): w for w in existing_widgets}
    cursor_y = max(
        (w.get("widgetPosition", {}).get("positionY", 0) + w.get("widgetSize", {}).get("height", 0)
         for w in existing_widgets),
        default=0,
    )
    cursor_x, row_height = 0, 0

    for wdef in widget_defs:
        wname = wdef["name"]
        size = wdef.get("size", DEFAULT_WIDGET_SIZE)
        filter_id = filter_ids.get(wdef["filter"])
        if filter_id is None:
            raise KeyError(
                f"Widget '{wname}' references unregistered filter '{wdef['filter']}' "
                f"-- add it to FILTER_FILES (or BUILD_FILTER_FILE) in provision_dashboards.py"
            )
        payload = {
            "name": wname,
            "description": wdef.get("description", ""),
            "widgetType": wdef["widgetType"],
            "filterIds": [filter_id],
            "contentParameters": wdef["contentParameters"],
        }

        existing_widget = existing_by_name.get(wname)
        if existing_widget:
            widget_id = existing_widget["widgetId"]
            if force:
                print(f"    widget '{wname}' on dashboard (id={widget_id}) - updating (--force)")
                client.put(f"/widget/{widget_id}", json=payload)
            else:
                print(f"    widget '{wname}' already on dashboard (id={widget_id}) - reusing")
            continue

        print(f"    creating widget '{wname}' ({wdef['widgetType']})")
        result = client.post("/widget", json=payload)
        widget_id = f"DRYRUN-WIDGET-{wname}" if client.dry_run else result["id"]

        width = size.get("width", DEFAULT_WIDGET_SIZE["width"])
        height = size.get("height", DEFAULT_WIDGET_SIZE["height"])
        if cursor_x + width > 12:
            cursor_x = 0
            cursor_y += row_height
            row_height = 0
        print(f"    adding widget {widget_id} at ({cursor_x},{cursor_y}) size {width}x{height}")
        client.put(
            f"/dashboard/{dashboard_id}/add",
            json={
                "addWidget": {
                    "widgetId": widget_id,
                    "widgetSize": {"width": width, "height": height},
                    "widgetPosition": {"positionX": cursor_x, "positionY": cursor_y},
                }
            },
        )
        cursor_x += width
        row_height = max(row_height, height)

    return dashboard_id


def provision_project(client, mode, group_by_attribute, team_names, extended_dashboards, build_attribute_key, force):
    print(f"\n=== Project '{client.project}' (mode={mode}, extended_dashboards={extended_dashboards}) ===")

    # Context for {{PLACEHOLDER}} substitution. BUILD_ATTRIBUTE_KEY is always
    # set (defaults to "version"); GROUP_BY_ATTRIBUTE is only meaningful for
    # mode: umbrella. render() is a no-op for templates without these tokens.
    context = {"BUILD_ATTRIBUTE_KEY": build_attribute_key}
    if mode == "umbrella" and group_by_attribute:
        context["GROUP_BY_ATTRIBUTE"] = group_by_attribute

    filter_ids = {}
    for fname, relpath in FILTER_FILES.items():
        fdef = strip_comments(load_json(relpath))
        filter_ids[fname] = ensure_filter(client, fdef, force)

    dashboard_groups = list(STANDARD_DASHBOARDS)

    if extended_dashboards:
        bdef = render(strip_comments(load_json(BUILD_FILTER_FILE)), context)
        filter_ids[bdef["name"]] = ensure_filter(client, bdef, force)
        dashboard_groups += EXTENDED_DASHBOARDS

    if mode == "umbrella":
        dashboard_groups += UMBRELLA_DASHBOARDS
        for team in team_names or []:
            tdef = render(strip_comments(load_json(TEAM_FILTER_FILE)), {"TEAM": team})
            ensure_filter(client, tdef, force)

    for dashboard_path, widgets_path in dashboard_groups:
        ddef = strip_comments(load_json(dashboard_path))
        wdefs = render(strip_comments(load_json(widgets_path))["widgets"], context)
        ensure_dashboard_with_widgets(client, ddef, wdefs, filter_ids, force)


def load_projects(teams_config_path):
    with open(teams_config_path) as f:
        data = yaml.safe_load(f) or {}
    projects = data.get("projects")
    if not projects:
        sys.exit(f"error: {teams_config_path} has no 'projects' entries")
    return projects


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--api-url", default=os.environ.get("RP_API_URL"),
                         help="e.g. https://reportportal.example.com/api (env: RP_API_URL)")
    parser.add_argument("--token", default=os.environ.get("RP_API_TOKEN"),
                         help="ReportPortal API token, used as a Bearer token (env: RP_API_TOKEN)")
    parser.add_argument("--teams-config", default=str(CONFIG_DIR / "teams.yml"),
                         help="Path to teams.yml (see config/teams.example.yml). Ignored if --project is set.")
    parser.add_argument("--project", help="Provision a single project instead of reading --teams-config")
    parser.add_argument("--mode", choices=["team", "umbrella"], default="team", help="Used with --project")
    parser.add_argument("--group-by-attribute", default="team", help="Used with --project --mode umbrella")
    parser.add_argument("--teams", default="",
                         help="Comma-separated team names for per-team drill-down filters; used with --project --mode umbrella")
    parser.add_argument("--build-attribute-key", default="version",
                         help="Launch attribute key used by the Release/Sprint Report dashboard (default: version)")
    parser.add_argument("--no-extended-dashboards", action="store_true",
                         help="Skip the Phase 2 'extended' dashboards (Test Layer Breakdown, Release/Sprint Report, "
                              "Duration & Flakiness Trends); used with --project")
    parser.add_argument("--create-project", action="store_true",
                         help="Create the project if it doesn't exist (used with --project; "
                              "for --teams-config, set 'create: true' per project instead)")
    parser.add_argument("--project-description", default="",
                         help="Description used when --create-project creates a new project")
    parser.add_argument("--list-existing", action="store_true",
                         help="Read-only audit: list existing filters/dashboards/widgets per project and exit "
                              "(no create/update calls are made)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print the create/update calls that would be made, without sending POST/PUT/DELETE requests. "
                              "Still performs read-only GETs against --api-url to determine what already exists.")
    parser.add_argument("--force", action="store_true",
                         help="Update existing filters/widgets in place if they already exist (default: reuse as-is)")
    args = parser.parse_args()

    if not args.api_url:
        sys.exit("error: --api-url or RP_API_URL is required")
    if not args.token:
        sys.exit("error: --token or RP_API_TOKEN is required (a read-capable token is enough for --dry-run)")

    if args.project:
        projects = [{
            "key": args.project,
            "mode": args.mode,
            "group_by_attribute": args.group_by_attribute,
            "teams": [t.strip() for t in args.teams.split(",") if t.strip()],
            "extended_dashboards": not args.no_extended_dashboards,
            "build_attribute_key": args.build_attribute_key,
            "create": args.create_project,
            "description": args.project_description,
        }]
    else:
        if not Path(args.teams_config).exists():
            sys.exit(
                f"error: {args.teams_config} not found.\n"
                f"Copy config/teams.example.yml to config/teams.yml and edit it with your "
                f"project keys, or pass --project <key> to provision a single project."
            )
        projects = load_projects(args.teams_config)

    for project in projects:
        client = RPClient(args.api_url, args.token, project["key"], dry_run=args.dry_run)

        if args.list_existing:
            list_existing(client)
            continue

        ensure_project_exists(client, project.get("create", False), project.get("description", ""))
        provision_project(
            client,
            mode=project.get("mode", "team"),
            group_by_attribute=project.get("group_by_attribute"),
            team_names=project.get("teams"),
            extended_dashboards=project.get("extended_dashboards", True),
            build_attribute_key=project.get("build_attribute_key", "version"),
            force=args.force,
        )

    print("\nDone." + (" (dry run - no changes were made)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
