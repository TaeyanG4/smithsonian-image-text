# Phase 0 — Scope Freeze

Status: **FROZEN for V1**

## Product target

- Kaggle title: **25K Museum Images with Captions**
- Subtitle: **CC0 Smithsonian images and metadata for computer vision, CLIP and VLMs**
- Final image target: 25,000; acceptable clean range: 20,000-25,000.
- Quality wins over count. A clean 21K release is preferred to a mediocre 25K release.
- Maximum image side: approximately 512 px.
- Kaggle package target: <= 4 GB; absolute hard stop: 5 GB.
- Starter subset: 5,000 images in the same Kaggle Dataset.
- Usable text target: >= 90%.
- Rebuild target after pipeline development: <= 8 hours.

## Included in V1

- 2D still images only.
- Smithsonian official metadata and authoritative source URLs.
- Deterministically composed model-ready text from Smithsonian metadata.
- One canonical row per selected image/media view.
- Object-level train/validation/test grouping to prevent front/back/detail leakage.
- 5K starter subset.
- Optional CLIP embeddings only if they do not threaten release schedule or size.

## Explicitly excluded from V1

- 3D assets.
- Video and audio.
- Full-resolution TIFF archives.
- A mirror of the full Smithsonian corpus.
- Uncontrolled modern portrait photography.
- Automatic release of culturally sensitive / funerary / human-remains material.
- Free-form LLM-generated source-like captions.
- Large OCR/document corpora.

## Non-negotiable collection order

1. Official-source and rights review.
2. Metadata-only discovery.
3. Eligibility filtering and sensitive quarantine.
4. Balanced sampling.
5. 1K image pilot.
6. Size/time gate.
7. Production image collection.

The project must not jump directly to a 25K image download.

## Phase 0 hard gates

- Do not start production image download while media-level CC0 cannot be determined in code.
- Do not accept a design whose projected package exceeds 5 GB.
- Do not split by image ID when multiple views share one object ID.
- Do not treat generated text as original Smithsonian caption text.
- Do not commit large image/metadata build products or credentials to Git.

## Current implementation guardrails

- `config/collection.yaml` encodes size/count/rebuild targets.
- `config/eligibility_rules.yaml` encodes the conservative rights/review gate.
- `scripts/discover_metadata.py` is metadata-only; no production downloader exists in Phase 0/1.
- `.gitignore` blocks dataset build products and common secret files.

Phase 2 may begin only after the Phase 1 rights/schema findings are reviewed and the automatic
media-level CC0 gate remains intact.
