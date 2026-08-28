# PC baseline migration audit

The checked-in PC baseline is generated from Git objects in the fixed source
repository, not from a dirty worktree:

- source commit: `85e92d5b7f8868bb5c28901606c50132fe4705bf`
- source tree: `7e64fddb974324b3aca39f1d50d31b20336bea81`
- source inventory: 185 records, 110 manifests, 8 old indexes

Run the source-specific migrator in a temporary output root to reproduce the
historical subset and its exclusion details:

```text
python scripts/migrate_pc_data_baseline.py --source-repo E:\Project\Active\GMI --output-root <temporary-root>
```

The baseline test locates that repository next to this checkout by default;
set `GMI_PC_BASELINE_SOURCE_REPO` when the fixed source object is stored
elsewhere. Tests that require the external Git object are skipped when it is
not present; validation of every checked-in record, manifest, artifact, and
index remains unconditional.

The historical conversion writes 168 records, 1,449 artifacts and 106
manifests. The exclusions are deterministic:

| reason | count | scope |
| --- | ---: | --- |
| `provenance_official_launcher` | 4 | old Perfect World records and old Kuro launcher record |
| `hkrpg_zh_tw_without_semantics` | 12 | records containing `zh-tw` voice data without current language semantics |
| `official_api_chunk_reference` | 1 | chunk-only reference whose source was `official_api`; it is not rewritten |
| `empty_after_conversion` | 1 | record left empty after the disallowed chunk reference was removed |
| `kuro_route_manifest_unpaired` | 648 | old Kuro patch artifacts without a one-to-one local manifest |

The migrator output also contains `exclusion_details`, keyed by each fixed
source path and reason, so every excluded record or route artifact can be
reviewed without relying on the current checkout. The generated
`migrate_pc_data_baseline_audit.json` is checked in so that this review remains
available when the external source repository is absent. After this historical pass,
the 8 registered PC collectors are run once with timeout 30 and at most four
workers; their `official_sync` records replace same-identity history where
available. No resource body is downloaded.

Some retained historical records do not have a `source_url` in the original
provenance. This is not treated as a conversion failure: schema v2 makes the
field optional, and the migration preserves the real `source_kind`,
`source_name`, and any available repository/commit metadata. The BH3 records
retain their source name and import timestamp, while Kuro records retain the
archived repository metadata when present. Artifact CDN URLs are deliberately
not promoted to discovery provenance, so no URL is invented merely to fill a
field; the fixed source commit/tree and `exclusion_details` remain the audit
trail for those records.

Canonical `current` objects retained on historical URL candidates are the
last bounded probe observations present in the fixed snapshot. Their original
`checked_at` timestamps are preserved, and they are not evidence of a new
probe performed during this migration. The official current discovery pass
does not probe or add `current`; later refresh belongs to backend sync
operations.
