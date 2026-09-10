# Kaggle Page Draft — 25K Museum Images with Captions

## Title

**25K Museum Images with Captions**

## Subtitle

CC0 Smithsonian images and authoritative metadata for computer vision, CLIP, and VLM workflows

## Short description

24,972 cleaned 2D Smithsonian Open Access images with authoritative object metadata, deterministic
model-ready text, nine broad sampling categories, object-level train/validation/test splits, and a
balanced 5,000-image starter subset.

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

- `images/` — 24,972 normalized JPEGs.
- `metadata.parquet` — canonical full metadata; recommended table for analysis/training.
- `metadata.csv` — convenience export of the same rows.
- `captions.jsonl` — image ID, filename, object ID, and deterministic `model_text`.
- `splits.csv` — leakage-safe train/validation/test assignments.
- `starter_5k/` — balanced 5,000-image subset with the same schema and inherited split.
- `SOURCES.md`, `RIGHTS_POLICY.md`, `DATA_DICTIONARY.md`, `COLLECTION_REPORT.md` — provenance and
  methodology.
- `provenance/local_snapshot_manifest.json` — hashes pinning the local metadata snapshot used for V1.
- `checksums.sha256` — release-file checksums.
- `examples/starter_eda.ipynb` — starter exploration notebook.

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
their own use context. See `RIGHTS_POLICY.md` and `SOURCES.md` for the exact policy and official source
links.

## Suggested uses

- image-text retrieval and CLIP-style baselines;
- museum-object classification and representation learning;
- metadata-conditioned VLM experiments;
- multimodal search prototypes;
- dataset quality, long-tail category, and multi-view research.

## Not included in V1

- 3D assets, audio, or video;
- bulk OCR/document corpora;
- embeddings as a required base artifact;
- free-form generated captions;
- rows requiring manual sensitive/rights review.

## Reproducibility

The repository uses deterministic shard ordering, category sampling, image IDs, starter sampling, and
object-level splits. Source URLs, Smithsonian identifiers, checksums, rights fields, and audit reports
are preserved so a row can be traced back to its upstream record and media item.
