"""Unit tests for ``ccdc_segment.ccdc.specs`` and ``ccdc_segment.ccdc.fit``."""

from __future__ import annotations

import pytest
from conftest import FakeEE

from ccdc_segment.ccdc import (
    CCDCParams,
    CCDCProfile,
    ReflectanceBounds,
    load_ccdc_mosaic,
    prepare_ccdc_for_export,
    run_ccdc,
)


def test_ccdc_params_presets_and_zero_lambda(fake_ee: FakeEE) -> None:
    col = fake_ee.ImageCollection("DUMMY")

    ls_params = CCDCParams.landsat()
    assert ls_params.breakpoint_bands == ("green", "red", "nir", "swir1", "swir2")
    assert ls_params.tmask_bands == ("green", "swir1")
    ee_dict = ls_params.to_ee_params(col)
    assert ee_dict["lambda"] == 20.0
    assert ee_dict["tmaskBands"] == ["green", "swir1"]

    # Explicit lambda_=0 must NOT fall back to 20 (fixes JS falsy bug)
    s2_zero = CCDCParams.sentinel2(lambda_=0.0)
    run_ccdc(col, params=s2_zero)
    assert len(fake_ee.ccdc_calls) == 1
    assert fake_ee.ccdc_calls[0]["lambda"] == 0.0
    assert "tmaskBands" not in fake_ee.ccdc_calls[0]
    assert fake_ee.ccdc_calls[0]["breakpointBands"] == ["green", "red", "nir", "swir1"]


def test_ccdc_params_validation() -> None:
    with pytest.raises(ValueError, match="breakpoint_bands"):
        CCDCParams(breakpoint_bands=())
    with pytest.raises(ValueError, match="tmask_bands"):
        CCDCParams(tmask_bands=("green",))
    with pytest.raises(ValueError, match="chi_square_probability"):
        CCDCParams(chi_square_probability=1.0)
    with pytest.raises(ValueError, match="lambda_"):
        CCDCParams(lambda_=-1.0)


def test_ccdc_profile_presets_and_band_naming() -> None:
    std = CCDCProfile.standard()
    assert std.coef_band_name("blue") == "blue_coefs"
    assert std.harmonic_band_names("nir") == ("nir_amp", "nir_phase")

    legacy = CCDCProfile.landsat_legacy()
    assert legacy.coef_band_name("blue") == "BLUE_coefs"
    assert legacy.harmonic_band_names("nir") == ("NIR_amp", "NIR_phase")
    assert legacy.coef_scale == 10000.0

    global_prof = CCDCProfile.google_global()
    assert global_prof.coef_band_name("swir1") == "SWIR1_coefs"
    assert global_prof.harmonic_band_names("nir") == ("nir_amp", "nir_phase")
    assert global_prof.coef_scale == 1.0

    with pytest.raises(ValueError, match="min"):
        ReflectanceBounds(min=1.0, max=0.5)


def test_load_ccdc_mosaic_variants(fake_ee: FakeEE) -> None:
    aoi = fake_ee.Geometry.Rectangle([125.0, -9.0, 126.0, -8.5])

    # Sequence of tile asset IDs
    load_ccdc_mosaic(["tile_a", "tile_b"], aoi=aoi)
    assert any(name == "mosaic" for name, _, _ in fake_ee.calls)
    assert any(name == "clip" and args == (aoi,) for name, args, _ in fake_ee.calls)

    # Single collection string (e.g. GOOGLE/GLOBAL_CCDC/V1)
    fake_ee.calls.clear()
    load_ccdc_mosaic("GOOGLE/GLOBAL_CCDC/V1", aoi=aoi, is_collection=True)
    assert any(
        name == "ee.ImageCollection" and args == ("GOOGLE/GLOBAL_CCDC/V1",)
        for name, args, _ in fake_ee.calls
    )
    assert any(name == "filterBounds" and args == (aoi,) for name, args, _ in fake_ee.calls)

    with pytest.raises(ValueError, match="at least one"):
        load_ccdc_mosaic([])


def test_prepare_ccdc_for_export_trims_to_core_bands(fake_ee: FakeEE) -> None:
    ccdc_img = fake_ee.Image("RAW_CCDC")
    prepare_ccdc_for_export(ccdc_img)
    assert any(
        name == "select"
        and args == (["tStart", "tEnd", "tBreak", "changeProb", ".*_coefs"],)
        for name, args, _ in fake_ee.calls
    )
