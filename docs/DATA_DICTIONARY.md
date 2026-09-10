# Candidate Data Dictionary

This is the Phase 1 canonical **media-level candidate** schema. One Smithsonian object can produce
multiple rows when it has multiple image views. `object_id` is therefore the grouping key for later
deduplication/splitting; `media_id` identifies the individual view.

| Field | Meaning | Smithsonian source / derivation |
| --- | --- | --- |
| `object_id` | Stable object grouping key | `descriptiveNonRepeating.record_ID`, falling back to EDAN URL/id |
| `edan_id` | EDAN top-level record id | top-level `id` |
| `media_id` | Individual media/view id | media `id`, falling back to `idsId`/media `guid` |
| `ids_id` | Smithsonian IDS identifier when present | media `idsId` |
| `unit_code` | Owning/source unit code | `descriptiveNonRepeating.unit_code` / top-level `unitCode` |
| `title` | Object title/name | `descriptiveNonRepeating.title.content` |
| `description` | Authoritative descriptive text | `freetext.notes` entries preferring labels containing Description/Summary |
| `object_type` | Object/type terms | `indexedStructured.object_type`, then `freetext.objectType` |
| `institution` | Smithsonian data source | `descriptiveNonRepeating.data_source` |
| `collection` | Collection/set names | selected `freetext.setName` values |
| `creator` | Creator/maker/artist etc. | selected `freetext.name` values |
| `related_names` | Other authoritative related names without claiming creator status | all `freetext.name` values |
| `date` | Source date text | `freetext.date`, then `indexedStructured.date` |
| `place` | Place terms | `indexedStructured.place`, then `freetext.place` |
| `topics` | Topic terms | `indexedStructured.topic` |
| `culture` | Culture terms | `indexedStructured.culture` |
| `scientific_name` | Scientific/taxonomic names | `indexedStructured.scientific_name`, then `freetext.taxonomicName` |
| `physical_description` | Physical description / medium text | selected `freetext.physicalDescription` values |
| `credit_line` | Smithsonian credit line | `freetext.creditLine` |
| `usage_flags` | Source usage/category-like flags | `indexedStructured.usage_flag` |
| `raw_category` | Initial source-side category hint | currently same normalized `usage_flags`; Phase 4 remaps deterministically |
| `source_url` | Official object/source link | `record_link`, falling back to record `guid` |
| `record_guid` | Object ARK/guid when present | `descriptiveNonRepeating.guid` |
| `media_guid` | Media ARK/guid when present | media `guid` |
| `media_url` | Official media content URL exactly as supplied | media `content` |
| `image_url` | Preferred ~512 px request URL | deterministic IDS derivative transform; non-IDS preserved |
| `thumbnail_url` | Source thumbnail URL | media `thumbnail` |
| `highres_jpeg_url` | High-resolution JPEG resource if advertised | media `resources[label=High-resolution JPEG].url` |
| `screen_url` | Screen derivative if advertised | media `resources[label=Screen Image].url` |
| `thumbnail_resource_url` | Thumbnail resource if advertised | media resource URL |
| `source_width` | Advertised source width when available | first media resource carrying `width` |
| `source_height` | Advertised source height when available | first media resource carrying `height` |
| `media_type` | Media type | media `type`; V1 accepts `Images` only |
| `media_rights` | **Selected media rights gate** | media `usage.access`; V1 automatic inclusion requires exact `CC0` |
| `metadata_rights` | Record metadata usage status | `metadata_usage.access`; V1 automatic inclusion requires exact `CC0` |
| `object_rights` | Object rights statements supplied in free text | `freetext.objectRights` |
| `indexed_media_rights` | Indexed media-rights hints | `indexedStructured.online_media_rights` when present |
| `media_caption` | Smithsonian-supplied media caption when supplied | media `caption` |
| `alt_text` | Smithsonian accessibility alt text | media `altTextAccessibility` |
| `media_description` | Smithsonian media-level extended description | media `extDescrAccessibility` |
| `record_type` | EDAN record type | top-level `type` |
| `record_hash` | Bulk record hash | top-level `hash` |
| `record_timestamp` | Source record timestamp | top-level `timestamp` |
| `record_last_updated` | Source update timestamp | top-level `lastTimeUpdated` |
| `source_shard_url` | Official bulk shard that yielded the candidate | discovery provenance added during Phase 2 |
| `eligibility_status` | `eligible`, `review_required`, or `rejected` | deterministic Phase 3 policy result |
| `eligibility_reasons` | Pipe-delimited policy reason codes when applicable | deterministic Phase 3 policy result |

