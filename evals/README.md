# Evidence brief evaluation set

The nine JSONL cases contain human-authored synthetic Experience records,
exact expected Tool sequences, grounding requirements, status/error expectations,
output terms, and deterministic recorded model turns. They exercise the same Tool
dispatcher, checkpoints, structured output schema, recovery path, and grounding
guard used by a live model.

Recorded 9/9 means deterministic regression expectations passed. It is not model
accuracy. Use representative or sanitized real cases plus `--live` before reporting
model performance.

Run the reproducible suite:

    experienceos ai eval --report eval-report.json

Run the same cases against the configured real model API:

    experienceos ai eval --live
