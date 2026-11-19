"""Unit tests for ``ccdc_segment.inputs`` (Landsat, Sentinel-2, and composites)."""

from __future__ import annotations

import pytest
from conftest import FakeEE

from ccdc_segment.inputs import (
    LandsatOptions,
    Sentinel2Options,
    composite,
    get_optical_collection,
    landsat,
    s2,
)


def test_landsat_collection_merges_all_four_sensors_and_masks_qa(fake_ee: FakeEE) -> None:
    roi = fake_ee.Geometry.Rectangle([125.0, -9.0, 126.0, -8.5])
    landsat.get_collection(roi, "2000-01-01", "2025-12-31")

    col_ids = [
        args[0]
        for name, args, _ in fake_ee.calls
        if name == "ee.ImageCollection" and args and isinstance(args[0], str)
    ]
    assert col_ids == [
        "LANDSAT/LT05/C02/T1_L2",
        "LANDSAT/LE07/C02/T1_L2",
        "LANDSAT/LC08/C02/T1_L2",
        "LANDSAT/LC09/C02/T1_L2",
    ]

    # Verify QA bitmasks: bits 0, 1, 3, 4, 5
    bit_args = [args[0] for name, args, _ in fake_ee.calls if name == "bitwiseAnd"]
    for bit in (1, 1 << 1, 1 << 3, 1 << 4, 1 << 5):
        assert bit in bit_args

    # Verify Collection 2 scaling and 10000 multiplier
    mult_args = [args[0] for name, args, _ in fake_ee.calls if name == "multiply"]
    assert 0.0000275 in mult_args
    assert 10000.0 in mult_args


def test_landsat_sensor_subset_and_validation(fake_ee: FakeEE) -> None:
    roi = fake_ee.Geometry.Rectangle([125.0, -9.0, 126.0, -8.5])
    landsat.get_collection(roi, "2020-01-01", "2025-12-31", sensors=("L8", "L9"), reflectance_scale=1.0)

    col_ids = [
        args[0]
        for name, args, _ in fake_ee.calls
        if name == "ee.ImageCollection" and args and isinstance(args[0], str)
    ]
    assert col_ids == ["LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2"]

    with pytest.raises(ValueError, match="Unsupported Landsat sensor"):
        LandsatOptions(sensors=("L4",))  # type: ignore[arg-type]


def test_s2_collection_links_cloud_score_plus_and_skips_unity_multiply(fake_ee: FakeEE) -> None:
    roi = fake_ee.Geometry.Rectangle([125.0, -9.0, 126.0, -8.5])
    s2.get_collection(roi, "2020-01-01", "2025-12-31", reflectance_scale=10000.0)

    assert any(
        name == "linkCollection" and args[1] == ["cs_cdf"]
        for name, args, _ in fake_ee.calls
    )
    # At native 10000 scale, multiplier == 1.0 so no extra multiply call is needed
    assert not any(name == "multiply" for name, _, _ in fake_ee.calls)


def test_s2_direct_reflectance_scale_multiplies_by_1e_minus_4(fake_ee: FakeEE) -> None:
    roi = fake_ee.Geometry.Rectangle([125.0, -9.0, 126.0, -8.5])
    s2.get_collection(roi, "2024-01-01", "2025-12-31", reflectance_scale=1.0, clear_threshold=0.55)

    assert any(
        name == "multiply" and args == (pytest.approx(1e-4),)
        for name, args, _ in fake_ee.calls
    )
    assert any(name == "gte" and args == (0.55,) for name, args, _ in fake_ee.calls)

    with pytest.raises(ValueError, match="clear_threshold"):
        Sentinel2Options(clear_threshold=1.5)


def test_get_optical_collection_dispatcher(fake_ee: FakeEE) -> None:
    roi = fake_ee.Geometry.Rectangle([0, 0, 1, 1])
    get_optical_collection("s2", roi, "2024-01-01", "2025-01-01")
    get_optical_collection("landsat", roi, "2024-01-01", "2025-01-01", sensors=("L9",))

    with pytest.raises(ValueError, match="Unsupported optical sensor"):
        get_optical_collection("modis", roi, "2024-01-01", "2025-01-01")  # type: ignore[arg-type]


def test_to_monthly_median_drops_empty_months(fake_ee: FakeEE) -> None:
    col = fake_ee.ImageCollection("DUMMY")
    composite.to_monthly_median(col, "2024-01-01", "2024-12-31")

    assert any(name == "ee.ImageCollection.fromImages" for name, _, _ in fake_ee.calls)
    assert any(name == "ee.Filter.gt" and args == ("n", 0) for name, args, _ in fake_ee.calls)
    assert any(
        name == "advance" and args == (15, "day")
        for name, args, _ in fake_ee.calls
    )


def test_seasonal_composite_handles_december_end_month_and_wrap_around(fake_ee: FakeEE) -> None:
    col = fake_ee.ImageCollection("DUMMY")

    # End month == 12 must NOT call ee.Date.fromYMD(2025, 13, 1); FakeDate raises on month 13
    composite.seasonal_composite(col, 2025, 10, 12, reducer="median")
    assert any(
        name == "ee.Date.fromYMD" and args == (2025, 12, 1)
        for name, args, _ in fake_ee.calls
    )
    assert any(name == "advance" and args == (1, "month") for name, args, _ in fake_ee.calls)

    # Wrap-around season (Dec -> Apr) spans year-1 to year + calendarRange filter
    fake_ee.calls.clear()
    composite.seasonal_composite(col, 2025, 12, 4, reducer=25)
    assert any(
        name == "ee.Date.fromYMD" and args == (2024, 12, 1)
        for name, args, _ in fake_ee.calls
    )
    assert any(
        name == "ee.Filter.calendarRange" and args == (12, 4, "month")
        for name, args, _ in fake_ee.calls
    )
    assert any(
        name == "ee.Reducer.percentile" and args == ([25],)
        for name, args, _ in fake_ee.calls
    )

    with pytest.raises(ValueError, match="start_month"):
        composite.seasonal_composite(col, 2025, 0, 5)
    with pytest.raises(TypeError, match="not bool"):
        composite.seasonal_composite(col, 2025, 6, 10, reducer=True)  # type: ignore[arg-type]