## Selection fields added in Phase 4

`selected_candidates.parquet` adds fields that are deterministic derivatives of authoritative metadata:

- `category_code`: one of the nine normalized sampling categories.
- `category`: human-readable form of `category_code`.
- `selection_hash`: fixed-seed SHA256 rank used for reproducible balanced sampling.

The category is a broad project sampling label, not a replacement for Smithsonian `object_type`,
collection, topic, or culture fields.

## Image/QA fields added in Phases 5-7

Production image manifests add:

| Field | Meaning |
| --- | --- |
| `image_id` | Stable, zero-padded-filename-compatible integer assigned after final Phase 4 selection |
| `file_name` | Normalized JPEG filename, e.g. `00000001.jpg` |
| `http_status` | Final HTTP response status for the download attempt |
| `content_type` | Source response MIME type |
| `attempts` | Network attempts; 0 means the byte-identical Phase 5 pilot result was reused |
| `download_bytes` | Bytes fetched for the selected source derivative |
| `download_seconds` | Network transfer time for the successful attempt |
| `original_width`, `original_height` | Decoded dimensions of the downloaded source derivative before normalization |
| `original_format` | Decoded source format |
| `width`, `height` | Final normalized JPEG dimensions in canonical release metadata |
| `aspect_ratio` | `width / height` |
| `final_bytes` | Final JPEG byte count |
| `sha256` | Exact checksum of the final JPEG bytes |
| `phash` | 64-bit DCT perceptual hash represented as 16 hex characters |
| `qa_flags` | Non-fatal image-QA flags such as extreme aspect ratio, when present |

Image normalization applies EXIF orientation, transparency-safe RGB conversion, maximum side 512 px,
JPEG quality 84, final decode verification, atomic rename, and a minimum downloaded-image maximum side
of 256 px.

## Text and split fields added in Phases 8-10

The canonical release table adds:

- `model_text`: deterministic composition of available Smithsonian title, object type, scientific
  name, creator, date, place, topics, and description. No free-form facts are generated.
- `text_source`: fixed value `smithsonian_metadata_composed` for these composed rows.
- `rights`: convenience value `CC0`; the separate `metadata_rights` and `media_rights` source fields
  are retained and both must be exact `CC0` for automatic release.
- `split`: `train`, `validation`, or `test`, assigned at **object_id group level**. Every view of the
  same object receives the same split.

These derived fields never overwrite the corresponding raw Smithsonian fields.

## Recommended Parquet logical types

The Phase 1 mapper intentionally keeps heterogeneous Smithsonian values conservative rather than
guessing stronger types.

- **Required string identifiers:** `object_id`, `media_id`.
- **Nullable strings:** all source text, unit/category hints, URLs, GUIDs, rights/status fields, and
  accessibility fields.
- **Nullable int64:** `source_width`, `source_height`, `record_timestamp`, `record_last_updated` when
  the upstream value is numeric.
- **Later numeric image fields:** decoded/final `width`, `height`, byte sizes as int64 and
  `aspect_ratio` as float64/float32.

Dates stay as authoritative source strings in the candidate table because unit records may contain a
year, a range, circa text, dynasty/period labels, or other non-ISO forms. Any normalized date added in
a later phase must be a separate derived field, never a destructive replacement.
