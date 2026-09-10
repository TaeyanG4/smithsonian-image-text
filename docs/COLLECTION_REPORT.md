# Collection Report — V1 build through Phase 11

Probe date: **2026-09-10**

Status: **Local V1 build and release validation complete. The 1K pilot passed before production
collection. No Kaggle publication has been performed.**

## What was actually executed

- Initialized the local Git repository and scope/rights configuration.
- Queried official Smithsonian Open Access pages, API, official GitHub repositories, and public bulk
  metadata indexes.
- Parsed current official S3 bulk metadata without collecting a production image corpus.
- Performed two one-off IDS derivative checks in ignored scratch space solely to verify the 512 px
  URL behavior. These are not part of the dataset and no full-resolution archive was collected.
- Ran a metadata-only 400-row schema smoke across eight units.
- Ran a 50K-100K bounded metadata discovery, balanced selection, 1K image pilot, production image
  collection, image QA, deterministic text build, leakage-safe split, and 5K starter build.
- Ran network-free tests and lint throughout development.

## Current source probe

- Official S3 EDAN top-level index currently exposes **37** unit index files.
- Probed unit indexes expose **256 hexadecimal metadata shards** each.
- Top-level index `Last-Modified` observed: **2026-09-07 07:32:37 GMT**.
- Smithsonian API `/stats` reports snapshot time `2026-09` and `42,650,469` total objects.
- API search for `online_media_type:"Images" AND media_usage:"CC0"` returned a current row count of
  **5,238,361** records.
- `/stats` is useful for planning only. At least one current unit reports a logically surprising
  relationship between `CC0_records` and `CC0_records_with_CC0_media`, so eligibility never trusts
  aggregate metrics; it inspects each raw record and each media item.

Selected `/stats` values observed during the probe (counts are planning signals, not release truth):

| Unit | CC0 records | `CC0_records_with_CC0_media` |
| --- | ---: | ---: |
| NMAH | 1,318,721 | 12,297 |
| CHNDM | 58,198 | 54,628 |
| NMNHPALEO | 746,315 | 97,362 |
| NPG | 16,197 | 14,671 |
| NMAI | 271,430 | 180 |
| NMNHANTHRO | 529,658 | 0 |
| NASM | 248,755 | 997 |

## 400-candidate metadata smoke

Input units: CHNDM, FSG, SAAM, NMAH, NASM, NPM, NMNHPALEO, NMNHMINSCI.

- Records scanned: **10,197**
- Media-level candidates emitted: **400**
- Unique objects: **248**
- Objects with >1 selected media row: **73**
- Metadata rights `CC0`: **400 / 400**
- Media rights `CC0`: **400 / 400**
- Media hosts: `ids.si.edu` **399**, `collections.nmnh.si.edu` **1**
- Basic metadata eligibility after word-boundary sensitive matching: **392 eligible**,
  **8 review_required**, **0 rejected**
- Basic usable-text gate among these pre-filtered rows: **100%**

Selected missing-field rates in this small, non-representative sample:

| Field | Missing |
| --- | ---: |
| title | 0.0% |
| description | 54.25% |
| media_caption | 95.0% |
| object_type | 16.75% |
| creator | 59.0% |
| date | 22.5% |
| place | 25.75% |
| topics | 35.5% |
| scientific_name | 83.5% |
| physical_description | 36.0% |
| alt_text | 62.75% |
| media_description | 49.75% |

This sample is for schema/implementation validation only; it is not an unbiased estimate of the final
dataset because units and shard limits were intentionally small.

An earlier smoke pass exposed a false-positive policy bug: substring matching of the term `grave`
also matched ordinary words such as `engraved`. The filter now uses word/phrase boundaries and has a
regression test for this case.

The higher `description`/`creator` missingness compared with the earliest parser pass is intentional.
The source-schema probe showed that arbitrary `notes` can contain administrative values (for example
record-modified metadata) and arbitrary `name` entries can mean collector, depicted person, issuing
authority, etc. V1 now prefers truthful nulls over semantically false text. `related_names`,
scientific names, physical descriptions, and the sparse official `media_caption` field are preserved
separately instead.

### Live source-schema probe

A separate metadata-only probe read 8,151 raw records / 1,302 media entries from one deterministic
shard each of CHNDM, FSG, NMAH, and NMNHPALEO. It found:

- media `caption` on 28 / 1,302 media entries;
- media `resources` on 1,289 / 1,302 entries;
- `High-resolution JPEG` resource on 1,276 entries;
- `High-resolution TIFF` resource on 608 entries;
- media hosts `ids.si.edu` 1,289 and `collections.nmnh.si.edu` 13;
- `freetext.objectRights` present in 238 sampled records, labeled `Restrictions & Rights`;
- indexed scientific-name/taxonomic fields heavily represented in the natural-history sample.

