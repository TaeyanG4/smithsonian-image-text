import yaml

from smithsonian_image_text.categorization import assign_category


def config():
    with open("config/category_mapping.yaml", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def test_natural_history_unit_is_direct():
    assert assign_category({"unit_code": "NMNHBIRDS", "title": "Specimen"}, config()) == (
        "natural_history"
    )


def test_nasm_is_space_aviation():
    assert assign_category({"unit_code": "NASM", "title": "Engine"}, config()) == (
        "space_aviation"
    )


def test_nmah_science_keyword_override():
    row = {"unit_code": "NMAH", "title": "Patent model for an electrical machine"}
    assert assign_category(row, config()) == "science_technology"


def test_fsg_neolithic_object_maps_to_archaeology():
    row = {"unit_code": "FSG", "topics": "Late Neolithic period; jade"}
    assert assign_category(row, config()) == "archaeology"


def test_chndm_furniture_stays_design():
    row = {"unit_code": "CHNDM", "object_type": "Furniture; Decorative arts"}
    assert assign_category(row, config()) == "decorative_arts_design"
