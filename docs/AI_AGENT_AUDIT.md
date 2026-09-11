# AI Agent implementation and integration audit

Audit date: 2026-08-29 (Asia/Shanghai)

## Decision

Decision: **approve the integrated Agent candidate for publication to `main`**.

The candidate is based on public `main` commit `fb5ff5f` and integrates the
Agent implementation plus the pre-integration audit fixes. The newer GitHub
and local-Git Connectors remain present and covered by their original tests.
Publication is allowed only as a fast-forward from the audited remote head.

This decision upgrades only these facts: the source contains a runnable Agent
engineering loop, it is reproducible without an API key, and the packaged
artifact passes the recorded regression suite. It does not upgrade any live
model, accuracy, production, cost, latency, or user-outcome claim.

## Source audit

Verified in the integrated candidate:

- Two real HTTP code paths exist: OpenAI-compatible Chat Completions and the
  OpenAI Responses API. They share bounded retry, timeout, request-ID, usage,
  and configured cost-estimate instrumentation.
- Responses runs with `store=false` and requests
  `reasoning.encrypted_content`; returned response items are checkpointed for
  stateless replay without storing plaintext hidden reasoning.
- API credentials are read from a configured environment variable at request
  time and are not serialized into config, messages, checkpoints, or reports.
- Strict JSON Schema output is requested from the Provider and validated again
  locally with Pydantic before a workflow can complete.
- `search_experiences`, `get_experience`, and `get_evidence_stats` are real,
  read-only Tools over the local Experience store. Tool arguments reject extra
  or out-of-range fields before execution.
- The workflow atomically checkpoints model turns and Tool results. Completed
  Tool `call_id` values are not re-executed during resume.
- Citation IDs must refer to records loaded by `get_experience`, and evidence
  locations must exist verbatim on those loaded records.
- Shareable reports omit questions, model output, and Tool result content.
- Eval case IDs reject path traversal, duplicate IDs are rejected, resume
  rejects Provider/model mismatches, and the packaged dataset has a tested
  SHA-256 provenance manifest.
- GitHub import and local repository analysis remain registered in the CLI;
  the integration did not delete or replace either Connector.

## Test, Demo, and packaging audit

Executed against the integrated source on Python 3.12:

- `ruff check .`: passed for the full repository, including
  `scripts/sync_issues.py`.
- Full test suite: **180 passed**.
- Focused AI/Agent/CLI/GitHub/local-Git regression selection: passed.
- Offline source Demo: completed with the three expected Tools, a durable
  checkpoint, locally validated output, grounded evidence, and a sanitized
  report.
- Recorded source eval: **9/9 expectations passed**; Tool sequence, Schema,
  grounding, task completion, and recovery were all 100% on this deterministic
  fixture set.
- Wheel build: passed. Inspection confirmed that both Connector modules, all
  Agent modules, `eval_cases.jsonl`, and `eval_manifest.json` are packaged.
- Fresh virtual environment installation outside the repository: passed.
  The installed CLI reported version 0.1.0, passed the bundled 9/9 eval, and
  completed the installed 3-Tool recorded Demo.
- Missing-key check: `ai check` exited before network I/O with the configured
  environment-variable guidance.
- Committed secret-prefix scan: no OpenAI or GitHub token-shaped value found.

The CI definition now repeats Ruff and the test matrix and adds a dedicated
wheel build plus installed-wheel eval job. This audit does not claim that the
new remote CI run passed before publication; it records the local execution
above.

## Evaluation and data provenance audit

`evals/manifest.json` is the source-of-truth disclosure. Its SHA-256 matches
`evals/experience_brief.jsonl`. The current dataset contains:

- 9 AI-assisted synthetic cases with 7 synthetic Experience records;
- 3 expected pause/failure cases and 1 checkpoint/resume recovery case;
- exact Tool sequence, status, content, and grounding expectations;
- placeholder evidence locations only;
- no real user records, personal data, or external source records;
- no independent human review.

Recorded 9/9 is therefore a deterministic workflow regression result, not
model accuracy, representative task performance, or production evidence. A
stronger result requires representative human-labelled sanitized cases and an
actual `ai eval --live` run.

## Remaining boundaries

- No API key was available, so no real OpenAI request was executed and no live
  latency, token, retry, request-ID, or cost result is published.
- Tool recovery is idempotent for the current read-only Tools; it is not an
  exactly-once protocol for future external side-effecting Tools.
- Grounding proves citation reference integrity, not semantic entailment of
  every sentence in the generated answer.
- RAG, MCP, Streaming, production deployment, and real user outcomes are not
  implemented or evidenced.
- `interview`, `enrich`, and `config set/get/list` remain separate unfinished
  roadmap work; the Evidence Brief Workflow must not be presented as those
  features.
