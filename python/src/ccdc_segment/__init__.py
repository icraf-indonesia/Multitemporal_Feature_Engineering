"""``ccdc_segment``: Modular Google Earth Engine Python API library for CCDC.

Provides stage-based optical harmonization (Landsat 5/7/8/9 and Sentinel-2 +
Cloud Score+), monthly/seasonal compositing, sensor-agnostic CCDC fitting,
trend-clamped synthetic reflectance reconstruction, harmonic phenology metrics,
multi-epoch stability filtering, and tiled batch export orchestration.
"""

from __future__ import annotations

from ccdc_segment import ccdc, config, constants, export, inputs
from ccdc_segment.ccdc import (
    CCDCModel,
    CCDCParams,
    CCDCProfile,
    ReflectanceBounds,
    SegmentMatch,
    fill_isolated,
    get_harmonics,
    get_multi_year_stacks,
    get_synthetic_stack,
    load_ccdc_mosaic,
    nearest_segment,
    prepare_ccdc_for_export,
    run_ccdc,
    stable_in_period,
)
from ccdc_segment.config import ExportDefaults, ProjectConfig, SeasonFractions
from ccdc_segment.export import (
    ExportTaskRecord,
    asset_exists,
    export_ccdc_tiles,
    export_to_asset,
    export_to_drive,
    make_tile_grid,
)
from ccdc_segment.inputs import (
    LandsatOptions,
    Sentinel2Options,
    get_optical_collection,
    seasonal_composite,
    to_monthly_median,
)

__version__ = "0.1.0"

__all__ = [
    "CCDCModel",
    "CCDCParams",
    "CCDCProfile",
    "ExportDefaults",
    "ExportTaskRecord",
    "LandsatOptions",
    "ProjectConfig",
    "ReflectanceBounds",
    "SeasonFractions",
    "SegmentMatch",
    "Sentinel2Options",
    "__version__",
    "asset_exists",
    "ccdc",
    "config",
    "constants",
    "export",
    "export_ccdc_tiles",
    "export_to_asset",
    "export_to_drive",
    "fill_isolated",
    "get_harmonics",
    "get_multi_year_stacks",
    "get_optical_collection",
    "get_synthetic_stack",
    "inputs",
    "load_ccdc_mosaic",
    "make_tile_grid",
    "nearest_segment",
    "prepare_ccdc_for_export",
    "run_ccdc",
    "seasonal_composite",
    "stable_in_period",
    "to_monthly_median",
]
