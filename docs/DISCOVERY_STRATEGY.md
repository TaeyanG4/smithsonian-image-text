# 50K-100K Metadata Discovery Strategy

Last verified: **2026-09-10**

Goal: construct a diverse, auditable **metadata candidate pool** before any large image download.
Target V1 discovery size is about **80K media-level candidate rows**, with an acceptable 50K-100K
range. This is not the final 25K selection.

## Why bulk S3 is the primary discovery transport

The official EDAN bulk export is public, weekly refreshed, line-delimited JSON and deterministically
partitioned by unit/hash shard. It is therefore a better fit than deep API pagination for a
reproducible metadata sweep.

The API remains useful for `/stats`, terms/facets, targeted verification, and schema debugging.
Repeated Phase 1 test-key probes did encounter HTTP `429`, which is another practical reason not to
base a 50K-100K discovery crawl on deep API pagination. No undocumented request-rate number is assumed.

## Current source topology

On 2026-09-10:

- official top-level EDAN S3 index exposed 37 unit indexes;
- probed unit indexes exposed 256 hexadecimal shards (`00.txt` ... `ff.txt`);
- shard sizes vary dramatically by unit;
- the Open Access source is refreshed weekly.

The discovery run should snapshot:

```text
discovery_started_at
top_level_index_url
top_level_index_last_modified
top_level_index_etag
unit_index_urls
selected_shard_urls
selected_shard_etags / last-modified where practical
pipeline_git_commit
configuration hash
```

That makes a later rebuild explainable even if Smithsonian updates the weekly export.

## Unit-first, not global-random sampling

A naive global sample will be dominated by very large natural-history units. Instead:

1. Read the live unit index.
2. Restrict Phase 2 to a broad preferred-unit list spanning art/design, history, space/technology,
   postal material, natural history, gardens/zoo, etc.
3. Deterministically permute each unit's 256 shard URLs with a fixed seed.
4. Scan units round-robin so one giant unit cannot consume the entire target first.
5. Apply explicit per-unit discovery caps tuned from the metadata-only yield calibration. This avoids
   a soft-cap/two-pass scheduler dropping the unconsumed tail of a shard.
6. Stop when the global media-candidate target is satisfied, not after downloading every unit.

The current code uses seed:

```text
smithsonian-image-text-v1
```

and a global maximum of 12,000 candidate rows per unit, with lower unit-specific caps for several
high-yield or sparse units. A CLI `--max-per-unit` value is a true hard upper bound over those configured
caps. These are discovery guardrails, not final Phase 4 category quotas.

The CLI deliberately defaults to only the configured `smoke_units`. A large scan requires explicit
`--all-preferred-units` (or an explicit `--units ...` list), so a casual smoke command cannot silently
become an 80K discovery job.

## Candidate extraction while streaming

For every JSON record in a selected shard:

1. Read `metadata_usage.access`.
2. Skip the record for automatic V1 candidacy unless it is exactly `CC0`.
3. Iterate `online_media.media[]`.
4. Keep only `type == "Images"`.
5. Keep only exact media `usage.access == "CC0"`.
6. Emit one canonical candidate row per qualifying media/view.
7. Preserve `object_id` so all views remain groupable.
8. Compute a preferred 512 px IDS derivative URL when the official URL is on IDS; preserve other
   official media URLs unchanged.
9. Do **not** request the image bytes.

Then run the Phase 3 metadata filters over the emitted rows: text usability, required provenance,
sensitive review, and later image-resolution hints where authoritative metadata provides them.

## Diversity guardrails during discovery

The discovery pool should be intentionally larger and broader than the final release. Do not try to
force the final nine Kaggle categories yet.

Track at minimum:

- candidate rows by unit/institution;
- unique `object_id` count by unit;
- media rows per object distribution;
- object type distribution;
- `usage_flags` / preliminary category signals;
- missingness for title/description/type/date/topics/creator/place;
- CC0 record/media counts encountered;
- sensitive-review trigger rate;
- non-IDS media-host distribution.

Recommended Phase 2 stop criteria:

