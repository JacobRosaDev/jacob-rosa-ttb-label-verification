import pytest

from app.vision_service import MockVisionService
from app.models import ExtractedLabel


def test_mock_clear_label_returns_populated():
    svc = MockVisionService(scenario="clear")
    res = svc.extract(b"fakebytes")
    assert isinstance(res, ExtractedLabel)
    assert res.brand_name == "Ketel One"
    assert res.class_type == "Vodka"
    assert res.abv == 40.0


def test_mock_blurry_returns_all_none():
    svc = MockVisionService(scenario="blurry")
    res = svc.extract(b"fakebytes")
    # all fields should be None
    assert res.brand_name is None
    assert res.government_warning is None


def test_mock_partial_returns_some_fields():
    svc = MockVisionService(scenario="partial")
    res = svc.extract(b"fakebytes")
    assert res.brand_name == "Ketel One"
    assert res.net_contents == "750 mL"
    assert res.class_type is None
