import shutil
from pathlib import Path

from PIL import Image

from smithsonian_image_text.image_processing import (
    normalize_to_jpeg,
    perceptual_hash,
    phash_distance,
)


def test_perceptual_hash_is_deterministic_and_fixed_width():
    image = Image.new("RGB", (64, 64), "white")
    first = perceptual_hash(image)
    second = perceptual_hash(image)
    assert first == second
    assert len(first) == 16
    assert phash_distance(first, second) == 0


def test_normalize_to_jpeg_caps_side_and_hashes():
    scratch = Path("tmp_research") / "test_image_processing"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        source = scratch / "source.png"
        output = scratch / "final.jpg"
        image = Image.new("RGBA", (1024, 256), (20, 40, 60, 128))
        image.save(source)

        result = normalize_to_jpeg(source, output, max_side=512, quality=84)
        assert result.original_width == 1024
        assert result.original_height == 256
        assert result.original_format == "PNG"
        assert result.final_width == 512
        assert result.final_height == 128
        assert output.exists()
        assert output.stat().st_size == result.final_bytes
        assert len(result.sha256) == 64
        assert len(result.phash) == 16
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
