# PC historical recovery audit

This recovery adds missing PC history without replacing any existing V5 record. The reviewed dry-run contains 322 candidates: 321 current rows from the legacy production database and one commit-pinned NTE record from the old Git repository. It plans 153 records and 100 manifests, preserves 169 existing V5 records with the same version, and blocks none.

The complete candidate-by-candidate report is `scripts/recover_pc_history_from_archive_db_audit.json` (SHA-256 `6A74B3457E5A866E768E48849A8820CBBF296AE34421AF53AB4CD94EAD9C008E`). It records each source revision, artifact and URL count, provenance, decision, conflict state, output path, and serialized size.

## Sources and provenance

- Primary source: `Game-Manifest-Index/var/db/archive.sqlite`, opened with SQLite `mode=ro&immutable=1`.
- Formal backups were audited but not mixed into the recovery. Each backup had 271 visible PC versions, compared with 321 in the production database.
- NTE `1.3.12` comes only from commit `8609a814dd8eebfde66a32fd464ed4d1bc8db6a2` in the old `GMI` repository. The importer reads two allowlisted Git blobs and ignores the source worktree.
- HSR, BH3, and NAP history keeps `third_party_history` provenance because the legacy database originally obtained those versions from HoyoFiles/Amarea, even when a candidate URL points to an official miHoYo CDN.
- NTE, ToF, Arknights, and Endfield database rows use `legacy_migration` provenance. This records a historical database recovery, not a new live vendor collection.
- URL candidate `source_kind` remains separate from version discovery provenance. Endfield mirror candidates remain mirrors; official candidates remain official.
- Historical probe observations and `current` values were not migrated. Endfield `auth_key` query credentials were removed.

## Restored records

| Domain | Added | Final total | Source classification |
| --- | ---: | ---: | --- |
| `arknights-pc` | 2 | 2 | legacy production database |
| `endfield-pc` | 7 | 7 | legacy production database |
| `endfield-resources` | 7 | 7 | legacy production database |
| `hkrpg-pc` | 12 | 30 | HoyoFiles/Amarea history preserved |
| `nap-pc` | 1 | 20 | HoyoFiles/Amarea history preserved |
| `bh3-pc` | 24 | 56 | HoyoFiles/Amarea history preserved |
| `nte-pc` | 55 | 56 | 54 database records plus pinned Git `1.3.12` |
| `tof-pc` | 45 | 46 | legacy production database |

NTE now has 56 provable versions: 54 from the production database, `1.3.12` from the pinned Git snapshot, and existing V5 `1.3.13`. The older note that production once had 59 versions could not be substantiated. The remaining three versions are `UNKNOWN`; 47 additional catalog entries contained only 404 candidates and were not promoted to canonical records.

Endfield resources use the registered secondary-domain layout `data/hypergryph/endfield/pc/domains/endfield-resources/`. The seven selected current revisions are 509, 510, 511, 512, 513, 514, and 982. They contain 4,683 resources and 4,683 one-to-one official HTTPS URLs. Revision 982 supplies 1,000 resources for `1.4.4`; the older 985-resource revision was not used.

## Safety and verification

- All 153 restored records pass canonical schema v2 validation and deterministic `artifact_id()` recomputation.
- All 100 manifests pass identity, safe-path, count, and size checks.
- The recovery tool defaults to dry-run, stages all output before publication, preserves existing records, rejects conflicts, and is idempotent. A repeat apply planned and wrote zero records.
- Android data and the existing NTE `1.3.13`, ToF `6.3.3`, HSR `4.5.0`, and WuWa `3.6.0` files retained their pre-apply hashes.
- Affected PC indexes were rebuilt. NTE has 56 indexed versions, ToF 46, HSR 30, BH3 56, NAP 20, Arknights 2, Endfield PC 7, and Endfield resources 7.
- Recovery and PC baseline tests passed (22 tests). API contract tests passed (49 tests). The full Python suite passed (331 tests).
- Frontend tests passed (200 tests), and the production Vue/TypeScript build completed successfully. No frontend files changed.
- Schema, storage, index, URL-adapter, and probe-adapter tests passed. Every stored direct or secondary-domain URL now matches exactly one vendor/platform probe adapter.
- `compileall` and `git diff --check` passed. All 11 PC indexes were normalized; a second rebuild produced byte-identical files.

## Limited official-host probe results

The acceptance probe used the current read-only V5 probe service with a 15-second timeout, a 16-byte range, and no persistence. It selected only candidates marked `source_kind=official`; it did not contact HoyoFiles, Amarea, or GitHub mirrors.

- Available (`206`, signature or size evidence accepted): NTE `1.0.0`, NTE `1.3.12`, ToF `5.5.3`, Arknights `75.0.0`, and Endfield resources `1.0.13`.
- Unavailable (`404`): representative BH3 `3.5.0` and NAP `0.2.0` URLs. The historical records remain in the archive.
- Unknown: the Endfield PC `1.0.13` representative returned `403`.
- HSR `2.0.0` returned `206`, but the archive signature check failed; the probe classified it unavailable instead of treating the HTTP status alone as proof.

No bulk probe results or historical observations were written into canonical records during recovery.
