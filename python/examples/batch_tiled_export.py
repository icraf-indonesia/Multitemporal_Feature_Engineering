"""Example: Tiled CCDC batch export with auto-grid, dry-run preview, and skip_existing.

By default this script runs with ``start=False`` so no Earth Engine tasks are
submitted until you review the planned assets and flip ``START_EXPORTS = True``.
"""

from __future__ import annotations

from pathlib import Path

import ee

from ccdc_segment.ccdc import CCDCParams, run_ccdc
from ccdc_segment.config import ProjectConfig
from ccdc_segment.export import export_ccdc_tiles, make_tile_grid
from ccdc_segment.inputs import composite, s2

ASSET_PREFIX = "projects/your-project/assets/CCDC_S2_2020_2025"
START_EXPORTS = False


def main() -> None:
    ee.Initialize()

    cfg = ProjectConfig.from_json(Path(__file__).parent / "timor_leste.json")
    aoi = cfg.resolve_aoi()

    # 1. Build Stage 1 collection and Stage 2 monthly pre-composite
    s2_col = s2.get_collection(aoi, "2020-01-01", "2025-12-31", reflectance_scale=10000.0)
    monthly = composite.to_monthly_median(s2_col, "2020-01-01", "2025-12-31")
    ccdc_img = run_ccdc(monthly, params=CCDCParams.sentinel2())

    # 2. Generate a 0.5-degree rectangular tile grid filtered to tiles intersecting AOI
    tiles = make_tile_grid(aoi, tile_size_deg=0.5, prefix="tl", filter_intersecting=True)

    # 3. Trim to core bands, enforce '.default': 'sample' pyramiding, and skip existing assets
    records = export_ccdc_tiles(
        ccdc_img,
        asset_prefix=ASSET_PREFIX,
        tiles=tiles,
        scale=cfg.export.scale,
        crs=cfg.export.crs,
        trim_bands=True,
        skip_existing=True,
        start=START_EXPORTS,
    )

    for rec in records:
        print(f"[{rec.status:>16}] {rec.tile_name} -> {rec.asset_id}")


if __name__ == "__main__":
    main()
