# Official Sources

Last verified: **2026-09-10**

Only Smithsonian-controlled sources (plus the Smithsonian listing in the Registry of Open Data on
AWS) are accepted as collection authorities for V1. Third-party mirrors may be useful for discovery
or comparison, but they are not a rights or metadata source of truth for this dataset.

## 1. Smithsonian Open Access

- Open Access home: <https://www.si.edu/openaccess>
- FAQ: <https://www.si.edu/openaccess/faq>
- Developer tools: <https://www.si.edu/openaccess/devtools>
- Smithsonian Terms of Use: <https://www.si.edu/termsofuse>

The FAQ and Terms are the primary human-readable policy sources. The developer-tools page states
that collection data is refreshed weekly and documents both the Open Access API and bulk metadata
access. The FAQ explicitly distinguishes CC0 items from items subject to usage conditions and notes
that CC0 addresses copyright, not every possible third-party right.

## 2. Official Open Access API

Base URL:

```text
https://api.si.edu/openaccess/api/v1.0
```

API documentation:

```text
https://edan.si.edu/openaccess/apidocs/
```

An API key is obtained through `api.data.gov`. Project code reads the key from the
`SMITHSONIAN_API_KEY` environment variable; credentials must never be committed.

Current official Python wrapper repository:

```text
https://github.com/Smithsonian/smithsonian-openaccess
```

The wrapper confirms these V1 endpoints:

| Purpose | Endpoint |
| --- | --- |
| Search | `/search` |
| Category search | `/category/{category}/search` |
| Get record | `/content/{id}/` |
| Search terms/facets | `/terms/{category}` |
| Aggregate CC0 statistics | `/stats` |

Important search parameters include `q`, `start`, `rows`, `sort`, `type`, and `row_group`. The
official wrapper currently lists `edanmdm`, `ead_collection`, `ead_component`, and `all` as record
types and `objects` / `archives` as row groups.

### API role in this project

Use the API for:

- schema spot checks;
- current aggregate counts;
- terms/facet discovery;
- targeted record verification;
- debugging discrepancies found in bulk metadata.

Do **not** make the API the default transport for the 50K-100K discovery scan. The public bulk
metadata is more reproducible for a deterministic large scan and does not require pagination through
millions of search results.

Repeated Phase 1 requests made with a public/test API credential eventually returned HTTP `429`.
No numerical quota is inferred from that observation. Normal project use should use a registered
`api.data.gov` key, handle `429` conservatively, and still avoid treating API pagination as the bulk
collection path. `scripts/probe_sources.py` records API HTTP status instead of failing the whole source
probe when a rate limit is encountered.

## 3. Official bulk EDAN metadata on AWS

Smithsonian's older `Smithsonian/OpenAccess` GitHub repository states that the compressed archive
transitioned away from GitHub to the public AWS dataset. The live top-level EDAN index is:

```text
https://smithsonian-open-access.s3-us-west-2.amazonaws.com/metadata/edan/index.txt
```

AWS Registry entry:

```text
https://registry.opendata.aws/smithsonian-open-access/
```

Bucket:

```text
s3://smithsonian-open-access/
```

The Registry marks the dataset **CC0** and says new/updated metadata and image files are pushed
weekly.

For this project, that dataset-level registry license is **not** interpreted as permission for every
media URL mentioned by every EDAN record. Individual media eligibility is still decided from that
media object's `usage.access` field. This avoids confusing the license of the bulk metadata/open-data
resource with a record's media-specific usage status.

### Current layout observed on 2026-09-10

- Top-level EDAN index: **37 unit indexes**.
- Each probed unit index exposes **256 hexadecimal shard files**, `00.txt` through `ff.txt`.
- Files are line-delimited JSON records.
- Smithsonian's bulk-repository documentation says shard assignment is based on the first two
  characters of the content-serialization hash.
- Top-level index `Last-Modified` observed by the source probe: `Mon, 07 Sep 2026 07:32:37 GMT`.

The current unit list should be read from the live index rather than hard-coded from old README
tables, because the unit taxonomy changes over time.

The API `/stats` unit taxonomy is also not assumed to be identical to the current bulk-index unit
taxonomy. Current stats can contain unit labels that are absent from the live EDAN top-level index;
joins and quotas therefore use identifiers actually observed in the chosen source rather than a stale
global unit table.

## 4. Smithsonian Image Delivery Service (IDS)

Most selected Open Access image media in the Phase 1 smoke sample use `ids.si.edu`. Actual EDAN media
objects expose the source URL in `online_media.media[].content`, and often expose resource variants
such as high-resolution JPEG/TIFF, screen image, and thumbnail.

Two 512 px derivative URL forms were observed in official metadata / Smithsonian pages and validated
with one-off requests during Phase 1:

```text
https://ids.si.edu/ids/deliveryService?id=<IDS_ID>&max=512
```

and

```text
https://ids.si.edu/ids/deliveryService/id/ark:/.../512
```

Both checks returned images whose maximum dimension was 512 px. This is an **observed operational
behavior**, not treated as an immutable public API contract. Production download code must still
validate HTTP status, MIME type, decode success, and actual dimensions.

### Non-IDS media exists

The 400-row metadata-only Phase 1 smoke contained 399 `ids.si.edu` media URLs and one current
`collections.nmnh.si.edu` media URL. Therefore future download code must preserve and validate the
official `media.content` URL and must not assume every valid Smithsonian image is served by IDS.

## 5. Current API statistics: planning only

On 2026-09-10 the API `/stats` response reported:

- snapshot time: `2026-09`;
- total objects: `42,650,469`;
- `CC0_records`: `17,431,244`;
- `CC0_records_with_CC0_media`: `5,255,849`;
- `CC0_media`: `4,785,570`.

The current API search

```text
online_media_type:"Images" AND media_usage:"CC0"
```

reported `5,238,361` matching records.

These counts are useful only for sizing and source selection. At least one `/stats` unit currently
reports `CC0_records_with_CC0_media` greater than `CC0_records`, so this project does not infer legal
eligibility from aggregate metrics. The raw record and individual media object are inspected instead.

## Source priority for V1

1. **Rights policy:** Smithsonian Open Access FAQ + Terms of Use.
2. **Record/media truth:** current official EDAN API or official bulk EDAN JSON.
3. **Large metadata discovery:** official public S3 EDAN bulk export.
4. **Image bytes:** the official URL supplied by the selected EDAN media object, preferring a validated
   512 px IDS derivative where applicable.
5. **Audits:** preserve object/media identifiers, source URL, media URL, rights fields, source update
   information, and retrieval metadata so every released row can be traced back.

## Sources explicitly not authoritative for inclusion

- search-engine image results;
- Wikimedia / Internet Archive / other mirrors when a Smithsonian source can be used;
- a webpage being publicly reachable;
- record-level `metadata_usage` alone;
- `/stats` aggregate counts;
- an inferred license from age, institution, object type, or visual appearance.

If the official record does not provide a machine-verifiable qualifying media right, V1 does not
auto-release that media.
