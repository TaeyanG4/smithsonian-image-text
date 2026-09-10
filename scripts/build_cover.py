#!/usr/bin/env python3
"""Build a deterministic 3x3 Kaggle cover grid from final release images."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from PIL import Image, ImageDraw, ImageFont, ImageOps

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
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "cover_grid.jpg")
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "docs" / "cover_grid_manifest.json"
    )
    parser.add_argument("--tile", type=int, default=420)
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
    for query_index, category in enumerate(PROMPTS):
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

    tile = args.tile
    label_height = 52
    canvas = Image.new("RGB", (tile * 3, (tile + label_height) * 3), "white")
    font = ImageFont.load_default(size=20)
    for index, item in enumerate(chosen):
        source_path = args.image_dir / item["file_name"]
        with Image.open(source_path) as source:
            image = ImageOps.fit(source.convert("RGB"), (tile, tile), method=Image.Resampling.LANCZOS)
        x = (index % 3) * tile
        y = (index // 3) * (tile + label_height)
        canvas.paste(image, (x, y))
        draw = ImageDraw.Draw(canvas)
        draw.text((x + 10, y + tile + 13), item["category"], fill="black", font=font)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output, format="JPEG", quality=90, optimize=True)
    args.manifest.write_text(
        json.dumps(
            {
                "purpose": "Kaggle dataset cover",
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
