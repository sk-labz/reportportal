#!/usr/bin/env python3
"""Configure per-project Jira (BTS) integrations in ReportPortal.

⚠️ UNVERIFIED AGAINST A LIVE INSTANCE. This script encodes a best-effort
guess at RP's BTS integration endpoint and payload shape, based on
dashboard-kit/docs/JIRA_INTEGRATION.md and RP's plugin documentation. Before
any non-dry-run execution:

  1. Run with --dry-run and read the printed request.
  2. Open https://<RP_DOMAIN>/api/ (Swagger UI) -> "Integration" controller
     and compare the path/body against what this script sends.
  3. If they don't match, either adjust JIRA_INTEGRATION_PATH /
     build_integration_payload() below, or fall back to the Admin UI flow
     described in dashboard-kit/docs/JIRA_INTEGRATION.md sections 2-4.

Reads dashboard-kit/config/jira.yml (see config/jira.example.yml). Credentials
are read from environment variables named in jira.yml (api_token_env /
password_env), never stored in the YAML itself.

Usage:
    python3 configure_bts_jira.py --dry-run
    python3 configure_bts_jira.py
    python3 configure_bts_jira.py --project payments_checkout
"""

import argparse
import os
import sys
from pathlib import Path

import yaml

from provision_dashboards import RPClient, extract_list, find_by_name

CONFIG_DIR = Path(__file__).resolve().parent / "config"

# VERIFY: the integration endpoint. Candidates seen in RP's API across
# versions: "/integration/jira", "/integration", or a plugin-specific path
# like "/integration/BTS/jira". This script uses "/integration" with a
# "pluginName" field in the body, which matches RP's generic
# "create project integration" pattern most closely -- but confirm.
JIRA_INTEGRATION_PATH = "/integration"


def build_integration_payload(project_cfg):
    """Best-effort BTS integration payload. VERIFY field names (see module docstring)."""
    auth_type = project_cfg.get("auth_type", "cloud")
    params = {
        "url": project_cfg["bts_url"],
        "project": project_cfg["bts_project"],
    }

    if auth_type == "cloud":
        token_env = project_cfg["api_token_env"]
        token = os.environ.get(token_env)
        if not token:
            sys.exit(f"error: env var {token_env} (referenced by config/jira.yml) is not set")
        params.update({
            "authType": "API_TOKEN",
            "email": project_cfg["email"],
            "token": token,
        })
    elif auth_type == "server":
        password_env = project_cfg["password_env"]
        password = os.environ.get(password_env)
        if not password:
            sys.exit(f"error: env var {password_env} (referenced by config/jira.yml) is not set")
        params.update({
            "authType": "BASIC",
            "username": project_cfg["username"],
            "password": password,
        })
    else:
        sys.exit(f"error: unknown auth_type '{auth_type}' for project '{project_cfg['key']}' (expected cloud|server)")

    return {
        "enabled": True,
        "pluginName": "jira",
        "integrationParameters": params,
    }


def ensure_jira_integration(client, project_cfg, force):
    name = project_cfg["key"]
    payload = build_integration_payload(project_cfg)

    existing = extract_list(client.get(JIRA_INTEGRATION_PATH, params={"page.size": 50}))
    found = find_by_name([{"name": i.get("pluginName"), "id": i.get("id")} for i in existing], "jira")

    if found and not force:
        print(f"  jira integration exists (id={found.get('id')}) - reusing (pass --force to update)")
        return
    if found and force:
        print(f"  jira integration exists (id={found.get('id')}) - updating (--force)")
        client.put(f"{JIRA_INTEGRATION_PATH}/{found['id']}", json=payload)
        return

    print(f"  creating jira integration for project '{name}' -> {project_cfg['bts_project']}")
    client.post(JIRA_INTEGRATION_PATH, json=payload)


def load_projects(jira_config_path):
    with open(jira_config_path) as f:
        data = yaml.safe_load(f) or {}
    projects = data.get("projects")
    if not projects:
        sys.exit(f"error: {jira_config_path} has no 'projects' entries")
    return projects


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", default=os.environ.get("RP_API_URL"))
    parser.add_argument("--token", default=os.environ.get("RP_API_TOKEN"))
    parser.add_argument("--jira-config", default=str(CONFIG_DIR / "jira.yml"))
    parser.add_argument("--project", help="Configure a single project key from jira.yml instead of all of them")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Update an existing Jira integration in place")
    args = parser.parse_args()

    if not args.api_url:
        sys.exit("error: --api-url or RP_API_URL is required")
    if not args.token:
        sys.exit("error: --token or RP_API_TOKEN is required")

    if not Path(args.jira_config).exists():
        sys.exit(
            f"error: {args.jira_config} not found.\n"
            f"Copy config/jira.example.yml to config/jira.yml and edit it -- "
            f"see dashboard-kit/docs/JIRA_INTEGRATION.md."
        )

    projects = load_projects(args.jira_config)
    if args.project:
        projects = [p for p in projects if p["key"] == args.project]
        if not projects:
            sys.exit(f"error: project '{args.project}' not found in {args.jira_config}")

    for project_cfg in projects:
        client = RPClient(args.api_url, args.token, project_cfg["key"], dry_run=args.dry_run)
        print(f"\n=== Project '{project_cfg['key']}' ===")
        ensure_jira_integration(client, project_cfg, force=args.force)

    print("\nDone." + (" (dry run - no changes were made)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
