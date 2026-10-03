# GMI V5 Agent Rules

This is a personal project. Complete the current task with the smallest clear change that
preserves verified behavior.

## Authority

1. Follow `BRANCHING.md` first. It is the highest repository-level authority for branch,
   merge, and promotion rules.
2. Treat the current Git state and checked-in files as authoritative. Historical handoff
   notes are context, not permission to override the repository.
3. Do not guess unknown product semantics. Check existing code, tests, data, and validated
   snapshots. If evidence is still missing, mark the point `UNKNOWN` and stop that part of
   the task.

## Branch Discipline

- Never develop or commit directly on `main`, `integration/v5`, `integration/apk`,
  `integration/pc`, or `snapshot/*`.
- Create each change on a short-lived task branch from the latest validated parent:
  - `core/*`, `backend/*`, and frontend tasks start from `integration/v5`;
  - `apk/*` starts from `integration/apk`;
  - `pc/*` starts from `integration/pc`.
- Do not branch from an unfinished task branch unless the dependency is explicit and
  approved.
- Squash validated task branches into their integration branch. Use normal merges between
  long-lived integration branches, exactly as defined in `BRANCHING.md`.
- Never merge `snapshot/*` into an integration branch or `main`.
- Before editing, state the current branch, task goal, expected files or directories, and
  excluded areas.
- Before promotion, inspect `git status`, `git diff --stat`, and
  `git diff --name-status`. Do not merge unexplained out-of-scope changes.

If the frozen historical `frontend` branch prevents Git from creating a `frontend/*` ref,
use a clearly named short-lived frontend task branch without deleting or renaming the
historical branch.

## Official-Source Requirement

Default discovery, automatic synchronization, background operations, and normal writes
must use only the game vendor's official website, API, launcher, manifest, or CDN metadata.

- Amarea, HoYoFiles, community repositories, mirrors, and aggregation APIs are allowed only
  in an explicitly named historical import or backfill workflow.
- Never use a third-party source as a default fallback.
- An official CDN download URL discovered through a third-party index does not make the
  discovery source official. Preserve the actual provenance.
- Do not change official endpoints, providers, source provenance, or game/vendor
  registration without explicit approval.
- Vendor-owned hosts whose names contain words such as `mirror` are still judged by their
  verified ownership and role, not by the hostname alone.

## Semantic Stability

Refactoring does not authorize behavior changes. Do not silently change:

- canonical JSON field meaning;
- `artifact_id` identity;
- source provenance;
- the public API contract;
- frontend data contracts;
- APK/PC platform ownership;
- game/vendor registration.

Canonical records use schema v2. Generate artifact IDs through
`backend.schema_v2.artifact_id()` using the complete record and artifact identity. Do not
derive identity from array order, URL, size, checksum, `kind`, `package_type`, or
`delivery_mode`.

Probe operations may update only the selected `artifacts[].urls[].current`. They must not
rewrite artifact identity, provenance, references, other URL candidates, or unrelated
record fields.

Keep Android and PC work isolated. A PC task must not casually edit Android collectors,
organizers, probes, or data, and the reverse also applies. If platform work requires a core
change, stop the platform task, use a separate `core/*` task, validate and synchronize it,
then resume platform work.

Retention and the external scheduler's deployment, trigger action, timezone, and missed-run
behavior remain unsupported or `UNKNOWN` unless a later task defines and validates them.
Do not invent these semantics or present them as implemented.

## Implementation Scope

- Prefer the smallest necessary change.
- Reuse existing routes, helpers, components, models, adapters, tests, and directory
  structure.
- Do not refactor unrelated code, format the whole repository, upgrade unrelated
  dependencies, or introduce speculative abstraction.
- For a non-trivial protocol, file format, parser, updater, or third-party API integration,
  check the repository and official SDK/examples before implementing a new solution.
- Preserve user-owned worktree changes. Do not stage or modify
  `GMI_V5_global_handoff.md` unless the user explicitly requests it.

## Investigation and Delegation

- Small, well-defined changes should be completed directly.
- When the entry point or root cause is unclear, use a read-only Explorer and consume its
  compressed conclusions instead of repeating the same search.
- Delegate large, well-defined, multi-file implementations to an Implementer, then review
  its diff and run the minimum relevant validation.
- Split parallel work by natural file or module boundaries. Do not let multiple agents edit
  the same area concurrently.
- Stop searching once the evidence is sufficient to implement or decide.

## Validation

Match validation effort to the change's risk:

1. Run the nearest relevant test or static check.
2. Expand to the affected module only when needed.
3. Run full suites, production builds, or real-network acceptance only when the change or
   task phase requires them.

Do not claim a test, UI, endpoint, or live source works unless it was actually exercised.
Distinguish test failures caused by the change from historical failures, environment
problems, missing dependencies, and external-service failures.

Do not use the Codex/ChatGPT in-app browser, desktop control, Chrome CDP, an interactive
browser, or the user's browser session. Repository-provided headless browser commands are
allowed only with an explicit timeout and clean exit. If those conditions cannot be met,
report the UI path as unverified.

## Git and Safety

- Do not overwrite, reset, clean, or delete user changes.
- Do not commit secrets, tokens, passwords, cookies, or private credentials.
- Do not commit, push, force-push, rebase, delete branches, create releases, or move tags
  unless the active task explicitly requires that action.
- Treat task branches as temporary. Freeze or delete them only when authorized.

## Completion Report

Report only:

- what changed;
- the key files;
- validation actually run;
- any remaining unverified or unsupported behavior.

Do not include raw search output, long logs, or unrelated findings.