These counts are evidence about current field shapes, not guarantees that a field is universal.

## Media URL validation

Two official IDS patterns were observed and tested at 512 px:

1. Query form: `.../ids/deliveryService?id=<IDS_ID>&max=512`
2. ARK path form: `.../ids/deliveryService/id/ark:/.../512`

Both returned images whose maximum dimension was 512 px in the one-off checks. Candidate extraction
therefore computes these derivative URLs when the source is on `ids.si.edu`. Non-IDS media URLs are
preserved and must be handled by later download/resize validation rather than rewritten speculatively.

## Phase 1 gate decision

**PASS for metadata-only Phase 2 discovery, with conditions.** Those conditions were preserved in the
later automatic release filters.

Conditions that remain mandatory:

1. Require exact record metadata `CC0` **and** exact individual image-media `CC0` for automatic V1
   eligibility.
2. Reject unknown/not-determined/usage-conditions media rights.
3. Quarantine explicit contextual-rights conflicts even when the primary media field says CC0.
4. Quarantine sensitive-content triggers; do not auto-release based on lack of a keyword.
5. Preserve all official source/media identifiers needed for later audits.
6. Do not start 25K production image collection before the 1K pilot and package-size/runtime gate.
7. Treat aggregate API metrics as planning aids only.

## Phase 2 — metadata discovery

The full V1 metadata pool was built without downloading image bytes during discovery. A broad
32-shard scan across preferred units was followed by offset shard extensions focused on sparse
art/history/space units so additional rows improved diversity rather than simply increasing the
largest natural-history collections.

- Final merged candidates: **97,718 media rows**.
- Allowed design range: **50,000-100,000**.
- Candidate-producing raw source records are retained as compressed NDJSON in `data/raw_metadata/`.
- Canonical candidates are retained in Parquet under `data/interim/`.
- `data/audits/local_snapshot_manifest.json` pins 21 V1 metadata/config lineage artifacts by SHA256.
- The completed large scans predate direct per-shard SHA256 capture, so their reports preserve shard
  URLs and the raw candidate-producing records are locally hashed. New discovery runs capture source
  index and shard URL/ETag/Last-Modified/bytes/SHA256 directly.

## Phase 3 — eligibility

The final merged metadata table produced:

| Status | Rows |
| --- | ---: |
| Eligible | **90,451** |
| Review required | **639** |
| Rejected | **6,628** |

In addition to the original rights/text/sensitive controls, V1 rejects an exact media URL when it is
attached to multiple Smithsonian object IDs. This avoids an ambiguous image-to-object text alignment
and prevents a shared image from crossing later object-level splits. Review-required rows are not
silently promoted into the automatic release.

## Phase 4 — balanced sampling

Deterministic selection produced exactly **25,000 media rows from 18,321 unique objects**. The
selection capped one object at four views and one institution at 6,250 rows. Actual supply after
filtering was used to revise the initial example quotas rather than forcing categories that did not
have enough clean candidates.

| Category | Selected |
| --- | ---: |
| Art | 4,000 |
| Natural History | 5,000 |
| Science & Technology | 2,400 |
| Historical Objects | 3,500 |
| Archaeology | 900 |
| Space & Aviation | 1,700 |
| Decorative Arts / Design | 3,500 |
| Coins / Stamps / Documents | 2,500 |
| Other Objects | 1,500 |

## Phase 5 — 1,000-image pilot

The required category-balanced pilot was executed before production:

- attempted/successful: **1,000 / 1,000**;
- HTTP 404: **0**;
- decode failures: **0**;
- exact SHA256 duplicate groups: **0**;
- final JPEG mean: **30.7 KB**;
- final JPEG p50: **27.5 KB**;
- final JPEG p95: **66.2 KB**;
- projected 25K package: about **0.776 GB**;
- measured pilot wall time: about **61.8 seconds** at 12 workers;
- projected full runtime at the same concurrency: about **0.43 hours**.

The package-size gate was therefore **GO** (`<= 4 GB`). The unexpectedly small average files are a
consequence of using official ~512 px derivatives plus JPEG quality 84; images are not upsampled merely
to hit a target package size.

## Phase 6 — production image collection

Production used 16 workers, retry/backoff, bounded response size, temporary source files, decode
validation, EXIF orientation, RGB conversion, maximum side 512 px, JPEG quality 84, atomic final
rename, append-only checkpoints, and resume. The 1,000 validated pilot outputs were SHA256-verified and
reused instead of being downloaded again.

