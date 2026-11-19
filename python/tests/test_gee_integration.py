"""Live Google Earth Engine smoke tests (skipped by default).

Run explicitly when GEE credentials are available:

    RUN_GEE_TESTS=1 pytest -m gee
"""

from __future__ import annotations

import os

import ee
import pytest

from ccdc_segment.ccdc import CCDCModel, CCDCProfile
from ccdc_segment.inputs import composite, landsat, s2

pytestmark = [
    pytest.mark.gee,
    pytest.mark.skipif(
        os.environ.get("RUN_GEE_TESTS") != "1",
        reason="Live GEE smoke tests are disabled; set RUN_GEE_TESTS=1 to run.",
    ),
]


@pytest.fixture(scope="module")
def initialized_ee() -> ee.Geometry:
    project = os.environ.get("GEE_PROJECT")
    if project:
        ee.Initialize(project=project)
    else:
        ee.Initialize()
    # Small 0.05-degree box near Dili, Timor-Leste for fast metadata/band checks
    return ee.Geometry.Rectangle([125.55, -8.60, 125.60, -8.55])


def test_live_s2_and_landsat_input_schemas(initialized_ee: ee.Geometry) -> None:
    expected = ["blue", "green", "red", "nir", "swir1", "swir2"]

    s2_col = s2.get_collection(initialized_ee, "2024-06-01", "2024-09-01", reflectance_scale=1.0)
    s2_comp = composite.seasonal_composite(s2_col, 2024, 6, 8)
    assert s2_comp.bandNames().getInfo() == expected

    ls_col = landsat.get_collection(
        initialized_ee,
        "2024-06-01",
        "2024-09-01",
        sensors=("L8", "L9"),
        reflectance_scale=1.0,
    )
    assert ls_col.first().bandNames().getInfo() == expected


def test_live_google_global_ccdc_reconstruction(initialized_ee: ee.Geometry) -> None:
    model = CCDCModel.from_tiles(
        "GOOGLE/GLOBAL_CCDC/V1",
        aoi=initialized_ee,
        profile=CCDCProfile.google_global(),
        is_collection=True,
    )
    synth = model.synthetic(2018.65, include_diagnostics=True)
    assert synth.bandNames().getInfo() == [
        "blue",
        "green",
        "red",
        "nir",
        "swir1",
        "swir2",
        "gap_years",
        "synth_valid",
    ]
    harm = model.harmonics(2018.50, bands=("nir",))
    assert harm.bandNames().getInfo() == ["nir_amp", "nir_phase"]
