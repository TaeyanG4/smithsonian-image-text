# Distribution and Versioning Plan

## Base V1 artifact

The canonical local package is `data/release/museum-images/`. It is designed to be portable across
Kaggle, local filesystems, and a future Hugging Face dataset repository without changing row IDs.

Keep these files stable inside V1:

- `images/<file_name>`
- `metadata.parquet`
- `metadata.csv`
- `captions.jsonl`
- `splits.csv`
- `starter_5k/`
- provenance/rights/data-dictionary documentation
- `release_manifest.json`
- `checksums.sha256`

The Parquet table is the canonical machine-readable release metadata. CSV/JSONL are convenience
formats and must contain the same release rows.

## Kaggle

Recommended dataset title: **Smithsonian 25K Museum Image-Text Dataset**.

The actual V1 row count is 24,972 and must be stated explicitly in the page copy. Do not imply that
`model_text` is a human-written image caption: it is deterministic Smithsonian-metadata composition.

Recommended resources:

1. full V1 package;
2. `starter_5k/` for quick notebooks;
3. `examples/starter_eda.ipynb` as the lightweight exploration notebook;
4. methodology/rights docs shipped beside the data.

Publishing should be an explicit external action after inspecting the final local validation report.
Do not let a rebuild script automatically overwrite an existing public dataset version.

The Kaggle CLI archives top-level directories when invoked with `--dir-mode zip`, so the public upload
may expose `images.zip`, `starter_5k.zip`, and similar archives rather than mounted folders. The starter
notebook detects both the local folder layout and this Kaggle zip layout.

## Hugging Face mirror

A later Hugging Face mirror should keep identical `image_id`, `object_id`, `file_name`, `split`, rights,
and source-provenance fields. Prefer Parquet metadata plus image archives/shards rather than silently
regenerating rows.

Suggested configs/subsets:

- `default`: all 24,972 V1 rows;
- `starter_5k`: balanced quick-start subset;
- optional future embedding configs stored separately from the base image package.

Do not recompute train/validation/test when mirroring. The existing object-level split is part of the
dataset contract and prevents multi-view leakage.

## Optional embeddings

Base V1 intentionally **does not ship model-derived embeddings**. A CLIP ViT-B/32 side artifact can be
built separately and keyed by the stable `image_id`; its manifest records the exact model
identifier/revision, preprocessing configuration, embedding dtype/dimension, and source metadata
checksum.

Keeping this artifact separate prevents embedding-model updates from forcing a new image release,
avoids unnecessary base-package dependencies, and keeps the canonical download focused on images plus
Smithsonian metadata.

## Versioning

Use semantic dataset versions for the packaged data:

- patch: documentation/checksum/packaging fix that does not change release rows or image bytes;
- minor: adds optional columns/artifacts while preserving row/image identity;
- major: changes rights policy, selection rules, image normalization, row identity, or split contract.

Never replace an existing public version in place when image bytes, included rows, or rights decisions
change. Preserve the prior release and publish a new version with a changelog.

## Rebuild provenance

For every published version retain:

- pipeline Git commit;
- `local_snapshot_manifest.json`;
- discovery/filter/sampling/pilot/production/QA/split reports;
- release manifest and SHA256 checksums;
- official Smithsonian source URLs and media/metadata CC0 fields.

The completed V1 large discovery predates direct per-shard content-hash capture. Its candidate-producing
raw source records and local outputs are hashed, and the original shard URLs are retained. New discovery
runs already capture source-index and downloaded-shard ETag/Last-Modified/byte-count/SHA256 directly.
