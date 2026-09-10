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

## Fields intentionally deferred

The following belong to later phases and are not fabricated during Phase 1:

- `image_id`, `file_name`
- decoded `width`, `height`, `aspect_ratio`, `final_bytes`
- `sha256`, `phash`
- `category` (final normalized category)
- `model_text`, `text_source`
- `split`

Those fields require selection, image processing, deterministic caption composition, or leakage-safe
splitting and will be added only in their corresponding phases.

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
