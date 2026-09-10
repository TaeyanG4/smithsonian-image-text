# Smithsonian 25K Museum Image-Text Dataset

## Title

**Smithsonian 25K Museum Image-Text Dataset**

## Subtitle

24,972 CC0 images, rich metadata, leakage-safe splits and a 5K starter set

## Short description

24,972 cleaned 2D Smithsonian Open Access images paired with authoritative object metadata and
deterministic model-ready text. V1 includes nine broad sampling categories, leakage-safe object-level
train/validation/test splits, and a balanced 5,000-image starter subset for fast notebooks.

## Why this dataset

Museum vision datasets often force a tradeoff between usable image-text pairs, clear provenance, and
redistribution rights. This V1 build is intentionally conservative: every automatically released row
requires both the record metadata **and the exact selected image media item** to report Smithsonian
Open Access `CC0`. Ambiguous rights and sensitive-review candidates are kept out of the automatic
release.

The images are normalized to a maximum side of 512 px to keep the dataset lightweight enough for
notebooks and small-model experiments. The final build contains 24,972 images rather than forcing the
nominal 25K target: 25 source derivatives remained HTTP 404 after retry and three were below the
minimum resolution gate.

## What is included

- `metadata.parquet` — canonical full metadata; this is the recommended table for analysis/training.
- `images/` — 24,972 normalized JPEGs.
- `starter_5k/` — balanced 5,000-image subset with its canonical Parquet metadata and images.
- `exports/` — optional CSV, JSONL, and split convenience exports derived from the canonical Parquet.
- `docs/` — data dictionary, source, rights, distribution, and collection-QA documentation.
- `provenance/` — release manifest, checksums, and the pinned source-snapshot manifest.

The Kaggle root is intentionally kept small so the canonical table and images are immediately visible;
supporting documents and redundant convenience exports are grouped into folders instead of competing
with the primary data files in Data Explorer.

Model-derived embeddings are deliberately **not included in the base V1 download**. They are treated
as a separately versioned side artifact so the canonical image/metadata dataset stays lightweight,
reproducible, and independent of any one model family.

## Quick start

For tabular work, start with `metadata.parquet`. Join an image with its row using `file_name`. Use
`model_text` as a compact text input and preserve `object_id` whenever you resample or evaluate so
multiple views of the same museum object remain grouped.

The public Kaggle starter notebook demonstrates loading the dataset, checking the CC0 and split
invariants, plotting category counts, and previewing image-text pairs. The balanced `starter_5k` subset
is intended for quick EDA and prototyping before moving to all 24,972 rows.

## Categories

The nine broad categories are project sampling labels derived deterministically from Smithsonian unit
and metadata signals. They do not replace the original Smithsonian object type, topics, collection,
scientific name, culture, or other source fields.

The intended selection was:

| Category | Selected before image download |
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

The released counts are lower by only 28 rows in total because failed/low-resolution source images
were not backfilled by weakening quality gates.

## Text fields

`title`, `description`, `object_type`, `creator`, `date`, `place`, `topics`, scientific names, and
other fields preserve Smithsonian metadata where available.

`model_text` is a deterministic convenience string assembled from Smithsonian metadata only. It is
**not an LLM-generated caption and is not claimed to be a human-written visual description**. It is
capped at 512 characters for model-friendly use while the full source `description` remains separate.

## Splits

All media views sharing one Smithsonian `object_id` are assigned to the same split. V1 therefore
prevents front/back/side/detail views of one object from leaking across train, validation, and test.

Final row counts:

- train: 19,979
- validation: 2,498
- test: 2,495

Object intersections between all split pairs are zero.

## Rights and responsible use

Automatic inclusion requires:

1. Smithsonian record metadata `metadata_usage.access == "CC0"`;
2. exact selected media `type == "Images"`;
3. exact selected media `usage.access == "CC0"`.

CC0 addresses copyright. It does not automatically resolve privacy, publicity, trademark, cultural,
ethical, or other non-copyright considerations. The build uses conservative review rules and excludes
ambiguous/sensitive-review rows from automatic release, but downstream users remain responsible for
their own use context. See `docs/RIGHTS_POLICY.md` and `docs/SOURCES.md` for the exact policy and
official source links.

## Source and provenance

The source of truth is Smithsonian Open Access metadata plus the exact selected Smithsonian image
media item. V1 was built from official Smithsonian bulk/EDAN metadata and official media URLs, with
stable object/media identifiers and source URLs retained in the release. The pipeline performs rights
gating before selection, validates downloaded image bytes, keeps exact checksums, and records a local
snapshot manifest so rows can be traced back to upstream Smithsonian records.

The build pipeline and methodology are published at
`https://github.com/TaeyanG4/smithsonian-image-text`.

## Suggested uses

- image-text retrieval and CLIP-style baselines;
- museum-object classification and representation learning;
- metadata-conditioned VLM experiments;
- multimodal search prototypes;
- dataset quality, long-tail category, and multi-view research.

## Not included in V1

- 3D assets, audio, or video;
- bulk OCR/document corpora;
- model-derived embeddings in the base dataset (a separately versioned side-artifact strategy is
  documented in the repository);
- free-form generated captions;
- rows requiring manual sensitive/rights review.

## Reproducibility

The repository uses deterministic shard ordering, category sampling, image IDs, starter sampling, and
object-level splits. Source URLs, Smithsonian identifiers, checksums, rights fields, and audit reports
are preserved so a row can be traced back to its upstream record and media item.

## Acknowledgements

All source images and metadata in the automatic release come from Smithsonian Open Access records and
media that report CC0 access under the V1 eligibility policy. Smithsonian remains the authoritative
source for object context and identifiers; this project contributes deterministic filtering,
selection, normalization, packaging, QA, and split logic.

## Ideas to explore

- How well do general-purpose vision models transfer across art, natural history, design, technology,
  archaeology, and space objects in one rights-consistent corpus?
- How different are retrieval or classification results when using concise `model_text` versus richer
  source metadata fields?
- Which institutions or categories show the strongest multi-view effects, and how much does
  object-level leakage change evaluation results?