First production pass:

- selected rows: **25,000**;
- successful images: **24,972**;
- permanent failures after a second resume/retry pass: **28**;
- failures: **25 HTTP 404 + 3 images below the 256 px minimum**;
- final image bytes: **797,441,211**;
- first-pass wall time: about **710.8 seconds**;
- image + production-candidate metadata working-set estimate: about **0.808 GB**.

The same 28 rows failed again on a dedicated resume pass, so they were not backfilled. **24,972 clean
images** is preferred over weakening quality controls to reach exactly 25,000.

## Phase 7 — image QA and duplicate review

Every retained production JPEG was decoded again after collection:

- scanned: **24,972**;
- QA keep: **24,972**;
- QA hard exclude: **0**;
- exact SHA256 duplicate groups: **0**;
- repeated `media_id` groups: **0**;
- extreme-aspect-ratio review flags: **34**.

The 34 extreme-aspect files were visually reviewed as legitimate long textiles/patterns, currency/
document strips, and other narrow objects rather than broken crops, so the flag is retained without
automatic exclusion. pHash distance <=4 produces many review candidates in visually repetitive
white-background collections; per project policy they are **not auto-deleted**. Pair and connected-
component audits are kept for review while exact SHA256 remains the automatic exact-duplicate rule.

## Phases 8-10 — text, canonical metadata, and split

Final canonical metadata contains **24,972 rows / 18,299 unique objects**. The 28 production failures
are the only selected rows removed at this stage.

`model_text` is deterministic source-only composition; the full authoritative source fields remain
separate. After profiling revealed that a few source descriptions were extremely long, the ML
convenience text was capped without modifying the source `description`:

- usable `model_text`: **100%**;
- mean length: about **263 characters**;
- p95: **498 characters**;
- maximum: **512 characters**.

Object-level deterministic split:

| Split | Rows | Objects |
| --- | ---: | ---: |
| train | **19,979** | **14,663** |
| validation | **2,498** | **1,831** |
| test | **2,495** | **1,805** |

`object_id` intersections between every pair of splits are **0**. Category distributions stay close
to 80/10/10 at row level.

## Phase 11 — starter subset

The starter subset contains exactly **5,000 rows / 4,621 objects**, allows at most two views per object,
and matches 20% of the full selection category quota: 800 Art, 1,000 Natural History, 480 Science &
Technology, 700 Historical Objects, 180 Archaeology, 340 Space & Aviation, 700 Design, 500
Coins/Stamps/Documents, and 300 Other. It inherits the full dataset split assignment and has zero
object-level split leakage.

## Phase 12 — optional embeddings

Embeddings are intentionally **omitted from the base V1 package**. The package already exposes stable
`image_id`, `file_name`, `model_text`, split, SHA256, and pHash fields, so CLIP/SigLIP or other
embeddings can be produced later as a versioned side artifact. Keeping them separate avoids increasing
the default download for users who only need images and metadata.

## Phases 13-14 — final QA and local release

The local release was built at `data/release/museum-images/` and then validated from that release tree,
not merely from the working/interim files. The final validator returned **PASS**:

- main rows / unique image IDs / unique filenames: **24,972 / 24,972 / 24,972**;
- starter rows: **5,000** and every starter identity is a subset of the full metadata;
- missing `source_url`: **0**;
- missing `object_id`: **0**;
- non-CC0 convenience/source-rights rows: **0**;
- usable `model_text`: **100%**;
- full and starter object-level split leakage: **0**;
- missing main/starter image files: **0**;
- release-image decode failures: **0**;
- dimension mismatches: **0**;
- full CSV/JSONL row counts match Parquet exactly;
- required release docs: complete;
- checksum files verified: **29,990**, failures **0**;
- final measured release size: about **1.036 GB**, safely below the 4 GB target and 5 GB hard cap.

The release builder is configured to record the exact final apparent byte count, including
`checksums.sha256`, in `release_manifest.json`; the validator checks that value against the release
directory itself.

## Phases 15-17 — publication assets and distribution plan

`docs/KAGGLE_PAGE.md` contains the prepared Kaggle description and `notebooks/starter_eda.ipynb`
contains a starter EDA/training-path notebook. These are included in the local release. External
publication is deliberately separate and has not been triggered by the build scripts.

`docs/DISTRIBUTION.md` defines the versioning/subset strategy for Kaggle and a possible Hugging Face
mirror while keeping optional embeddings separate.

The generated audit files under `data/audits/`, metadata under `data/interim/`, and images under
`data/images/` are local build artifacts and intentionally ignored by Git.
