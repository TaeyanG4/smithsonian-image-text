# 25K Museum Images with Captions

Reproducible tooling for a Kaggle-ready Smithsonian Open Access image-text dataset.

**Kaggle subtitle:** CC0 Smithsonian images and metadata for computer vision, CLIP and VLMs

## V1 scope

- 20,000-25,000 clean 2D images; quality wins over hitting 25K.
- Smithsonian official metadata is the source of truth.
- Both record metadata and each selected image media item must explicitly report `CC0`.
- Official Smithsonian IDS derivatives are preferred; target maximum side is 512 px.
- Final Kaggle package target is <= 4 GB; hard cap is 5 GB.
- One `object_id` stays in exactly one train/validation/test split.
- Sensitive or ambiguous material is quarantined for review rather than auto-released.
- V1 does not include 3D, audio, video, bulk OCR/document corpora, or free-form LLM captions.

## Current status

The local V1 build has progressed through discovery, filtering, balanced selection, the mandatory
1K image pilot, production collection, image QA, deterministic text composition, object-level
splitting, the 5K starter subset, and final release validation. External Kaggle publication has
**not** been performed.

Current build summary (2026-09-10):

- Phase 2 merged discovery: **97,718** media-level CC0 candidates.
- Phase 3: **90,451 eligible / 639 review-required / 6,628 rejected**.
- Phase 4: exactly **25,000** balanced rows selected from **18,321** objects, maximum four views per
  object and maximum 6,250 rows from one institution.
- Phase 5 pilot: **1,000 / 1,000** HTTP/decode successes, zero exact duplicates, projected 25K package
  about **0.776 GB** -> package gate **GO**.
- Phase 6 production: **24,972** successful images. Twenty-five source derivatives remained HTTP 404
  after a retry pass and three were below the 256 px minimum; those 28 rows were deliberately not
  backfilled because the project prioritizes quality over reaching exactly 25K.
- Phase 7: all 24,972 retained JPEGs decoded again successfully; zero exact SHA256 duplicates and zero
  repeated `media_id` groups. pHash-near candidates are audit/review signals only, not auto-deletions.
- Phase 8/9: model-ready text is composed only from Smithsonian fields, is non-empty for 100% of
  retained rows, and is capped at 512 characters while the full source `description` stays intact.
- Phase 10: **19,979 train / 2,498 validation / 2,495 test** rows with zero `object_id` overlap.
- Phase 11: balanced **5,000-row** starter subset from **4,621** objects, inheriting the same split.
- Phase 13/14 local release: **PASS**, 24,972 main rows + 5,000 starter rows, zero missing/decode/
  dimension/rights/split-leakage/checksum failures, final apparent package about **1.036 GB**.
- Phase 15/16: Kaggle page copy and a starter EDA notebook are prepared locally; publication remains a
  separate explicit external action.

Important findings and decisions are documented in:

- `docs/SOURCES.md`
- `docs/RIGHTS_POLICY.md`
- `docs/SCHEMA_RESEARCH.md`
- `docs/DISCOVERY_STRATEGY.md`
- `docs/DISTRIBUTION.md`

Machine-readable controls live in `config/collection.yaml` and `config/eligibility_rules.yaml`.

## Rights gate

Do not infer image rights from a record-level metadata license. A record may have CC0 metadata
while an attached image has usage restrictions. The V1 automatic eligibility gate requires:

1. `content.descriptiveNonRepeating.metadata_usage.access == "CC0"`
2. media `type == "Images"`
3. that exact media item's `usage.access == "CC0"`

Anything else is rejected or sent to review according to the policy config.

## Developer setup

```powershell
python -m pip install -e ".[data,dev]"
python -m pytest -q
python -m ruff check .
```

If using the Smithsonian API, set your own data.gov key without committing it:

```powershell
$env:SMITHSONIAN_API_KEY = "..."
python scripts/probe_sources.py
```

The bulk metadata source itself is public and does not require the API key.

## Safe metadata smoke test

This command downloads Smithsonian **metadata shards only** and emits up to 250 CC0 image-media
candidate rows by default from a small representative unit set. It does not download collection
images.

```powershell
python scripts/discover_metadata.py
```

Large Phase 2 runs remain explicit. For a fresh rebuild, use an explicit output/report path and
`--all-preferred-units --target ...`; the CLI will not silently turn its safe smoke default into a
50K+ run. Large outputs under `data/` are ignored by Git.

The collection scripts are ordered to preserve the required gates:

```text
discover_metadata.py -> build_candidate_tables.py -> select_candidates.py
-> run_pilot.py -> download_images.py -> qa_images.py
-> build_metadata.py -> create_splits.py -> build_starter.py
-> build_release.py -> validate_release.py
```

Phase 12 embeddings are intentionally omitted from the base V1 package. They can be distributed as a
separate optional artifact later without making every image-only/text-only user download them.

## Repository layout

```text
config/                     Collection and eligibility policy
docs/                       Source, rights, schema, and discovery decisions
src/smithsonian_image_text/ Metadata, filtering, image, text, and split logic
scripts/                    Discovery through local release/validation entry points
tests/                      Network-free unit tests
data/                       Local build products; large files are gitignored
```

No Kaggle API key is required to rebuild the local dataset package and this repository never stores
credentials. Publishing is intentionally a separate external action.
