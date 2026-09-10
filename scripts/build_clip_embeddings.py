#!/usr/bin/env python3
"""Build optional normalized CLIP image embeddings keyed by stable release image_id."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from smithsonian_image_text.embeddings import sha256_file  # noqa: E402


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
        "--image-dir", type=Path, default=ROOT / "data" / "images" / "production"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "interim" / "clip_embeddings.parquet",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data" / "audits" / "clip_embeddings_manifest.json",
    )
    parser.add_argument("--model-id", default="openai/clip-vit-base-patch32")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")
    if args.output.exists() and not args.force:
        raise SystemExit(f"Output exists; use --force: {args.output}")
    if args.manifest.exists() and not args.force:
        raise SystemExit(f"Manifest exists; use --force: {args.manifest}")

    try:
        import torch
        import transformers
        from transformers import CLIPImageProcessor, CLIPModel
    except ImportError as exc:
        raise SystemExit("Install the embeddings extra: pip install -e '.[data,embeddings]'") from exc

    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise SystemExit("CUDA requested but torch.cuda.is_available() is false")

    table = pq.read_table(
        args.metadata,
        columns=["image_id", "file_name", "object_id", "split", "category"],
    )
    rows = table.to_pylist()
    if not rows:
        raise SystemExit("Metadata contains no rows")

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    model = CLIPModel.from_pretrained(args.model_id).eval().to(args.device)
    processor = CLIPImageProcessor.from_pretrained(args.model_id)
    dimension = int(model.config.projection_dim)
    commit_hash = getattr(model.config, "_commit_hash", None)
    vectors = np.empty((len(rows), dimension), dtype=np.float16)

    started = time.perf_counter()
    for start in range(0, len(rows), args.batch_size):
        batch = rows[start : start + args.batch_size]
        images: list[Image.Image] = []
        try:
            for row in batch:
                path = args.image_dir / str(row["file_name"])
                with Image.open(path) as source:
                    images.append(source.convert("RGB"))
            inputs = processor(images=images, return_tensors="pt")
            inputs = {key: value.to(args.device, non_blocking=True) for key, value in inputs.items()}
            with torch.inference_mode():
                if args.device.startswith("cuda"):
                    with torch.autocast(device_type="cuda", dtype=torch.float16):
                        features = model.get_image_features(**inputs)
                else:
                    features = model.get_image_features(**inputs)
                features = features.float()
                features = features / features.norm(dim=1, keepdim=True).clamp_min(1e-12)
            vectors[start : start + len(batch)] = features.cpu().numpy().astype(np.float16)
        finally:
            for image in images:
                image.close()
        if start == 0 or (start + len(batch)) % 2048 < args.batch_size:
            print(f"embeddings {start + len(batch)}/{len(rows)}", flush=True)

    norms = np.linalg.norm(vectors.astype(np.float32), axis=1)
    if not np.isfinite(vectors).all():
        raise RuntimeError("Non-finite CLIP embedding encountered")
    if float(np.max(np.abs(norms - 1.0))) > 0.01:
        raise RuntimeError("CLIP embeddings are not sufficiently L2-normalized")

    flat = pa.array(vectors.reshape(-1), type=pa.float16())
    embedding_array = pa.FixedSizeListArray.from_arrays(flat, dimension)
    output_table = pa.table(
        {
            "image_id": table["image_id"],
            "file_name": table["file_name"],
            "object_id": table["object_id"],
            "split": table["split"],
            "category": table["category"],
            "embedding": embedding_array,
        }
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=args.output.parent, prefix=args.output.name + ".", suffix=".partial", delete=False
    ) as temp:
        temp_path = Path(temp.name)
    try:
        pq.write_table(output_table, temp_path, compression="zstd")
        temp_path.replace(args.output)
    finally:
        temp_path.unlink(missing_ok=True)

    elapsed = time.perf_counter() - started
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifact_type": "optional_clip_image_embeddings",
        "source_metadata": str(args.metadata),
        "source_metadata_sha256": sha256_file(args.metadata),
        "image_count": len(rows),
        "model_id": args.model_id,
        "model_revision": commit_hash,
        "embedding_dimension": dimension,
        "embedding_dtype": "float16",
        "l2_normalized": True,
        "preprocessing": processor.to_dict(),
        "transformers_version": transformers.__version__,
        "torch_version": torch.__version__,
        "device": args.device,
        "batch_size": args.batch_size,
        "elapsed_seconds": elapsed,
        "rows_per_second": len(rows) / elapsed if elapsed else None,
        "output": str(args.output),
        "output_bytes": args.output.stat().st_size,
        "output_sha256": sha256_file(args.output),
        "norm_min": float(norms.min()),
        "norm_max": float(norms.max()),
        "norm_mean": float(norms.mean()),
    }
    args.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
