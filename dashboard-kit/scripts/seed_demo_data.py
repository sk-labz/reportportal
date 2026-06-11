#!/usr/bin/env python3
"""Seed sample launch data into a ReportPortal project for trying out the
dashboard kit's dashboards with real-looking data.

NOT part of the production dashboard-kit -- a convenience script for local
verification/demos (referenced from the sandbox testing notes). Generates a
handful of launches across 4 "suites" (api/ui/integration/unit), each tagged
with team/layer/service/version attributes per ci-examples/ATTRIBUTES.md, with
a mix of passed/failed/skipped items so the dashboards have data to show.

Usage:
    python3 scripts/seed_demo_data.py --project demo_checkout --team checkout
    python3 scripts/seed_demo_data.py --project demo_overview --team checkout
    python3 scripts/seed_demo_data.py --project demo_overview --team fraud
"""

import argparse
import os
import random
import sys
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from provision_dashboards import RPClient  # noqa: E402

LAUNCHES = [
    {"name": "Checkout API Tests", "layer": "api", "service": "checkout-api"},
    {"name": "Checkout UI Regression", "layer": "ui", "service": "checkout-web"},
    {"name": "Checkout Integration Suite", "layer": "integration", "service": "checkout-api"},
    {"name": "Checkout Unit Tests", "layer": "unit", "service": "checkout-api"},
]

ITEM_NAMES = [
    "test_login",
    "test_add_to_cart",
    "test_apply_coupon",
    "test_checkout_flow",
    "test_payment_decline",
]


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def seed(client, team, runs_per_launch):
    now = datetime.utcnow()
    for i, launch_def in enumerate(LAUNCHES):
        for run in range(runs_per_launch):
            start = now - timedelta(days=(runs_per_launch - run) * 2, hours=i)
            launch_uuid = str(uuid.uuid4())
            version = f"2026.06.{run + 1}"
            attrs = [
                {"key": "team", "value": team},
                {"key": "layer", "value": launch_def["layer"]},
                {"key": "service", "value": launch_def["service"]},
                {"key": "version", "value": version},
            ]
            client.post("/launch", json={
                "name": launch_def["name"],
                "startTime": iso(start),
                "uuid": launch_uuid,
                "attributes": attrs,
            })

            t = start
            statuses = []
            for item_name in ITEM_NAMES:
                t += timedelta(seconds=random.randint(2, 8))
                item_uuid = str(uuid.uuid4())
                client.post("/item", json={
                    "name": item_name,
                    "startTime": iso(t),
                    "type": "STEP",
                    "launchUuid": launch_uuid,
                    "uuid": item_uuid,
                    "hasStats": True,
                })

                roll = random.random()
                if item_name == "test_payment_decline" and run % 2 == 0:
                    status = "FAILED"  # deterministic flakiness for the Flaky Test Cases widgets
                elif roll < 0.08:
                    status = "FAILED"
                elif roll < 0.12:
                    status = "SKIPPED"
                else:
                    status = "PASSED"
                statuses.append(status)

                t += timedelta(seconds=random.randint(1, 5))
                client.put(f"/item/{item_uuid}", json={
                    "endTime": iso(t),
                    "status": status,
                    "launchUuid": launch_uuid,
                })

            launch_status = "FAILED" if "FAILED" in statuses else "PASSED"
            t += timedelta(seconds=2)
            client.put(f"/launch/{launch_uuid}/finish", json={"endTime": iso(t), "status": launch_status})
            print(f"  seeded '{launch_def['name']}' run {run + 1}/{runs_per_launch} "
                  f"-> {launch_status} attrs={attrs} items={statuses}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-url", default=os.environ.get("RP_API_URL"))
    ap.add_argument("--token", default=os.environ.get("RP_API_TOKEN"))
    ap.add_argument("--project", required=True)
    ap.add_argument("--team", default="checkout", help="Value for the 'team' launch attribute")
    ap.add_argument("--runs-per-launch", type=int, default=3,
                     help="How many historical runs to generate per launch name (default: 3)")
    args = ap.parse_args()

    if not args.api_url or not args.token:
        sys.exit("error: --api-url/--token or RP_API_URL/RP_API_TOKEN are required")

    client = RPClient(args.api_url, args.token, args.project)
    print(f"Seeding '{args.project}' (team={args.team}, {args.runs_per_launch} runs/launch)...")
    seed(client, args.team, args.runs_per_launch)
    print("Done.")


if __name__ == "__main__":
    main()
