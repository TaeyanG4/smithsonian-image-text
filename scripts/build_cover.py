#!/usr/bin/env python3
"""Build a deterministic Kaggle-native cover from final release images.

Kaggle's current dataset metadata uploader submits two fixed crop rectangles for
the cover asset: a 560x280 header from the top-left and a 280x280 thumbnail
starting at x=140, y=0.  Rendering the canonical asset at exactly 560x280 keeps
the banner lossless and lets us deliberately compose the central square so the
dataset card thumbnail is useful instead of showing an accidental partial tile.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]


PROMPTS = {
    "Art": "a landscape painting",
    "Natural History": "a fossil specimen",
    "Science & Technology": "a scientific instrument",
    "Historical Objects": "a historical museum artifact",
    "Archaeology": "an ancient archaeological object",
    "Space & Aviation": "a spacecraft",
    "Decorative Arts / Design": "a decorative textile pattern",
    "Coins / Stamps / Documents": "a postage stamp or historical document",
    "Other Objects": "an interesting museum object",
}

# Eight representative categories are arranged so the middle four tiles live
# entirely inside Kaggle's 280x280 thumbnail crop (x=140..420).  The remaining
# four fill the two 140px side rails visible only in the 2:1 header.
COVER_LAYOUT = [
    ("Historical Objects", (0, 0, 140, 140)),
    ("Archaeology", (0, 140, 140, 280)),
    ("Art", (140, 0, 280, 140)),
    ("Natural History", (280, 0, 420, 140)),
    ("Science & Technology", (140, 140, 280, 280)),
    ("Space & Aviation", (280, 140, 420, 280)),
    ("Decorative Arts / Design", (420, 0, 560, 140)),
    ("Coins / Stamps / Documents", (420, 140, 560, 280)),
]


def _load_embeddings(path: Path) -> tuple[np.ndarray, np.ndarray]:
    table = pq.read_table(path, columns=["image_id", "embedding"])
    ids = np.asarray(table["image_id"].to_numpy(), dtype=np.int64)
    vectors = np.asarray(table["embedding"].to_pylist(), dtype=np.float32)
    return ids, vectors


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata",
        type=Path,
        default=ROOT / "data" / "interim" / "metadata_final.parquet",
    )
    parser.add_argument(
        "--embeddings",
        type=Path,
        default=ROOT / "data" / "interim" / "clip_embeddings.parquet",
    )
    parser.add_argument(
        "--embedding-manifest",
        type=Path,
        default=ROOT / "data" / "audits" / "clip_embeddings_manifest.json",
    )
    parser.add_argument(
        "--image-dir", type=Path, default=ROOT / "data" / "images" / "production"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs" / "dataset-cover-image.jpg"
    )
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "docs" / "cover_grid_manifest.json"
    )
    args = parser.parse_args()

    try:
        import torch
        from transformers import AutoTokenizer, CLIPModel
    except ImportError as exc:
        raise SystemExit("CLIP cover generation requires torch + transformers") from exc

    metadata = pd.read_parquet(args.metadata).set_index("image_id", drop=False)
    image_ids, image_embeddings = _load_embeddings(args.embeddings)
    embedding_manifest = json.loads(args.embedding_manifest.read_text(encoding="utf-8"))
    model_id = embedding_manifest["model_id"]
    revision = embedding_manifest.get("model_revision")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision)
    model = CLIPModel.from_pretrained(model_id, revision=revision).eval().to(device)
    tokens = tokenizer(list(PROMPTS.values()), padding=True, truncation=True, return_tensors="pt").to(
        device
    )
    with torch.inference_mode():
        text_features = model.get_text_features(**tokens).float()
        text_features = text_features / text_features.norm(dim=1, keepdim=True).clamp_min(1e-12)
    query_vectors = text_features.cpu().numpy()

    id_to_position = {int(image_id): i for i, image_id in enumerate(image_ids)}
    chosen: list[dict] = []
    used_objects: set[str] = set()
    prompt_categories = list(PROMPTS)
    query_index_by_category = {category: index for index, category in enumerate(prompt_categories)}
    for category, _rect in COVER_LAYOUT:
        query_index = query_index_by_category[category]
        subset = metadata[metadata["category"] == category]
        positions: list[int] = []
        candidate_ids: list[int] = []
        for row in subset.itertuples():
            object_id = str(row.object_id)
            ratio = float(row.aspect_ratio)
            if object_id in used_objects or ratio < 0.65 or ratio > 1.8:
                continue
            image_id = int(row.image_id)
            position = id_to_position.get(image_id)
            if position is not None:
                positions.append(position)
                candidate_ids.append(image_id)
        scores = image_embeddings[np.asarray(positions)] @ query_vectors[query_index]
        order = np.argsort(scores)[::-1]
        image_id = candidate_ids[int(order[0])]
        row = metadata.loc[image_id]
        used_objects.add(str(row["object_id"]))
        chosen.append(
            {
                "category": category,
                "prompt": PROMPTS[category],
                "image_id": image_id,
                "file_name": str(row["file_name"]),
                "object_id": str(row["object_id"]),
                "title": str(row["title"]),
                "source_url": str(row["source_url"]),
                "clip_score": float(scores[int(order[0])]),
            }
        )

    canvas = Image.new("RGB", (560, 280), "white")
    for item, (_category, rect) in zip(chosen, COVER_LAYOUT, strict=True):
        source_path = args.image_dir / item["file_name"]
        x0, y0, x1, y1 = rect
        tile_width = x1 - x0
        tile_height = y1 - y0
        with Image.open(source_path) as source:
            image = ImageOps.fit(
                source.convert("RGB"),
                (tile_width, tile_height),
                method=Image.Resampling.LANCZOS,
            )
        canvas.paste(image, (x0, y0))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output, format="JPEG", quality=90, optimize=True)
    args.manifest.write_text(
        json.dumps(
            {
                "purpose": "Kaggle dataset cover rendered at native crop geometry",
                "kaggle_header_crop": {"left": 0, "top": 0, "width": 560, "height": 280},
                "kaggle_thumbnail_crop": {
                    "left": 140,
                    "top": 0,
                    "width": 280,
                    "height": 280,
                },
                "layout": [
                    {"category": category, "rect": list(rect)} for category, rect in COVER_LAYOUT
                ],
                "model_id": model_id,
                "model_revision": revision,
                "selection": chosen,
                "output": str(args.output),
                "width": canvas.width,
                "height": canvas.height,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output), "selection": chosen}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
