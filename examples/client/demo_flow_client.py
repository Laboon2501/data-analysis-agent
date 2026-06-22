"""Small API-client demo flow for local direct analysis and export confirmation."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from examples.client.minimal_client import (
    DEFAULT_BASE_URL,
    DataAnalysisAPIClient,
    artifact_id_from_ref,
    extract_artifact_refs_from_job,
    human_request_from_job,
)


def run_demo_flow(settings: argparse.Namespace) -> dict[str, Any]:
    """Run direct analysis, report outline, and one confirm export through the API."""

    client = DataAnalysisAPIClient(base_url=settings.base_url)
    direct_job = _submit_and_wait(
        client,
        session_id=settings.session_id,
        message=settings.analysis_message,
        command="none",
    )
    final_state = direct_job.get("final_state") or {}
    analysis_package = final_state.get("analysis_package")
    if analysis_package is None:
        raise RuntimeError("Direct analysis did not return analysis_package.")

    report_job = _submit_and_wait(
        client,
        session_id=settings.session_id,
        message=settings.report_message,
        command="report",
        analysis_package=analysis_package,
    )
    human_request = human_request_from_job(report_job)
    if human_request is None:
        raise RuntimeError("Report flow did not return a human_request.")
    report_outline_summary = _job_summary(client, report_job)

    approved_job = client.approve(report_job["job_id"], settings.confirm_command)
    approved_job = client.wait_for_job(approved_job["job_id"])
    artifact_refs = _collect_refs(direct_job, report_job, approved_job)
    downloads = [_download_summary(client, artifact_ref) for artifact_ref in artifact_refs]
    return {
        "direct_analysis": _job_summary(client, direct_job),
        "report_outline": {
            **report_outline_summary,
            "approve_hint": _approve_hint_for_command(report_job, settings.confirm_command),
        },
        "confirmed_export": _job_summary(client, approved_job),
        "artifact_refs": artifact_refs,
        "downloads": downloads,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse demo flow client arguments."""

    parser = argparse.ArgumentParser(description="Run a minimal API client demo flow.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--session-id", default="client-demo-flow")
    parser.add_argument("--analysis-message", default="Show monthly GMV trend")
    parser.add_argument("--report-message", default="Export this analysis")
    parser.add_argument(
        "--confirm-command",
        choices=("report_confirm", "ppt_confirm", "excel_confirm", "dashboard_confirm"),
        default="excel_confirm",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for the local API demo flow."""

    print(json.dumps(run_demo_flow(parse_args(argv)), indent=2, sort_keys=True, default=str))
    return 0


def _submit_and_wait(
    client: DataAnalysisAPIClient,
    *,
    session_id: str,
    message: str,
    command: str,
    analysis_package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit a job and wait for its terminal status."""

    job = client.post_chat(
        session_id=session_id,
        message=message,
        command=command,
        analysis_package=analysis_package,
    )
    return client.wait_for_job(job["job_id"])


def _job_summary(client: DataAnalysisAPIClient, job: dict[str, Any]) -> dict[str, Any]:
    """Return a compact job summary with event names."""

    events = client.list_events(job["job_id"])
    return {
        "job_id": job["job_id"],
        "status": job.get("status"),
        "intent": job.get("intent"),
        "command": job.get("command"),
        "final_response_text": job.get("final_response_text"),
        "error_message": job.get("error_message"),
        "event_types": [event.get("event_type") for event in events],
        "artifact_refs": extract_artifact_refs_from_job(job),
    }


def _approve_hint_for_command(job: dict[str, Any], confirm_command: str) -> str:
    """Return an approve hint that reflects the command used by this demo run."""

    return f"client.approve({job['job_id']!r}, {confirm_command!r})"


def _collect_refs(*jobs: dict[str, Any]) -> list[str]:
    """Collect artifact refs from several job responses."""

    refs: list[str] = []
    for job in jobs:
        refs.extend(extract_artifact_refs_from_job(job))
    output: list[str] = []
    for ref in refs:
        if ref not in output:
            output.append(ref)
    return output


def _download_summary(client: DataAnalysisAPIClient, artifact_ref: str) -> dict[str, Any]:
    """Download one artifact and report metadata plus byte size only."""

    download = client.download_artifact(artifact_ref)
    return {
        "artifact_ref": download.artifact_ref,
        "artifact_id": artifact_id_from_ref(download.artifact_ref),
        "mime_type": download.metadata.get("mime_type"),
        "metadata_keys": sorted(download.metadata.get("metadata", {}).keys()),
        "content_bytes": len(download.content),
    }


if __name__ == "__main__":
    raise SystemExit(main())
