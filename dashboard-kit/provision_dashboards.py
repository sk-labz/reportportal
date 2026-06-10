#!/usr/bin/env python3
"""Provision the ReportPortal Dashboard Kit (filters, widgets, dashboards).

Reads JSON templates from config/{filters,widgets,dashboards}/ and a
config/teams.yml describing which projects to provision (see
config/teams.example.yml), then creates or updates the corresponding
filters/widgets/dashboards in ReportPortal via its REST API.

IMPORTANT: Several field names below (filter `filteringField` tokens, widget
`widgetType`/`widgetOptions` keys, list-endpoint response shapes) are flagged
as "VERIFY" in both this file and the JSON templates under config/. Confirm
them against the target instance's Swagger UI (https://<RP_DOMAIN>/api/) for
your ReportPortal version before relying on a non-dry-run execution. See
dashboard-kit/README.md for details.

Usage:
    python3 provision_dashboards.py --dry-run
    python3 provision_dashboards.py
    python3 provision_dashboards.py --project payments_checkout --mode team
    python3 provision_dashboards.py --project payments_overview --mode umbrella \\
        --group-by-attribute team --teams checkout,fraud
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests
import yaml

CONFIG_DIR = Path(__file__).resolve().parent / "config"

# (dashboard template, widget-set template) pairs provisioned into every project.
TEAM_DASHBOARDS = [
    ("dashboards/dashboard_pass_fail_trends.json", "widgets/overall_pass_fail_trends.json"),
    ("dashboards/dashboard_failure_defect_breakdown.json", "widgets/failure_defect_breakdown.json"),
    ("dashboards/dashboard_team_comparison.json", "widgets/team_project_comparison.json"),
]

# Additional pairs provisioned only for projects with mode: umbrella.
UMBRELLA_DASHBOARDS = [
    ("dashboards/dashboard_umbrella_overview.json", "widgets/umbrella_component_health.json"),
]

# Filters shared by every TEAM_DASHBOARDS widget set, keyed by the "name"
# field used inside the widget templates' "filter" attribute.
FILTER_FILES = {
    "Last 50 Launches": "filters/filter_last_50_launches.json",
    "Launches With Failures (recent)": "filters/filter_failed_last_14_days.json",
}

# Per-team drill-down filter, only created for mode: umbrella projects.
TEAM_FILTER_FILE = "filters/filter_by_team_attribute.json"

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
    """RP list endpoints return either a bare array or {"content": [...]}.

    VERIFY which shape your instance uses for /filter, /widget, /dashboard.
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
    """Thin wrapper around the ReportPortal v1 project API.

    base = {api_url}/v1/{project}, e.g. https://rp.example.com/api/v1/payments_checkout
    """

    def __init__(self, api_url, token, project, dry_run=False):
        self.project = project
        self.base = f"{api_url.rstrip('/')}/v1/{project}"
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.dry_run = dry_run

    def _request(self, method, path, **kwargs):
        url = f"{self.base}{path}"
        if self.dry_run and method in ("POST", "PUT", "DELETE"):
            body = json.dumps(kwargs.get("json", {}))
            print(f"  [dry-run] {method} {url}\n            body: {body}")
            return None
        resp = self.session.request(method, url, timeout=30, **kwargs)
        if not resp.ok:
            raise RuntimeError(f"{method} {url} -> {resp.status_code}: {resp.text[:1000]}")
        return resp.json() if resp.content else None

    def get(self, path, **kwargs):
        return self._request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self._request("POST", path, **kwargs)

    def put(self, path, **kwargs):
        return self._request("PUT", path, **kwargs)


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


