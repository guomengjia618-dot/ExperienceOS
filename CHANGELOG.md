# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Evidence-brief workflow (#032): a checkpointed model/tool loop — the model
  must *read* records through three read-only tools before making claims;
  citations are validated against evidence loaded during the run; every
  round persists an atomic checkpoint so a paused run resumes exactly where
  it stopped. Provider-neutral (OpenAI-compatible chat and the Responses API
  ship with the box), with sanitized run reports (operational metrics only,
  never prompts) and request metrics with optional per-model cost rates.
- Evaluation harness (#032): `experienceos ai eval` replays a 9-case
  labelled dataset (tool-sequence, schema-validity, citation-grounding and
  expected-content assertions over deterministic recorded turns), writes
  redacted shareable reports, and supports `--live` for real-model runs on
  the same cases. Dataset ships with a signed-sha256 manifest that states
  what the numbers are *not* valid for.
- Local workbench (#033): `experienceos web` serves a zero-dependency
  loopback-only browser UI for browsing experiences, running the brief
  workflow (offline demo mode with synthetic data, or a configured live
  model), inspecting tool-call timelines, and resuming paused runs.
  Hardened by default: Host/Origin/Sec-Fetch-Site checks, strict CSP,
  no request logging, errors kept off the wire.
- Workbench run-history dropdown (#034): replaced the bare `<select>` with
  a custom listbox showing each run's question, status dot (running/
  paused/completed), mode and relative time; keyboard-navigable with
  outside-click/Escape dismissal.

### Changed

- `AIProviderError` now carries sanitized request `metadata`; the AI
  config gained explicit retry-budget and cost-rate fields
  (`ai.timeout_seconds` replaces `ai.timeout`). The layering guard now
  allows ai's read-only tool seam to import storage (downward, acyclic).

## [0.6.0] - 2026-08-30

Architecture-hardening release: a full-codebase review whose findings were
fixed structurally (no special-case patches). Details in
`docs/issues/m5-hardening.md`.

### Added

- Project-files connector (#027): `experienceos import /path/to/folder`
  turns a non-git project directory into one honest draft — title from the
  folder name, description verbatim from the README, languages from the
  shared extension map, explicit undated period, empty contributions.
  Walk safety: junk/build dirs pruned, directory symlinks never followed,
  file-count cap.
- Shared language module `connectors/languages.py` (#027): one curated
  extension→language map now serves both git-repo and project-files.
- Injection protocols (#028): `MaterialDraftExtractor` /
  `AcceptsMaterialExtractor` in `connectors.base`; the AI extraction
  pipeline (`ai.extraction.AIExtraction`) is wired by the composition
  root, so any connector can use AI reading without importing the ai tier.
- Layering guard tests (#028): `tests/test_layering.py` parses every
  module's imports (AST) and fails when a tier reaches where it must not.
- Interview confirmation now includes `evidence` (#030): AI-harvested
  evidence candidates pass the same keep/drop gate as every other field.

### Changed

- **Breaking (internal API)**: `ExperienceDraft` moved to
  `core.draft` (re-exported from `connectors.base`); the material→draft
  pipeline moved from `ai.interview` to `ai.extraction` (names re-exported);
  `ResumeExtractor(provider=..., model=...)` replaced by
  `ResumeExtractor(material_extractor)` / `set_material_extractor()`.
- Unified query path (#029): `services.query_results` is the single
  entry point for CLI and API; the FTS index only pre-filters candidates
  while the in-memory engine always does final filtering and scoring —
  scores and ranking are now identical with and without an index (the
  FTS path previously discarded both).
- `SourceOrigin` gained `project_files`; `UNDATED_START` is defined once
  in `core.models`; GitHub User-Agent reports the package version.

### Fixed

- Stale `import --help` text still claiming PDF resumes were not supported.

## [0.5.0] - 2026-08-29

### Added

- Service layer + FastAPI (#018): `services/` holds the use cases (CLI and
  API are thin shells); optional `[api]` extra serves read endpoints
  (/experiences, /search, /stats, /lint) plus draft-only creation via
  `experienceos-serve`.
- Plugin system (#019): built-ins declared as entry points; third-party
  packages register connectors/exporters by declaring their own;
  `experienceos plugins list` shows source, version and load state.
- Schema migrations (#020): ordered version steps, transparent read-path
  migration with backup under `<home>/backup/`, `migrate --check`.
- Sync & backup (#021): `experienceos sync [--init|--push REMOTE]` commits
  the home with git; `experienceos backup` writes a restore-ready zip.
- FTS index (#022): rebuildable SQLite FTS5 index (CJK unigram split);
  text queries use it only above the record threshold; files stay the
  source of truth. Benchmark script included.

## [0.4.0] - 2026-08-29

Output milestone (M3): faithful projections of confirmed records.

### Added

- Exporter framework (#014): `Exporter` protocol, name-keyed registry and the
  `experienceos export <name>` command with SearchQuery-backed filters;
  defaults to active records so drafts never leak into artifacts.
- Markdown exporter (#015): time-sorted profile with STAR structure and
  evidence lists, plus an `--timeline` by-year view; stdlib
  `string.Template` keeps it dependency-free; golden-file tests pin output.
- JSON Resume exporter (#016): jsonresume.org-compatible mapping
  (work/projects, technology -> keywords, url evidence -> url) validated by
  strict pydantic models; unexportable fields are dropped and itemized on
  stderr instead of being rewritten.
- Skill profile (#017): `experienceos profile` (technology timeline,
  co-occurrence Top-N, per-year evidence coverage) and machine-readable
  `stats --json`, backed by a shared pure-function stats module.

## [0.3.0] - 2026-08-29

Intelligence milestone (M2): provider wiring and AI-assisted drafting.

### Added

- LLM provider wiring (#010): `OpenAICompatibleProvider` completes the M0 skeleton — configurable timeout (`ai.timeout`), exactly one retry for network-class errors, and 429/5xx responses surfaced as `AIProviderError` with a response-body summary. New `experienceos config get/set/list` subcommands edit config.toml (secrets stay in env vars), `experienceos ai check` verifies the endpoint end to end (`--mock` targets the scripted provider), and `MockProvider` moves into the core `ai` package for tests and `--dry-run` modes.

## [0.2.0] - 2026-08-29

Import milestone (M1): every connector produces drafts only, with provenance.

### Added

- Resume importer (#009): rule-based (no LLM) parsing of Markdown/plain-text
  resumes into experience drafts — common CN/EN section headings, entry
  splitting on headings/bold/date lines, `YYYY-MM` period parsing (incl.
  `至今/present`, year-only ranges), curated technology keywords plus inline
  code spans, verbatim descriptions, and the source file attached as `file`
  evidence with `source.ref`. Undated entries carry an explicit `1970-01`
  placeholder tagged `undated`; PDF input is rejected until the M2 AI
  extraction path (#012).
- Local git repository analyzer (#008): read-only `git log` analysis of a
  local checkout — activity window, author-attributed commit count and
  median change size, extension-based language composition (built-in map,
  no linguist), repo-path evidence plus the GitHub URL when an `origin`
  remote points at github.com. `--author` defaults to the repository's
  `git config user.email`; non-git directories, submodules and shallow
  clones fail or degrade with readable errors.
- GitHub importer (#007): authenticated-user or explicit-author activity
  import, repository languages, paginated commits/PRs/issues, evidence-backed
  drafts, actionable authentication/rate-limit errors, and offline API fixtures.
- Connector framework (#006): `Extractor` protocol, `ExperienceDraft`
  (forced `status=draft` + mandatory provenance), `scheme:payload` source
  routing with Windows-drive-letter safety, name-keyed registry, and the
  `experienceos import` command (preview confirmation, never overwrites
  existing records).

### Fixed

- Experience detail rendering now uses ASCII-safe list/evidence markers and
  folds long evidence URLs correctly on Windows GBK consoles.

## [0.1.0] - 2026-08-25

First public foundation release (Milestone 0).

### Added

- Core `Experience` domain model (pydantic v2) with strict validation,
  schema versioning, evidence and provenance (`source`) sub-models.
- Time-sortable ULID identifier generation (stdlib only).
- Local-first file storage layer: one JSON file per experience, atomic
  writes, corruption-tolerant listing, `validate` reporting.
- In-memory search engine: weighted full-text matching plus filters by
  type / tag / technology / status / period overlap.
- CLI (`experienceos`): `init`, `add`, `list`, `show`, `search`, `set`,
  `add-item`, `edit`, `delete`, `stats`, `validate`, `path`.
- AI layer scaffolding: `LLMProvider` protocol, OpenAI-compatible provider
  skeleton (optional `[ai]` extra), versioned prompt templates.
- Project docs: README (zh-CN), ARCHITECTURE, ROADMAP, CONTRIBUTING and a
  GitHub-ready issue backlog split by milestone.
- CI workflow (GitHub Actions: ruff + pytest on Python 3.10-3.13,
  Ubuntu + Windows).

[Unreleased]: https://github.com/experienceos/experienceos/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/experienceos/experienceos/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/experienceos/experienceos/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/experienceos/experienceos/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/experienceos/experienceos/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/experienceos/experienceos/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/experienceos/experienceos/releases/tag/v0.1.0
