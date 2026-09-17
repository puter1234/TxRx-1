from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from station.schema import Brand, Recipe, StationConfig
from station.storage import Store
from station.controller import Controller
from station.devices import ReplayIO


@pytest.fixture
def brand():
    return Brand(
        id="hazzys",
        name="헤지스",
        options=[
            {"key": "style", "label": "품번", "values": ["HUTS6C612"]},
            {"key": "color", "label": "색상", "values": ["N3", "BK"]},
            {"key": "size", "label": "사이즈", "values": ["095", "100"]},
        ],
        decoder={"kind": "hazzys_6bit_crc8"},
    )


@pytest.fixture
def recipe():
    return Recipe(
        brand_id="hazzys",
        brand_revision=1,
        targets={"style": "HUTS6C612", "color": "N3", "size": "095"},
        channels=["rfid"],
    )


@pytest.fixture
def controller(tmp_path, brand):
    store = Store(tmp_path)
    store.save_brand(brand.model_dump(), None, "test")
    c = Controller(store, ReplayIO(), StationConfig(disk_min_free_mb=100))
    yield c
    store.close()