def ensure_widget(client, widget_def, filter_id, force):
    """GET-by-name, then POST (create) or PUT (update if --force).

    Returns (widget_id, size) where size is the {"width","height"} layout hint.
    """
    name = widget_def["name"]
    size = widget_def.get("size", DEFAULT_WIDGET_SIZE)
    payload = {
        "name": name,
        "description": widget_def.get("description", ""),
        "widgetType": widget_def["widgetType"],
        "filterIds": [filter_id],
        "contentParameters": widget_def["contentParameters"],
        "share": True,
    }

    existing = extract_list(client.get("/widget", params={"filter.eq.name": name, "page.size": 50}))
    found = find_by_name(existing, name)

    if found and not force:
        print(f"  widget '{name}' exists (id={found.get('id')}) - reusing")
        return found["id"], size
    if found and force:
        print(f"  widget '{name}' exists (id={found.get('id')}) - updating (--force)")
        client.put(f"/widget/{found['id']}", json=payload)
        return found["id"], size

    print(f"  creating widget '{name}' ({widget_def['widgetType']})")
    result = client.post("/widget", json=payload)
    widget_id = f"DRYRUN-WIDGET-{name}" if client.dry_run else result["id"]
    return widget_id, size


def ensure_dashboard(client, dashboard_def, widgets):
    """GET-by-name, then POST (create) the dashboard, then PUT/add any missing widgets.

    `widgets` is a list of (widget_id, size) tuples in display order. Existing
    widgets already attached to the dashboard are left untouched (idempotent);
    new ones are appended in a 12-column grid, stacking rows as needed.
    """
    name = dashboard_def["name"]
    existing = extract_list(client.get("/dashboard", params={"page.size": 100}))
    found = find_by_name(existing, name)

    if found:
        dashboard_id = found["id"]
        print(f"  dashboard '{name}' exists (id={dashboard_id}) - reusing")
        details = client.get(f"/dashboard/{dashboard_id}") or {}
        existing_widget_ids = {w.get("widgetId") for w in details.get("widgets", [])}
        cursor_y = max(
            (w.get("widgetPosition", {}).get("positionY", 0) + w.get("widgetSize", {}).get("height", 0)
             for w in details.get("widgets", [])),
            default=0,
        )
    else:
        print(f"  creating dashboard '{name}'")
        result = client.post(
            "/dashboard",
            json={"name": name, "description": dashboard_def.get("description", ""), "share": True},
        )
        dashboard_id = f"DRYRUN-DASHBOARD-{name}" if client.dry_run else result["id"]
        existing_widget_ids = set()
        cursor_y = 0

    cursor_x, row_height = 0, 0
    for widget_id, size in widgets:
        if widget_id in existing_widget_ids:
            print(f"    widget {widget_id} already on dashboard - skipping add")
            continue
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


def provision_project(client, mode, group_by_attribute, team_names, force):
    print(f"\n=== Project '{client.project}' (mode={mode}) ===")

    filter_ids = {}
    for fname, relpath in FILTER_FILES.items():
        fdef = strip_comments(load_json(relpath))
        filter_ids[fname] = ensure_filter(client, fdef, force)

    dashboard_groups = list(TEAM_DASHBOARDS)
    if mode == "umbrella":
        dashboard_groups += UMBRELLA_DASHBOARDS
        for team in team_names or []:
            tdef = render(strip_comments(load_json(TEAM_FILTER_FILE)), {"TEAM": team})
            ensure_filter(client, tdef, force)

    for dashboard_path, widgets_path in dashboard_groups:
        ddef = strip_comments(load_json(dashboard_path))
        wdefs = strip_comments(load_json(widgets_path))["widgets"]

        if mode == "umbrella" and group_by_attribute:
            wdefs = render(wdefs, {"GROUP_BY_ATTRIBUTE": group_by_attribute})

        widgets = []
        for wdef in wdefs:
            filter_id = filter_ids.get(wdef["filter"])
            if filter_id is None:
                raise KeyError(
                    f"Widget '{wdef['name']}' references unregistered filter '{wdef['filter']}' "
                    f"-- add it to FILTER_FILES in provision_dashboards.py"
                )
            widgets.append(ensure_widget(client, wdef, filter_id, force))

        ensure_dashboard(client, ddef, widgets)


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
        provision_project(
            client,
            mode=project.get("mode", "team"),
            group_by_attribute=project.get("group_by_attribute"),
            team_names=project.get("teams"),
            force=args.force,
        )

    print("\nDone." + (" (dry run - no changes were made)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
