# V1 Rights and Redistribution Policy

Last verified: **2026-09-10**

This document defines the conservative machine gate for the Kaggle release. It is an engineering
policy for dataset inclusion, not legal advice.

## Policy sources

- Smithsonian Open Access FAQ: <https://www.si.edu/openaccess/faq>
- Smithsonian Terms of Use: <https://www.si.edu/termsofuse>
- Open Access Developer Tools: <https://www.si.edu/openaccess/devtools>
- Smithsonian Open Access AWS listing: <https://registry.opendata.aws/smithsonian-open-access/>

Smithsonian states that Open Access assets designated CC0 may be used, transformed, and shared
without Smithsonian permission or fee, including commercially. Smithsonian also explicitly warns
that CC0 addresses copyright and does not guarantee the absence of third-party rights such as
trademark, privacy, or publicity rights.

The AWS Registry's CC0 label is treated as the license for the Open Access data resource, not as a
shortcut that turns every media reference encountered in EDAN metadata into an eligible image. The
individual selected media item must still explicitly pass the media-level gate below.

## Critical distinction: metadata rights are not media rights

An EDAN record can expose CC0 metadata while one or more attached media items have a different usage
status. Consequently this is **not** sufficient:

```text
content.descriptiveNonRepeating.metadata_usage.access == "CC0"
```

Automatic V1 inclusion requires the exact selected media item to pass as well.

## Automatic V1 rights gate

For each candidate **media row**, all of the following must be true:

```text
record.content.descriptiveNonRepeating.metadata_usage.access == "CC0"
media.type == "Images"
media.usage.access == "CC0"
media.content is present
object_id is present
media_id is present
source_url is present
```

The implementation is in `config/eligibility_rules.yaml`, `schema.py`, and `filtering.py`.

### Automatic reject

Reject rather than infer eligibility when any of these apply:

- missing/unknown record metadata usage;
- missing/unknown individual media usage;
- individual media status is `Usage conditions apply`;
- media is not an image;
- media URL is missing;
- required audit identifier/source link is missing;
- official media cannot later be fetched/decoded during the image pilot or production QA.

Typical machine reason codes:

```text
NO_CC0_METADATA
NO_CC0_MEDIA
NO_IMAGE
RIGHTS_UNCLEAR
```

## Redistribution decision

**Decision: eligible CC0 image media and their CC0 metadata may be redistributed in the Kaggle
package, subject to the conservative filters in this project.**

The Smithsonian FAQ says attribution is not required for CC0 assets, but recommends basic credit and
a link so users can obtain current data. V1 therefore preserves Smithsonian institution/source URLs,
rights fields, and identifiers and will include source/rights documentation in the package.

This project will not use Smithsonian logos or trademarks as if they endorse the Kaggle dataset.

## Third-party and personal rights risk

Smithsonian's Terms make clear that a CC0 marker does not necessarily clear:

- rights of publicity;
- privacy rights;
- trademarks;
- contractual or other third-party restrictions.

This is why V1 is stricter than “media says CC0.” Certain material is quarantined even after the CC0
copyright gate passes.

## Sensitive-content quarantine

There is no verified universal EDAN field that can be treated as a complete sensitive-content flag.
V1 therefore uses a deliberately conservative review layer over metadata signals.

### Unit-level review triggers

Rows from these units are not automatically released in V1:

```text
NMAI
NMNHANTHRO
NAA
HSFA
```

This does **not** mean all material in those units is sensitive. It is a workload/risk guardrail for
the first release.

### Metadata term review triggers

Terms related to the following are quarantined when they appear as actual words/phrases in the
available title/description/type/topic/culture/accessibility fields:

- human remains;
- funerary, burial, mortuary, grave;
- sacred, ceremonial, ritual;
- medicine bundles;
- mummy/mummified material;
- skull/cranium;
- ancestor;
- repatriation / NAGPRA.

These are review triggers, not automatic assertions about cultural sensitivity. A Phase 1 regression
test ensures a term such as `grave` does not incorrectly match the ordinary word `engraved`.

### Modern portrait photography

National Portrait Gallery (`NPG`) candidates matching portrait/photographic signals are sent to
review rather than automatically released. Later phases may simply exclude this group from V1 if a
reliable living-person / modernity determination cannot be made from metadata.

## Rights conflicts and warnings

The canonical schema preserves both:

- `object_rights` from free-text object rights statements; and
- `indexed_media_rights` when present.

These are audit/context fields and must never be used to weaken the individual `media.usage.access`
gate. If explicit restriction phrases in these fields conflict with an otherwise CC0 media row, the
current filter moves that row to `review_required` with `RIGHTS_CONTEXT_REVIEW` rather than silently
keeping it. Current review phrases include `Usage conditions apply`, `Not determined`, `all rights
reserved`, `permission required`, and `restrictions apply`.

## What V1 will not do

- infer public domain from an object's age;
- assume a museum/unit is entirely CC0;
- treat a public URL as permission;
- treat `metadata_usage=CC0` as permission for every media file;
- remove rights/credit/context fields to save metadata space;
- generate a source-like free caption that could be mistaken for Smithsonian text;
- automatically publish sensitive material merely because no keyword was found.

## Release audit requirements

Before Kaggle release:

- `metadata_rights != CC0`: **0** rows;
- `media_rights != CC0`: **0** rows;
- unknown rights: **0** rows;
- missing `source_url`: **0** rows;
- missing `media_url`: **0** rows;
- every `review_required` row: explicitly resolved as include/exclude with an auditable decision;
- package README and source docs: clearly state the CC0/third-party-rights distinction.

When uncertainty remains, V1 excludes the row. Dataset size is subordinate to rights clarity.
