"""Unit tests for ``ccdc_segment.ccdc.reconstruct`` and ``CCDCModel``."""

from __future__ import annotations

import pytest
from conftest import FakeEE

from ccdc_segment.ccdc import (
    CCDCModel,
    CCDCParams,
    CCDCProfile,
    fill_isolated,
    get_harmonics,
    get_multi_year_stacks,
    get_synthetic_stack,
    nearest_segment,
)


def test_nearest_segment_returns_segment_match(fake_ee: FakeEE) -> None:
    ccdc_img = fake_ee.Image("CCDC")
    seg = nearest_segment(ccdc_img, 2025.65)
    assert seg.idx.kind == "arrayGet"
    assert seg.gap.kind == "rename"
    assert seg.gap.args == ("gap_years",)


def test_fill_isolated_uses_3x3_focal_median_and_validates_neighbors(fake_ee: FakeEE) -> None:
    img = fake_ee.Image("STACK")
    fill_isolated(img, min_neighbors=5)
    assert any(name == "focalMedian" and args == (1, "square", "pixels") for name, args, _ in fake_ee.calls)
    assert any(name == "gte" and args == (5,) for name, args, _ in fake_ee.calls)

    with pytest.raises(ValueError, match="min_neighbors"):
        fill_isolated(img, min_neighbors=9)


def test_get_synthetic_stack_respects_profile_and_diagnostics_flag(fake_ee: FakeEE) -> None:
    ccdc_img = fake_ee.Image("CCDC_LEGACY")
    profile = CCDCProfile.landsat_legacy()

    # With diagnostics=True (default) and fill_holes=True
    res = get_synthetic_stack(ccdc_img, 2025.65, profile=profile)
    assert res.kind == "addBands"
    selected_bands = [args[0] for name, args, _ in fake_ee.calls if name == "select"]
    for b in ("BLUE_coefs", "GREEN_coefs", "RED_coefs", "NIR_coefs", "SWIR1_coefs", "SWIR2_coefs"):
        assert b in selected_bands
    assert any(name == "rename" and args == ("synth_valid",) for name, args, _ in fake_ee.calls)
    assert any(name == "focalMedian" for name, _, _ in fake_ee.calls)

    # With include_diagnostics=False and fill_holes=False
    fake_ee.calls.clear()
    res_no_diag = get_synthetic_stack(
        ccdc_img,
        2025.65,
        profile=CCDCProfile.google_global(),
        fill_holes=False,
        include_diagnostics=False,
    )
    assert res_no_diag.kind == "updateMask"
    assert not any(name == "focalMedian" for name, _, _ in fake_ee.calls)
    assert any(name == "divide" and args == (1.0,) for name, args, _ in fake_ee.calls)


def test_get_harmonics_extracts_first_order_and_respects_case(fake_ee: FakeEE) -> None:
    ccdc_img = fake_ee.Image("CCDC_LEGACY")
    get_harmonics(ccdc_img, 2025.50, profile=CCDCProfile.landsat_legacy(), bands=("nir", "red"))

    renames = [args[0] for name, args, _ in fake_ee.calls if name == "rename"]
    assert "NIR_amp" in renames
    assert "NIR_phase" in renames
    assert "RED_amp" in renames
    assert "RED_phase" in renames

    # Explicit output_case override
    fake_ee.calls.clear()
    get_harmonics(
        ccdc_img,
        2025.50,
        profile=CCDCProfile.landsat_legacy(),
        bands=("nir",),
        output_case="lower",
    )
    renames = [args[0] for name, args, _ in fake_ee.calls if name == "rename"]
    assert "nir_amp" in renames
    assert "nir_phase" in renames


def test_get_multi_year_stacks_and_ccdc_model_facade(fake_ee: FakeEE) -> None:
    col = fake_ee.ImageCollection("S2_MONTHLY")
    model = CCDCModel.fit(col, params=CCDCParams.sentinel2(), profile=CCDCProfile.standard())
    assert len(fake_ee.ccdc_calls) == 1

    series = model.synthetic_series([2020, 2025], season_fraction=0.65, include_diagnostics=False)
    assert list(series.keys()) == [2020, 2025]

    harm = model.harmonics(2025.50)
    assert harm.kind == "updateMask"

    trimmed = model.prepare_for_export()
    assert trimmed.kind == "select"

    with pytest.raises(ValueError, match="season_fraction"):
        get_multi_year_stacks(model.image, [2025], season_fraction=1.2)
