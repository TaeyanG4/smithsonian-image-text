from scripts.qa_images import HammingBKTree


def test_hamming_bk_tree_finds_near_hashes():
    tree = HammingBKTree()
    tree.add(0b0000, 1)
    tree.add(0b1111, 2)
    found = sorted(tree.query(0b0001, 1))
    assert found == [(1, 1)]
