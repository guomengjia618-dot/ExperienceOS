# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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


### Added

- LLM provider wiring (#010): `OpenAICompatibleProvider` completes the M0 skeleton — configurable timeout (`ai.timeout`), exactly one retry for network-class errors, and 429/5xx responses surfaced as `AIProviderError` with a response-body summary. New `experienceos config get/set/list` subcommands edit config.toml (secrets stay in env vars), `experienceos ai check` verifies the endpoint end to end (`--mock` targets the scripted provider), and `MockProvider` moves into the core `ai` package for tests and `--dry-run` modes.

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

[Unreleased]: https://github.com/experienceos/experienceos/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/experienceos/experienceos/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/experienceos/experienceos/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/experienceos/experienceos/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/experienceos/experienceos/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/experienceos/experienceos/releases/tag/v0.1.0
