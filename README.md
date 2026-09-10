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

Phase 0 (scope freeze) and Phase 1 (source/rights/schema review) are implemented. The repository
contains a **metadata-only** discovery foundation, but production image collection is intentionally
not started yet.

Important findings and decisions are documented in:

- `docs/SOURCES.md`
- `docs/RIGHTS_POLICY.md`
- `docs/SCHEMA_RESEARCH.md`
- `docs/DISCOVERY_STRATEGY.md`

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
python -m pip install -e ".[dev]"
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

Phase 2 can later request the planned 50K-100K candidate pool explicitly after Phase 1 review is
accepted, for example with `--all-preferred-units --target 80000` and an appropriate output path.
Large outputs under `data/` are ignored by Git.

## Repository layout

```text
config/                     Collection and eligibility policy
docs/                       Source, rights, schema, and discovery decisions
src/smithsonian_image_text/ Metadata parsing/discovery/filtering
scripts/                    Safe metadata-only entry points for Phase 1/2
tests/                      Network-free unit tests
data/                       Local build products; large files are gitignored
```

No Kaggle API key is required for Phase 0/1 and this repository never stores credentials.
