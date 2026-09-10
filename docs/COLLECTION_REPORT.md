# Collection Report — Phase 0/1

Probe date: **2026-09-10**

Status: **Phase 0/1 complete enough to permit Phase 2 metadata-only discovery; production image
download remains blocked.**

## What was actually executed

- Initialized the local Git repository and scope/rights configuration.
- Queried official Smithsonian Open Access pages, API, official GitHub repositories, and public bulk
  metadata indexes.
- Parsed current official S3 bulk metadata without collecting a production image corpus.
- Performed two one-off IDS derivative checks in ignored scratch space solely to verify the 512 px
  URL behavior. These are not part of the dataset and no full-resolution archive was collected.
- Ran a metadata-only 400-row schema smoke across eight units.
- Ran network-free tests and lint.

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

**PASS for metadata-only Phase 2 discovery, with conditions.**

Conditions that remain mandatory:

1. Require exact record metadata `CC0` **and** exact individual image-media `CC0` for automatic V1
   eligibility.
2. Reject unknown/not-determined/usage-conditions media rights.
3. Quarantine explicit contextual-rights conflicts even when the primary media field says CC0.
4. Quarantine sensitive-content triggers; do not auto-release based on lack of a keyword.
5. Preserve all official source/media identifiers needed for later audits.
6. Do not start 25K production image collection before the 1K pilot and package-size/runtime gate.
7. Treat aggregate API metrics as planning aids only.

The generated audit files under `data/audits/` and metadata smoke under `data/interim/` are local build
artifacts and intentionally ignored by Git.
