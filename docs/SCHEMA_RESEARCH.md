# Smithsonian EDAN Schema Research

Last verified: **2026-09-10**

Smithsonian EDAN records are heterogeneous. The project therefore maps a small set of stable,
high-value fields while preserving identifiers and rights context needed to audit the mapping.

## Top-level record structure observed

Typical Open Access object records include:

```text
id
unitCode
type
url
hash
timestamp
lastTimeUpdated
title
content
```

`content` commonly contains three important groups:

```text
content.freetext
content.indexedStructured
content.descriptiveNonRepeating
```

Field availability and labels vary by Smithsonian unit. The mapper must tolerate missing groups and
must not assume a field is universally present because it appeared in one museum.

## `descriptiveNonRepeating`

Fields observed in current records include:

```text
guid
title.label
title.content
record_ID
unit_code
title_sort
data_source
record_link
online_media
metadata_usage.access
```

### Object identity

Canonical `object_id` priority:

1. `descriptiveNonRepeating.record_ID`
2. top-level EDAN `url`
3. top-level EDAN `id`

The raw EDAN id is also preserved separately as `edan_id`.

## `online_media`

The object can contain zero, one, or many media entries:

```text
descriptiveNonRepeating.online_media.media[]
```

Current image-media fields observed include:

```text
id
guid
type
idsId
usage.access
content
thumbnail
caption                 # sparse, authoritative when present
altTextAccessibility
extDescrAccessibility
resources[]
```

One object may have front/back/side/detail photographs. V1 intentionally preserves useful multiple
views, so the canonical candidate table is **media-level** rather than one row per object. All later
train/validation/test splitting must group by `object_id`.

### Resource variants

`media.resources[]` may expose:

- High-resolution TIFF;
- High-resolution JPEG;
- Screen Image;
- Thumbnail Image.

High-resolution JPEG resources may include `width`, `height`, and `dimensions`. Not every media entry
has every variant or size field.

V1 does not need the high-resolution file merely because it is advertised. The official
`media.content` URL is retained and, for IDS URLs, a 512 px derivative URL is computed for the later
image pilot.

## `freetext`

This area consists of lists of `{label, content}` objects whose names and labels differ by unit.
Observed/useful groups include:

```text
name
notes
date
place
setName
creditLine
dataSource
identifier
objectType
objectRights
physicalDescription
```

### Text mapping rules

- `title`: prefer `descriptiveNonRepeating.title.content`.
- `description`: use `notes` entries whose labels contain `Description` or `Summary`. Do **not** fall
  back to arbitrary notes such as record-modified timestamps or crowdsourcing fields merely to avoid
  a null description.
- `creator`: prefer `name` labels such as artist, maker, manufacturer, creator, designer, author, or
  photographer. Other name relations are preserved separately as `related_names` rather than being
  mislabeled as creators.
- `date`: use authoritative source text; do not parse into a guessed year at Phase 1.
- `collection`: selected `setName` entries associated with collection membership.
- `object_rights`: preserve `freetext.objectRights` as an independent audit field.
- `physical_description`: preserve physical-description/medium text when available.
- `credit_line`: preserve the official credit line.

No caption text is invented during this mapping.

## `indexedStructured`

Useful normalized/controlled fields observed include:

```text
name
place
topic
culture
object_type
scientific_name
online_media_type
online_media_rights     # when supplied
usage_flag
geoLocation
```

The project prefers indexed terms for `object_type`, topics, culture, and place when available,
because they are more convenient for profiling/category design than unit-specific free-text labels.

## Rights fields

At least three rights-related signals can coexist:

1. `descriptiveNonRepeating.metadata_usage.access` — rights/usage status for record metadata;
2. `online_media.media[].usage.access` — rights/usage status for that exact media item;
3. free/indexed contextual rights fields such as `objectRights` / `online_media_rights`.

The V1 automatic copyright gate requires both (1) and (2) to be exactly `CC0`. Context fields are
preserved for audit/review; they never override a restricted individual media item.

## Sensitive-content metadata: what is actually available

No generic, verified EDAN-wide boolean such as `sensitive=true`, `human_remains=true`, or
`sacred=true` was found that can safely decide public release across Smithsonian units.

Available signals include:

- `unit_code`;
- title;
- `freetext.notes` descriptions/summaries;
- `objectType` / `indexedStructured.object_type`;
- topics;
- culture;
- place;
- free-text object-rights/warnings;
- media rights;
- accessibility alt/extended descriptions.

The live source-schema probe also found a sparse media-level `caption` field. In a 1,302-media probe
it was present on 28 media objects. Because it is Smithsonian-supplied source metadata, the canonical mapper
preserves it as `media_caption`; it remains distinct from the later deterministic `model_text` field.

An API search for `"human remains"`, for example, returns records where the phrase is visible in
topics or titles, demonstrating that useful signals do exist. Their absence, however, is not evidence
that an object is non-sensitive. Therefore V1 uses quarantine + review, not an automatic negative
classification.

## Canonical Phase 1 candidate schema

The complete field-by-field mapping is in `DATA_DICTIONARY.md`. The minimum groups are:

### Identity

```text
object_id
edan_id
media_id
ids_id
unit_code
```

### Authoritative text

```text
title
description
object_type
institution
collection
creator
related_names
date
place
topics
culture
scientific_name
physical_description
credit_line
usage_flags
```

### Provenance and rights

```text
source_url
record_guid
media_guid
media_url
image_url
media_type
metadata_rights
media_rights
object_rights
indexed_media_rights
media_caption
```

### Accessibility/media hints

```text
alt_text
media_description
thumbnail_url
highres_jpeg_url
screen_url
source_width
source_height
```

### Reproducibility

```text
record_type
record_hash
record_timestamp
record_last_updated
raw_category
```

Image checksums, decoded image dimensions, final file names, model text, final category, and split are
deliberately deferred to later phases.

## Phase 1 smoke findings

A metadata-only smoke scan across CHNDM, FSG, SAAM, NMAH, NASM, NPM, NMNHPALEO, and NMNHMINSCI
produced 400 qualifying media rows from 248 unique objects without downloading collection images.
This immediately confirmed that multiple media views per object are common enough that object-level
grouping is not optional.

The sample also showed that field coverage varies substantially by source: title and source/media URLs
were complete in the sample, while description/object type were missing for a minority and creator,
topics, culture, and accessibility text were much sparser. Final `model_text` therefore needs a
deterministic fall-through composition policy rather than a single required description field.

## Schema assumptions explicitly rejected

- all units have identical free-text labels;
- one EDAN record equals one image;
- every Open Access image is on `ids.si.edu`;
- every media object exposes a high-resolution JPEG;
- every rights field agrees with every other rights field;
- missing sensitive keywords imply a safe object;
- aggregate `/stats` values can replace raw per-media inspection.