- 50K minimum / ~80K target / 100K maximum candidate media rows;
- enough unique objects that multiple-view inflation is not driving pool size;
- no single unit allowed to consume most of the candidate pool;
- at least several viable units for each intended high-level category where the source supports it.

If a source has extremely high media yield, stop scanning it once its discovery budget is filled.
If a source is sparse, scan additional deterministic shards only while it meaningfully improves
diversity.

## Handling multiple views

Do not deduplicate front/back/side/detail images merely because they share an object. During discovery:

- retain their distinct `media_id` values;
- report media-per-object counts;
- keep the `object_id` grouping key;
- optionally cap views only during Phase 4 sampling if a few objects would otherwise dominate.

The final split must assign all views of the same `object_id` to the same partition.

## Raw metadata preservation without mirroring all Smithsonian data

Do not archive every scanned Smithsonian record or every 42M+ object locally. For reproducibility,
Phase 2 should preserve raw JSON for records that produced candidate rows (and optionally rejected
near-candidates needed for audits), compressed under `data/raw_metadata/`.

A V1 run-level layout is used rather than mirroring every upstream shard as a local file:

```text
data/raw_metadata/phase2_candidate_records.ndjson.gz
data/raw_metadata/phase2_candidate_records_extension_32_63.ndjson.gz
data/raw_metadata/phase2_candidate_records_extension_64_127.ndjson.gz
```

Each line wraps the untouched source record with `source_unit` and `source_shard_url`. The completed
large V1 scans predated per-shard hash capture; their source shard URLs are retained and all
candidate-producing raw records are preserved. `data/audits/local_snapshot_manifest.json` pins those
raw files and canonical outputs by SHA256. New discovery runs additionally record top/unit index and
downloaded shard URL, ETag/Last-Modified, byte count, and SHA256 in a source manifest. The bulk source
itself remains the canonical upstream archive.

## Canonical output

Primary output:

```text
data/interim/candidates.parquet
```

Recommended auxiliary audits:

```text
data/audits/discovery_report.json
data/audits/*_source_manifest.json
data/audits/local_snapshot_manifest.json
data/audits/shared_media_across_objects.csv
```

The Parquet table should be media-level. Report unique object counts separately.

## Schema-drift policy

Smithsonian data is heterogeneous and refreshed weekly. The parser should:

- tolerate missing optional fields;
- fail loudly on invalid NDJSON or a broken source response;
- log unknown media types/rights values rather than map them to CC0;
- record fields/labels that appear unexpectedly;
- keep raw source identifiers so any mapping can be audited;
- never convert an unrecognized rights value into an eligible state.

## Why `/stats` is not the rights gate

The 2026-09 `/stats` response is useful for deciding which units may have enough CC0 media, but at
least one current unit exposes aggregate metric values whose relationship is not intuitive. The
project therefore treats `/stats` as planning telemetry only.

Eligibility comes from:

```text
record metadata_usage.access
+ exact individual media.type
+ exact individual media.usage.access
```

## Phase 2 execution shape

The implementation foundation already supports deterministic, metadata-only round-robin streaming.
A full Phase 2 run should proceed in checkpoints:

1. **Schema smoke:** hundreds of rows across representative units — completed in Phase 1.
2. **Yield calibration:** one deterministic shard from each preferred unit showed severe natural-history
   dominance in an unconstrained pool.
3. **Adaptive metadata scan:** a 32-shard broad scan plus two offset extensions for sparse art/history/
   space units produced **97,718** merged media-level candidates, within the 50K-100K design range.
4. **Canonicalize + filter:** **90,451 eligible**, **639 review-required**, **6,628 rejected** after the
   final merged-table build. Cross-object shared media URLs are rejected automatically because the
   image-to-object text alignment is ambiguous.
5. **Distribution gate:** deterministic category sampling selected exactly **25,000 rows / 18,321
   unique objects**, with at most four views per object and at most 6,250 rows from one institution.

The Phase 5 1K pilot was subsequently completed before production: 1,000/1,000 HTTP/decode successes,
0 exact duplicates, mean final JPEG 30.7 KB, and a projected 25K package of about 0.776 GB. That passed
the <=4 GB package-size gate and authorized Phase 6 production collection.
