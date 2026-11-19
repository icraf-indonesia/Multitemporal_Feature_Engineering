"""Shared library-level constants for ``ccdc_segment``.

All values here are sensor- or methodology-level defaults rather than
project-specific settings (study area AOIs, CRS, tile lists, and monsoon
season dates belong in :class:`ccdc_segment.config.ProjectConfig`).
"""

from __future__ import annotations

#: Canonical six-band lowercase optical surface reflectance schema.
OPTICAL_BANDS: tuple[str, ...] = ("blue", "green", "red", "nir", "swir1", "swir2")

#: Reflectance scaling factor calibrated for GEE CCDC LASSO ``lambda=20``.
DEFAULT_CCDC_REFLECTANCE_SCALE: float = 10000.0

#: Reflectance scaling factor for direct 0..1 surface reflectance composites.
DEFAULT_DIRECT_REFLECTANCE_SCALE: float = 1.0

#: Unified physical surface reflectance plausibility bounds (0..1 scale).
DEFAULT_REFLECTANCE_MIN: float = -0.05
DEFAULT_REFLECTANCE_MAX: float = 1.0

#: Default maximum allowable temporal distance (years) to the nearest CCDC segment.
DEFAULT_TOL_YEARS: float = 1.0

#: Default spatial resolutions (metres) by optical sensor profile.
DEFAULT_SCALES: dict[str, int] = {
    "s2": 20,
    "s2_fine": 10,
    "landsat": 30,
}

#: Default Earth Engine export pixel budget.
DEFAULT_MAX_PIXELS: int = 10**13

#: Regex/band selectors retained when trimming CCDC array outputs for asset export.
CCDC_CORE_EXPORT_BANDS: tuple[str, ...] = (
    "tStart",
    "tEnd",
    "tBreak",
    "changeProb",
    ".*_coefs",
)

#: Mandatory GEE pyramiding policy for array-valued CCDC image exports.
CCDC_PYRAMIDING_POLICY: dict[str, str] = {".default": "sample"}

#: Default GEE pyramiding policy for continuous optical/synthetic rasters.
DEFAULT_PYRAMIDING_POLICY: dict[str, str] = {".default": "mean"}
