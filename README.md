# Smithsonian 25K Museum Image-Text Dataset

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

[![CI](https://github.com/TaeyanG4/smithsonian-image-text/actions/workflows/ci.yml/badge.svg)](https://github.com/TaeyanG4/smithsonian-image-text/actions/workflows/ci.yml)

Reproducible tooling for a rights-audited Smithsonian Open Access image-text dataset published on Kaggle.

**Kaggle:** [Smithsonian 25K Museum Image-Text Dataset](https://www.kaggle.com/datasets/taeyangg4/smithsonian-25k-museum-image-text)

**Current public release:** 24,972 CC0 images, rich metadata, leakage-safe splits, and a balanced 5K starter set.

## Current release

Dataset Version 3 is the current presentation-cleaned Kaggle release. The underlying image rows and canonical metadata are unchanged from the validated build; the Kaggle file layout was simplified so users can find the canonical table and documentation quickly.

- **24,972** released JPEG images.
- **5,000-row** balanced starter subset from 4,621 objects.
- **19,979 train / 2,498 validation / 2,495 test** rows with zero `object_id` overlap.
- **43/43** canonical `metadata.parquet` columns have Data Explorer descriptions.
- Kaggle Data Explorer root is intentionally minimal: `README.md` + `metadata.parquet`.
- Current Kaggle Usability score: **10.00 / 10**.
- Final validated release size is about **1.03 GB**, well below the 5 GB hard cap.

## Release principles

- Smithsonian official metadata is the source of truth.
- Both the record metadata and the exact selected image media item must explicitly report `CC0`.
- Official Smithsonian IDS derivatives are preferred; the target maximum side is 512 px.
- One `object_id` stays in exactly one train/validation/test split.
- Quality wins over forcing the release to exactly 25,000 rows.
- Sensitive or ambiguous material is quarantined for review rather than automatically released.
- 3D, audio, video, bulk OCR/document corpora, and free-form LLM captions are excluded from the base dataset.

## Build summary

- Discovery produced **97,718** media-level CC0 candidates.
- Eligibility filtering produced **90,451 eligible / 639 review-required / 6,628 rejected** rows.
- Balanced selection chose exactly **25,000** rows from **18,321** objects before image download.
- The mandatory 1K pilot completed **1,000 / 1,000** HTTP/decode successes and passed the package-size gate.
- Production collection retained **24,972** images. Twenty-five source derivatives remained HTTP 404 after retry and three were below the 256 px minimum; those rows were not backfilled.
- All retained JPEGs decoded successfully again during QA, with zero exact SHA256 duplicates and zero repeated `media_id` groups.
- Model-ready text is composed only from Smithsonian fields, is non-empty for 100% of retained rows, and is capped at 512 characters while the full source `description` remains intact.
- Final release validation passed the image, rights, dimensions, split-leakage, and checksum gates.
- CLIP ViT-B/32 embeddings are optional side artifacts and are intentionally excluded from the base release.

## Rights gate

Do not infer image rights from a record-level metadata license. A record can have CC0 metadata while an attached image has usage restrictions. Automatic eligibility requires all three conditions:

1. `content.descriptiveNonRepeating.metadata_usage.access == "CC0"`
2. media `type == "Images"`
3. that exact media item's `usage.access == "CC0"`

Anything else is rejected or sent to review according to the policy configuration.

## Pipeline

The collection flow preserves the rights, quality, and split gates in this order:

```text
discover_metadata.py -> build_candidate_tables.py -> select_candidates.py
-> run_pilot.py -> download_images.py -> qa_images.py
-> build_metadata.py -> create_splits.py -> build_starter.py
-> build_release.py -> validate_release.py
```

Large Phase 2 collection runs are always explicit. Large outputs under `data/` are ignored by Git.

## Developer setup

Python 3.11+ is supported.

```powershell
python -m pip install -e ".[data,dev]"
python -m pytest -q
python -m ruff check .
```

The CI matrix runs the same tests on Python 3.11 and 3.12.

## Safe metadata smoke test

This downloads Smithsonian metadata shards only and emits up to 250 CC0 image-media candidates from a small representative unit set. It does not download collection images.

```powershell
python scripts/discover_metadata.py
```

For a full rebuild, use explicit output/report paths and `--all-preferred-units --target ...`; the CLI does not silently turn the smoke-test default into a large crawl.

## Smithsonian API key

The bulk metadata source is public and does not require an API key. For scripts that use the Smithsonian API, provide your own data.gov key without committing it:

```powershell
$env:SMITHSONIAN_API_KEY = "..."
python scripts/probe_sources.py
```

## Repository layout

```text
config/                     Collection and eligibility policy
docs/                       Source, rights, schema, discovery, and Kaggle publishing notes
src/smithsonian_image_text/ Metadata, filtering, image, text, and split logic
scripts/                    Discovery through release and validation entry points
tests/                      Network-free unit tests
data/                       Local build products; large files are gitignored
```

## Documentation

- `docs/SOURCES.md`
- `docs/RIGHTS_POLICY.md`
- `docs/SCHEMA_RESEARCH.md`
- `docs/DISCOVERY_STRATEGY.md`
- `docs/DISTRIBUTION.md`
- `docs/KAGGLE_PUBLISHING.md`

Machine-readable controls live in `config/collection.yaml` and `config/eligibility_rules.yaml`.
