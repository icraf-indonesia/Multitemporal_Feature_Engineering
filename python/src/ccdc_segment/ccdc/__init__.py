"""Stage 2 & 3 sensor-agnostic CCDC temporal segmentation subpackage."""

from __future__ import annotations

from ccdc_segment.ccdc.fit import load_ccdc_mosaic, prepare_ccdc_for_export, run_ccdc
from ccdc_segment.ccdc.model import CCDCModel
from ccdc_segment.ccdc.reconstruct import (
    fill_isolated,
    get_harmonics,
    get_multi_year_stacks,
    get_synthetic_stack,
    nearest_segment,
)
from ccdc_segment.ccdc.specs import (
    CCDCParams,
    CCDCProfile,
    ReflectanceBounds,
    SegmentMatch,
)
from ccdc_segment.ccdc.stability import stable_in_period

__all__ = [
    "CCDCModel",
    "CCDCParams",
    "CCDCProfile",
    "ReflectanceBounds",
    "SegmentMatch",
    "fill_isolated",
    "get_harmonics",
    "get_multi_year_stacks",
    "get_synthetic_stack",
    "load_ccdc_mosaic",
    "nearest_segment",
    "prepare_ccdc_for_export",
    "run_ccdc",
    "stable_in_period",
]
