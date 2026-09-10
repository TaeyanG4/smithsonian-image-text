import numpy as np

from smithsonian_image_text.embeddings import l2_normalize


def test_l2_normalize_rows():
    values = np.array([[3.0, 4.0], [1.0, 0.0]], dtype=np.float32)
    result = l2_normalize(values)
    assert np.allclose(np.linalg.norm(result, axis=1), 1.0)


def test_l2_normalize_rejects_non_matrix():
    values = np.array([1.0, 2.0], dtype=np.float32)
    try:
        l2_normalize(values)
    except ValueError as exc:
        assert "2-dimensional" in str(exc)
    else:
        raise AssertionError("expected ValueError")
