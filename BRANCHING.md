# V5 Branching Model

This repository uses branches as short-lived development and validation lanes.
`main` is not the day-to-day development branch.

## Long-lived Branches

- `main`
  - Final trusted V5 product state.
  - Keep empty during migration and development.
  - Only merge from `integration/v5` after full validation.

- `integration/v5`
  - Current trusted V5 development baseline.
  - Merge validated shared, backend, frontend, APK, and PC work here.
  - New task branches should usually start from the latest `integration/v5`.

- `integration/apk`
  - APK platform validation branch.
  - Merge validated APK task branches here before promoting to `integration/v5`.
  - Run real APK collection and probing acceptance here.

- `integration/pc`
  - PC platform validation branch.
  - Merge validated PC task branches here before promoting to `integration/v5`.

- `snapshot/*`
  - Read-only historical reference branches.
  - Never merge into `integration/*` or `main`.
  - Use only for viewing, diffing, extracting confirmed files, and behavior comparison.

## Task Branches

Task branches are temporary. After validation and merge, freeze or delete them instead of
continuing development on stale branch history.

### Shared Core

- `core/schema`
  - Version JSON format, validation, and `artifact_id`.

- `core/version-store`
  - Generic saving, paths, overwrite behavior, and manual field preservation.

- `core/indexes`
  - Android and PC `index.json` generation and reading.

### APK

- `apk/data-baseline`
  - Official V5 APK baseline data and indexes.

- `apk/url-adapters`
  - APK official-site collectors and vendor-specific organizers.

- `apk/probe-adapters`
  - APK URL probing and validation.

- `apk/registry-integration`
  - APK collector/prober registration and API wiring.

### PC

- `pc/mihoyo-packages`
  - Mihoyo PC package resources.

- `pc/mihoyo-patches`
  - Mihoyo PC patch resources.

- `pc/mihoyo-voice`
  - Mihoyo PC voice resources.

- `pc/mihoyo-chunks`
  - Mihoyo PC chunk resources.

- `pc/kuro-manifests`
  - Kuro PC manifests.

- `pc/perfectworld-packages`
  - Perfect World PC package resources.

- `pc/probe-adapters`
  - PC URL probing and validation.

- `pc/registry-integration`
  - PC registration and API wiring.

- `pc/data-baseline`
  - PC historical data. Create only after PC formats and adapters are stable.

### Backend

- `backend/api-contract`
  - API output contract for APK and PC data, keeping frontend expectations stable.

- `backend/sync-operations`
  - Manual collection, scheduled sync, batch sync, and batch probing.

- `backend/version-admin`
  - Version visibility, manual management, and admin operations.

- `backend/retention-policy`
  - Create only if retention behavior is explicitly required.

### Frontend

- `frontend`
  - One-time imported frontend baseline.
  - After validation and merge into `integration/v5`, freeze or delete it.

- `frontend/*`
  - Future frontend task branches, such as APK status, PC package UI, version admin,
    or sync operations UI.

## Merge Flow

APK work:

```text
apk/*
  -> integration/apk
  -> integration/v5
  -> main
```

PC work:

```text
pc/*
  -> integration/pc
  -> integration/v5
  -> main
```

Shared, backend, and frontend work:

```text
core/*, backend/*, frontend/*
  -> integration/v5
  -> main
```

Snapshot branches:

```text
snapshot/*
  -> never merge
```

## Core Synchronization Rule

After any `core/*` branch is validated and merged into `integration/v5`, update affected
platform integration branches before continuing platform work:

```text
core/*
  -> integration/v5
  -> integration/apk and/or integration/pc
```

This prevents APK and PC work from continuing on stale schema or shared storage logic.

## Task Discipline

At task start, declare the expected file or directory scope.

At task end, inspect:

```text
git diff --stat
git diff --name-status
```

If files outside the declared scope changed, explain why before merging. Unexplained
out-of-scope changes must not be merged.

Tests and docs travel with the feature branch that needs them. Do not create generic
`tests`, `docs`, `requirements`, `config`, or `utils` branches.

## Merge Strategy

Use different merge strategies for task branches and long-lived integration branches.

### Task Branch to Integration Branch

For temporary task branches:

```text
core/*
backend/*
frontend/*
apk/*
pc/*
```

Prefer squash merge after validation.

Examples:

```text
apk/url-adapters
  -> squash merge -> integration/apk

pc/mihoyo-packages
  -> squash merge -> integration/pc

core/schema
  -> squash merge -> integration/v5
```

This keeps implementation and debugging commits out of the long-lived integration
history.

After a successful squash merge, freeze or delete the task branch.

### integration/v5 to Platform Integration

When shared core changes require APK or PC branches to catch up:

```text
integration/v5
  -> integration/apk

integration/v5
  -> integration/pc
```

Use a normal merge.

Do not squash this synchronization merge. This preserves ancestry between the
long-lived integration branches.

### Platform Integration to integration/v5

After platform acceptance:

```text
integration/apk
  -> integration/v5

integration/pc
  -> integration/v5
```

Use a normal merge commit.

Do not squash or cherry-pick an entire platform integration branch back into
`integration/v5`.

### integration/v5 to main

After full V5 validation:

```text
integration/v5
  -> main
```

Prefer fast-forward when possible. Otherwise use a normal merge commit.

Tag important validated states after promotion.

## Branch Creation Rule

Create task branches from the latest validated parent branch.

- `apk/*` starts from the latest `integration/apk`.
- `pc/*` starts from the latest `integration/pc`.
- `core/*`, `backend/*`, and `frontend/*` normally start from the latest
  `integration/v5`.

Before creating a new task branch, update the parent branch first.

Do not create new task branches from another unfinished task branch unless the dependency
is explicit and approved.

## Protected Branch Rule

Agents must not directly modify or commit to:

- `main`
- `integration/v5`
- `integration/apk`
- `integration/pc`
- `snapshot/*`

Changes must be produced on a task branch first.

Promotion into integration branches occurs only after validation and diff review.

## Semantic Stability Rule

Refactoring does not authorize semantic changes.

A task branch must not silently change:

- official data sources or endpoints;
- source provenance;
- JSON field meaning;
- artifact identity;
- public API contracts;
- platform ownership between APK and PC.

If such a change is required, declare it explicitly before implementation.
