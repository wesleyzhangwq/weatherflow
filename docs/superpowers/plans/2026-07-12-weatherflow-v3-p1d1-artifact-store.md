# WeatherFlow v3 P1d1 Artifact Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Persist validated, content-addressed Run artifacts with durable provenance and atomic metadata/audit behavior.

**Architecture:** Blob bytes live beneath the Workspace artifact root using SHA-256 paths. SQLite owns immutable manifests. `ArtifactStore` validates names and hashes, writes through a temporary file + atomic replace, then commits manifest and audit event together; failed metadata commits remove newly-created orphan blobs.

**Tech Stack:** Python 3.12, pathlib/os, hashlib, SQLite/aiosqlite, Pydantic v2, pytest-asyncio.

---

## Locked contracts

- Artifact paths are derived from digest, never user-controlled names.
- Manifest stores provenance; credentials and raw secrets are not valid metadata.
- Same content is deduplicated physically but each Run may have its own manifest.
- Reported hash and size are verified from bytes before commit.
- A manifest never points at a missing blob after a successful return.

### Task 1: Manifest model, migration 5, repository

**Files:** Add migration 5; create `artifacts/{__init__.py,models.py,repository.py}` and tests; update storage tests.

- [ ] Write failing tests for migration table creation; frozen `ArtifactManifest`; repository round-trip/list-by-run; duplicate manifest rejection; and JSON validation metadata.
- [ ] Add table `artifacts(id PK, run_id FK, name, media_type, digest, size_bytes, relative_path, validation JSON, created_at)` plus run index. Implement immutable manifest and connection-bound repository.
- [ ] Verify and commit `feat: define durable Artifact manifests`.

### Task 2: Content-addressed ArtifactStore

**Files:** Create `artifacts/store.py` and focused tests.

- [ ] Write failing tests that `put_bytes()` writes beneath `<artifact_root>/sha256/<prefix>/<digest>`, returns verified manifest, appends `artifact.created`, deduplicates identical bytes, rejects blank/path-like names, cleans a new blob when ledger commit fails, and never writes outside artifact root.
- [ ] Implement `ArtifactStore.put_bytes(run_id, workspace, name, media_type, data, validation=None)`: validate logical name, compute digest/size, create directories, write unique temp file in target directory with exclusive mode, fsync, `os.replace`, then transactionally create manifest and event. Track whether this call created the blob and remove it on transaction failure. Existing digest blobs must match expected size/hash.
- [ ] Verify focused and full tests; commit `feat: add content-addressed Artifact Store`.

### Task 3: Document and audit P1d1

- [ ] Update README/AGENTS file map and artifact invariants.
- [ ] Run locked sync, `make check`, diff/status checks; commit `docs: describe WeatherFlow Artifact Store`.

P1d1 ends here. P1d2 builds the provider-neutral shared turn loop over Runs, snapshots, Trust, approvals, and artifacts.
