"""Unified command line entry point for EOAT release and deployment orchestration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from deployment.common import DeploymentError, redact_text, to_jsonable

from .models import DeploymentState
from .services import ReleaseDeploymentService


def _print(value: Any, as_json: bool) -> None:
    payload = to_jsonable(value)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if isinstance(payload, dict) and {"status", "summary", "next_safe_action"} <= set(payload):
        print(f"{payload['status']}: {payload['summary']}")
        print(f"Next safe action: {payload['next_safe_action']}")
        for diagnostic in payload.get("diagnostics", []):
            print(f"- {diagnostic['status']} {diagnostic['name']}: {diagnostic['detail']}")
        return
    print(json.dumps(payload, indent=2, sort_keys=True))


def _candidate_commands(commands: argparse._SubParsersAction[Any]) -> None:
    candidate = commands.add_parser("candidate", help="Prepare, inspect, or discard immutable candidates")
    actions = candidate.add_subparsers(dest="candidate_command", required=True)
    for name, help_text in (
        ("rehearse", "Validate a disposable candidate without retained state"),
        ("prepare", "Persist a validated immutable candidate"),
    ):
        child = actions.add_parser(name, help=help_text)
        versions = child.add_mutually_exclusive_group(required=True)
        versions.add_argument("--bump", choices=("patch", "minor", "major"))
        versions.add_argument("--version", dest="explicit_version")
    actions.add_parser("list", help="List retained candidates")
    show = actions.add_parser("show", help="Show one retained candidate")
    show.add_argument("candidate_id")
    discard = actions.add_parser("discard", help="Discard an unpromoted candidate")
    discard.add_argument("candidate_id")


def _publish_commands(commands: argparse._SubParsersAction[Any]) -> None:
    publish = commands.add_parser("publish", help="Start, resume, or inspect immutable publication")
    actions = publish.add_subparsers(dest="publish_command", required=True)
    start = actions.add_parser("start", help="Publish a validated candidate")
    start.add_argument("candidate_id")
    start.add_argument("--confirm-version", required=True)
    resume = actions.add_parser("resume", help="Reconcile and resume a publication")
    resume.add_argument("publication_id")
    status = actions.add_parser("status", help="Show publication receipt")
    status.add_argument("publication_id")


def _target_plan_deploy_commands(commands: argparse._SubParsersAction[Any]) -> None:
    target = commands.add_parser("target", help="Explicit read-only test-target diagnostics")
    actions = target.add_subparsers(dest="target_command", required=True)
    inspect = actions.add_parser("inspect", help="Inspect a non-production test target")
    inspect.add_argument("--server-config", type=Path, required=True)
    status = actions.add_parser("status", help="Show a stored target inspection")
    status.add_argument("--inspection", required=True)

    plan = commands.add_parser("plan", help="Create deployment plans from stored release and inspection facts")
    actions = plan.add_subparsers(dest="plan_command", required=True)
    create = actions.add_parser("create", help="Create a plan")
    create.add_argument("--release", required=True)
    create.add_argument("--inspection", required=True)
    show = actions.add_parser("show", help="Show a stored plan")
    show.add_argument("plan_id")

    deploy = commands.add_parser("deploy", help="State-aware deployment transaction controls")
    actions = deploy.add_subparsers(dest="deploy_command", required=True)
    stage = actions.add_parser("stage", help="Initialize a transaction; no mutation")
    stage.add_argument("--plan", required=True)
    stage.add_argument("--confirm-version", required=True)
    for name, state, text in (
        ("approve-migration", DeploymentState.MIGRATION_APPROVED, "Approve a migration transaction"),
        ("activate", DeploymentState.ACTIVATION_STARTED, "Begin activation"),
        ("abort", DeploymentState.ABORTED, "Abort an unactivated transaction"),
        ("rollback-application", DeploymentState.ROLLBACK_STARTED, "Begin application rollback"),
        ("restore-database", DeploymentState.DATABASE_RESTORE_STARTED, "Begin database recovery"),
        ("verify-recovery", DeploymentState.RECOVERY_VALIDATED, "Verify recovery"),
    ):
        child = actions.add_parser(name, help=text)
        child.add_argument("--transaction", required=True)
        child.set_defaults(target_state=state)
        if state in {
            DeploymentState.MIGRATION_APPROVED,
            DeploymentState.ACTIVATION_STARTED,
            DeploymentState.ROLLBACK_STARTED,
            DeploymentState.DATABASE_RESTORE_STARTED,
        }:
            child.add_argument("--confirm", required=True)
    status = actions.add_parser("status", help="Show transaction status")
    status.add_argument("--transaction", required=True)
    recover = actions.add_parser("recover", help="Show transaction recovery state")
    recover.add_argument("--transaction", required=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EOAT Atlas unified release and deployment console CLI")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2], help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", dest="as_json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Show candidate readiness")
    commands.add_parser("diagnose", help="Show candidate readiness diagnostics")
    _candidate_commands(commands)
    _publish_commands(commands)
    releases = commands.add_parser("releases", help="Release inventory and verification")
    release_actions = releases.add_subparsers(dest="release_command", required=True)
    release_actions.add_parser("list", help="List all GitHub releases and eligibility")
    for name, help_text in (
        ("inspect", "Show verified release receipt"),
        ("verify", "Download and fully verify a release"),
    ):
        child = release_actions.add_parser(name, help=help_text)
        child.add_argument("--version", required=True)
    _target_plan_deploy_commands(commands)
    receipts = commands.add_parser("receipts", help="Browse and export durable receipts")
    receipt_actions = receipts.add_subparsers(dest="receipt_command", required=True)
    receipt_actions.add_parser("list", help="List all receipt inventories")
    show = receipt_actions.add_parser("show", help="Show a receipt")
    show.add_argument("receipt_id")
    export = receipt_actions.add_parser("export", help="Export human-readable receipt")
    export.add_argument("receipt_id")
    export.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    service = ReleaseDeploymentService(args.root)
    try:
        if args.command in {"status", "diagnose"}:
            result = service.status()
        elif args.command == "candidate":
            if args.candidate_command == "rehearse":
                result = service.rehearse_candidate(args.bump, args.explicit_version)
            elif args.candidate_command == "prepare":
                result = service.prepare_candidate(args.bump, args.explicit_version)
            elif args.candidate_command == "list":
                result = service.candidates()
            elif args.candidate_command == "show":
                result = service.receipt(args.candidate_id)
            else:
                result = service.discard_candidate(args.candidate_id)
        elif args.command == "publish":
            if args.publish_command == "start":
                result = service.publish_start(args.candidate_id, args.confirm_version)
            elif args.publish_command == "resume":
                result = service.publish_resume(args.publication_id)
            else:
                result = service.publication(args.publication_id)
        elif args.command == "releases":
            if args.release_command == "list":
                result = service.inventory()
            elif args.release_command == "verify":
                result = service.verify_release(args.version)
            else:
                result = service.receipt(f"release-{args.version}")
        elif args.command == "target":
            result = (
                service.inspect_target(args.server_config)
                if args.target_command == "inspect"
                else service.receipt(args.inspection)
            )
        elif args.command == "plan":
            result = (
                service.create_plan(args.release, args.inspection)
                if args.plan_command == "create"
                else service.plan(args.plan_id)
            )
        elif args.command == "deploy":
            if args.deploy_command == "stage":
                result = service.begin_transaction(args.plan, args.confirm_version)
            elif args.deploy_command in {"status", "recover"}:
                result = service.transaction(args.transaction)
            else:
                result = service.transition_transaction(
                    args.transaction, args.target_state, getattr(args, "confirm", None)
                )
        elif args.receipt_command == "list":
            result = service.receipts()
        elif args.receipt_command == "show":
            result = service.receipt(args.receipt_id)
        else:
            result = service.export_receipt(args.receipt_id, args.output)
        _print(result, args.as_json)
        return 0 if not hasattr(result, "status") or result.status.value not in {"BLOCKED", "UNKNOWN"} else 2
    except (DeploymentError, OSError, ValueError) as exc:
        print(f"ERROR: {redact_text(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
