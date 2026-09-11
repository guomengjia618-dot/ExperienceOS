"""Runnable end-to-end demo for structured output, tools, and checkpoints."""

from __future__ import annotations

import argparse
from pathlib import Path

from experienceos.ai.demo import build_recorded_demo_provider
from experienceos.ai.factory import create_provider
from experienceos.ai.reporting import save_run_report
from experienceos.ai.tools import ExperienceToolRegistry
from experienceos.ai.workflow import EvidenceBriefWorkflow, WorkflowCheckpointStore
from experienceos.config import load_config, save_config
from experienceos.core.models import Experience
from experienceos.storage import ExperienceStore


def seed_demo(store: ExperienceStore) -> None:
    if store.list_all():
        return
    store.save(
        Experience.new(
            title="Campus Search Engine",
            type="course_project",
            period={"start": "2024-01", "end": "2024-06"},
            description="Built a Chinese document search engine with BM25 ranking.",
            technology=["Python", "BM25"],
            result=["Top-10 hit rate reached 92% on a 200-query evaluation set."],
            evidence=[
                {
                    "kind": "repo",
                    "location": "github.com/example/campus-search",
                    "description": "Demo source and evaluation scripts",
                }
            ],
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Use the configured real model API")
    parser.add_argument("--resume", help="Resume a workflow ID from the demo checkpoint")
    parser.add_argument(
        "--home",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".experienceos-demo",
    )
    args = parser.parse_args()

    args.home.joinpath("experiences").mkdir(parents=True, exist_ok=True)
    if not args.home.joinpath("config.toml").exists():
        save_config(args.home, load_config(args.home))
    store = ExperienceStore(args.home)
    seed_demo(store)
    checkpoints = WorkflowCheckpointStore(args.home)

    if args.live:
        provider = create_provider(load_config(args.home).ai)
    else:
        provider = build_recorded_demo_provider(store)
        if args.resume:
            previous = checkpoints.load(args.resume)
            if any(message.get("tool_calls") for message in previous.messages):
                provider.responses = provider.responses[-1:]

    workflow = EvidenceBriefWorkflow(
        provider=provider,
        tools=ExperienceToolRegistry(store),
        checkpoints=checkpoints,
    )
    state = (
        workflow.resume(args.resume)
        if args.resume
        else workflow.start(
            "Summarize my strongest project, its verified result, and any evidence gaps."
        )
    )
    print(f"workflow={state.workflow_id} status={state.status}")
    print("tools=" + " -> ".join(event.name for event in state.tool_events))
    print(state.output.model_dump_json(indent=2) if state.output else "no output")
    print(f"checkpoint={checkpoints.path_of(state.workflow_id)}")
    report = save_run_report(
        state,
        args.home / "reports" / f"{state.workflow_id}.json",
    )
    print(f"sanitized_report={report}")


if __name__ == "__main__":
    main()
