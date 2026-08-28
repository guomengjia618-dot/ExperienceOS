# AI Agent implementation audit

Audit date: 2026-08-28 (Asia/Shanghai)

## Scope

This audit covers the local Agent candidate based on commit `d7d39aa`, the
post-commit audit fixes in the same working tree, the current public `main`
snapshot at `fb5ff5f`, and the evaluation dataset under `evals/`.

## Source audit

Verified in the local candidate:

- API credentials are read from a configured environment variable and are not
  serialized into config, messages, checkpoints, or reports.
- Chat Completions and Responses API Adapters share bounded retry, timeout,
  request-ID, usage, and cost-estimate instrumentation.
- Structured output is requested with JSON Schema and validated locally with
  Pydantic before completion.
- The three Tools are read-only and validate arguments before touching the
  local store.
- Workflow checkpoints use atomic replacement. Completed Tool `call_id` values
  are not executed again during resume.
- Citation IDs and evidence locations must come from records loaded by
  `get_experience`.
- Shareable run reports omit questions, model answers, and Tool results.

Audit fixes added before the merge decision:

- Eval case IDs now reject path separators/traversal, and duplicate case IDs
  are rejected before execution.
- Resume now rejects a different Provider or model, preventing incompatible
  Chat/Responses replay and incorrect report attribution.
- The packaged eval dataset now includes a machine-readable provenance
  manifest with a tested SHA-256 digest.

Boundaries that remain:

- Tool recovery is idempotent for the three current read-only Tools. It is not
  an exactly-once protocol for future external side-effecting Tools.
- Citation grounding currently proves reference integrity (loaded record and
  valid evidence location), not semantic entailment of every natural-language
  claim.
- No live API call, production deployment, RAG, MCP, Streaming, or user-outcome
  evidence exists in this audit.

## Test and packaging audit

- `ruff check .`: passed.
- Full local test suite: 142 passed on Python 3.12.
- Focused AI/Agent coverage includes both Provider payloads, strict schema,
  429/5xx classification, bounded timeout/network retry, Tool argument errors,
  grounding rejection, duplicate Tool-call idempotency, checkpoint/resume,
  report redaction, unsafe eval IDs, duplicate eval IDs, and manifest integrity.
- Wheel build: passed.
- Installed-wheel smoke test, run outside the repository: 9/9 recorded
  expectations passed using the dataset bundled inside the wheel.
- Current public `main` snapshot `fb5ff5f`: Ruff passed and its full test suite
  passed independently before integration.

Not tested: a real OpenAI request. `OPENAI_API_KEY` was absent, and `ai check`
correctly stopped before network I/O.

## Evaluation and data provenance audit

`evals/manifest.json` is the source-of-truth disclosure. The current dataset is:

- 9 AI-assisted synthetic cases containing 7 synthetic Experience records;
- 3 expected pause/failure cases and 1 checkpoint/resume recovery case;
- placeholder evidence locations only;
- free of real user records and personal data;
- not independently human reviewed;
- intended for deterministic workflow regression and small live smoke runs.

Therefore, recorded 9/9 is not model accuracy, representative task accuracy,
or production performance. A stronger claim requires human-labelled,
representative real or sanitized cases plus an actual `--live` run.

## Merge and factual-status decision

Decision: **do not merge the local Agent commit directly into public `main` yet**.

The public branch advanced from the common commit `c9d0cd8` to `fb5ff5f` with
the docs sync script, CLI path fix, GitHub importer, and local Git analyzer.
A dry applicability check found conflicts in `README.md`,
`docs/ARCHITECTURE.md`, `src/experienceos/cli/app.py`, and
`scripts/sync_issues.py`. The script already exists remotely, so it should not
be re-added by the Agent change.

Required integration gate:

1. Rebase or cherry-pick the Agent changes onto current public `main`.
2. Preserve the newer GitHub and local-Git connector code and documentation.
3. Resolve the four conflicts and exclude the redundant script addition.
4. Rerun full Ruff, tests, recorded eval, wheel build, and installed-wheel smoke.
5. Only then publish the Agent implementation.

Allowed factual status now: local implementation and offline verification.
Disallowed upgrades: public availability of the Agent, real-model completion,
model accuracy, representative eval coverage, real latency/tokens/cost, and
production or user outcomes.
