"""Unit tests for ``ccdc_segment.ccdc.stability``."""

from __future__ import annotations

import pytest
from conftest import FakeEE

from ccdc_segment.ccdc import CCDCModel, CCDCProfile, stable_in_period


def test_stable_in_period_checks_breakpoints_symmetric_midpoints_and_drift(fake_ee: FakeEE) -> None:
    ccdc_img = fake_ee.Image("CCDC")
    res = stable_in_period(
        ccdc_img,
        start_year=2015.25,
        end_year=2025.99,
        profile=CCDCProfile.landsat_legacy(),
        apply_slope_filter=True,
        drift_bands=("nir", "swir1"),
        max_drift=0.12,
    )
    assert res.kind == "toByte"

    # Symmetric midpoints: floor(2015.25)+0.50 = 2015.50 and floor(2025.99)+0.50 = 2025.50
    ee_numbers = [args[0] for name, args, _ in fake_ee.calls if name == "ee.Number"]
    assert pytest.approx(2015.50) in ee_numbers
    assert pytest.approx(2025.50) in ee_numbers

    # Uppercase legacy drift bands selected
    selected = [args[0] for name, args, _ in fake_ee.calls if name == "select"]
    assert "NIR_coefs" in selected
    assert "SWIR1_coefs" in selected
    assert "tBreak" in selected
    assert "changeProb" in selected

    # Cumulative drift threshold checked
    assert any(name == "lte" and args == (0.12,) for name, args, _ in fake_ee.calls)


def test_stable_in_period_can_disable_slope_filter_and_validates_inputs(fake_ee: FakeEE) -> None:
    ccdc_img = fake_ee.Image("CCDC")
    model = CCDCModel(image=ccdc_img, profile=CCDCProfile.standard())
    model.stable_in_period(2020.0, 2025.0, apply_slope_filter=False)

    selected = [args[0] for name, args, _ in fake_ee.calls if name == "select"]
    assert "nir_coefs" not in selected
    assert "swir1_coefs" not in selected

    with pytest.raises(ValueError, match="end_year"):
        stable_in_period(ccdc_img, 2025.0, 2020.0)
    with pytest.raises(ValueError, match="max_drift"):
        stable_in_period(ccdc_img, 2020.0, 2025.0, max_drift=-0.01)
    with pytest.raises(ValueError, match="midpoint_offset"):
        stable_in_period(ccdc_img, 2020.0, 2025.0, midpoint_offset=1.0)
