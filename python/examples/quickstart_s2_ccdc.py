"""Quickstart: Sentinel-2 CCDC fitting, synthetic stacks, harmonics, and stability.

Run after authenticating Google Earth Engine (``earthengine authenticate``):

    python examples/quickstart_s2_ccdc.py
"""

from __future__ import annotations

from pathlib import Path

import ee

from ccdc_segment.ccdc import CCDCModel, CCDCParams, CCDCProfile
from ccdc_segment.config import ProjectConfig
from ccdc_segment.inputs import composite, s2


def main() -> None:
    ee.Initialize()

    # Load externalized project settings (keeps AOI, CRS, and monsoon dates out of library code)
    cfg_path = Path(__file__).parent / "timor_leste.json"
    cfg = ProjectConfig.from_json(cfg_path)
    aoi = cfg.resolve_aoi()

    # Stage 1: Sentinel-2 L2A + Cloud Score+ harmonized to 6 bands on 0..10000 scale for CCDC
    s2_col = s2.get_collection(
        aoi,
        start_date="2020-01-01",
        end_date="2025-12-31",
        clear_threshold=0.60,
        qa_band="cs_cdf",
        reflectance_scale=10000.0,
    )

    # Optional Stage 2 pre-aggregation: monthly medians reduce noise and EECU cost
    monthly = composite.to_monthly_median(s2_col, "2020-01-01", "2025-12-31")

    # Stage 2: Fit CCDC with Sentinel-2 preset (4 breakpoint bands, lambda=20)
    model = CCDCModel.fit(
        monthly,
        params=CCDCParams.sentinel2(),
        profile=CCDCProfile.standard(tol_years=cfg.tol_years),
    )

    # Stage 3: Reconstruct peak wet/dry synthetic surface reflectance (0..1 scale)
    wet_2025 = model.synthetic(cfg.seasons.date_for(2025, "wet"))
    dry_2025 = model.synthetic(cfg.seasons.date_for(2025, "dry"))

    # First-order annual harmonic amplitude & phase
    harm_2025 = model.harmonics(cfg.seasons.date_for(2025, "harm"))

    # Multi-epoch training sample stability mask (2020..2025)
    stable_2020_2025 = model.stable_in_period(2020.0, 2025.99)

    print("Wet 2025 bands:", wet_2025.bandNames().getInfo())
    print("Dry 2025 bands:", dry_2025.bandNames().getInfo())
    print("Harmonics bands:", harm_2025.bandNames().getInfo())
    print("Stability bands:", stable_2020_2025.bandNames().getInfo())


if __name__ == "__main__":
    main()
