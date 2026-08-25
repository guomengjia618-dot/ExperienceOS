# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/experienceos/experienceos/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/experienceos/experienceos/releases/tag/v0.1.0
