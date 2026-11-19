"""Landsat 5/7/8/9 Collection 2 Level-2 optical input preparation.

Harmonizes TM, ETM+, OLI, and OLI-2 surface reflectance acquisitions to the
canonical six-band lowercase schema (``blue``, ``green``, ``red``, ``nir``,
``swir1``, ``swir2``) with configurable QA_PIXEL bitmasking and reflectance
scaling.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

import ee

from ccdc_segment.constants import DEFAULT_CCDC_REFLECTANCE_SCALE, OPTICAL_BANDS

LandsatSensor = Literal["L5", "L7", "L8", "L9"]

_TM_ETM_BANDS: list[str] = ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"]
_OLI_BANDS: list[str] = ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"]

#: Registry mapping sensor codes to (GEE ImageCollection ID, source SR band names).
LANDSAT_COLLECTIONS: dict[LandsatSensor, tuple[str, list[str]]] = {
    "L5": ("LANDSAT/LT05/C02/T1_L2", _TM_ETM_BANDS),
    "L7": ("LANDSAT/LE07/C02/T1_L2", _TM_ETM_BANDS),
    "L8": ("LANDSAT/LC08/C02/T1_L2", _OLI_BANDS),
    "L9": ("LANDSAT/LC09/C02/T1_L2", _OLI_BANDS),
}

# USGS Collection 2 Level-2 surface reflectance linear conversion factors
_C2_SCALE: float = 0.0000275
_C2_OFFSET: float = -0.2


@dataclass(frozen=True)
class LandsatOptions:
    """Configuration for Landsat Collection 2 Level-2 ingestion and QA masking.

    Parameters
    ----------
    reflectance_scale : float, default 10000.0
        Output surface reflectance multiplier. Use ``10000.0`` for CCDC fitting
        (calibrated for ``lambda=20``) or ``1.0`` for direct 0..1 composites.
    sensors : tuple[str, ...], default ('L5', 'L7', 'L8', 'L9')
        Subset of Landsat missions to merge.
    mask_fill : bool, default True
        Mask ``QA_PIXEL`` bit 0 (fill and Landsat 7 SLC-off scanline gaps).
    mask_cloud : bool, default True
        Mask ``QA_PIXEL`` bit 1 (dilated cloud) and bit 3 (cloud).
    mask_shadow : bool, default True
        Mask ``QA_PIXEL`` bit 4 (cloud shadow).
    mask_snow : bool, default True
        Mask ``QA_PIXEL`` bit 5 (snow).
    """

    reflectance_scale: float = DEFAULT_CCDC_REFLECTANCE_SCALE
    sensors: tuple[LandsatSensor, ...] = ("L5", "L7", "L8", "L9")
    mask_fill: bool = True
    mask_cloud: bool = True
    mask_shadow: bool = True
    mask_snow: bool = True

    def __post_init__(self) -> None:
        if self.reflectance_scale <= 0:
            raise ValueError(
                f"LandsatOptions.reflectance_scale must be > 0, got {self.reflectance_scale!r}."
            )
        normalized = tuple(s.upper() for s in self.sensors)
        if not normalized:
            raise ValueError("LandsatOptions.sensors must include at least one sensor.")
        invalid = [s for s in normalized if s not in LANDSAT_COLLECTIONS]
        if invalid:
            raise ValueError(
                f"Unsupported Landsat sensor(s): {invalid!r}. "
                f"Expected subset of {list(LANDSAT_COLLECTIONS)}."
            )
        object.__setattr__(self, "sensors", normalized)


def _mask_and_scale(
    img: ee.Image,
    source_bands: list[str],
    opts: LandsatOptions,
) -> ee.Image:
    """Apply QA_PIXEL bitmasking and Collection 2 linear SR scaling to a single scene."""
    qa = img.select("QA_PIXEL")
    mask = ee.Image(1)

    if opts.mask_fill:
        mask = mask.And(qa.bitwiseAnd(1).eq(0))  # Bit 0: Fill / SLC-off
    if opts.mask_cloud:
        mask = mask.And(qa.bitwiseAnd(1 << 1).eq(0))  # Bit 1: Dilated cloud
        mask = mask.And(qa.bitwiseAnd(1 << 3).eq(0))  # Bit 3: Cloud
    if opts.mask_shadow:
        mask = mask.And(qa.bitwiseAnd(1 << 4).eq(0))  # Bit 4: Cloud shadow
    if opts.mask_snow:
        mask = mask.And(qa.bitwiseAnd(1 << 5).eq(0))  # Bit 5: Snow

    sr_bands = (
        img.select(source_bands, list(OPTICAL_BANDS))
        .multiply(_C2_SCALE)
        .add(_C2_OFFSET)
        .multiply(opts.reflectance_scale)
    )

    return sr_bands.updateMask(mask).copyProperties(img, ["system:time_start"])


def get_collection(
    roi: ee.Geometry,
    start_date: str = "2000-01-01",
    end_date: str = "2025-12-31",
    *,
    options: LandsatOptions | None = None,
    reflectance_scale: float | None = None,
    sensors: Sequence[str] | None = None,
    mask_fill: bool | None = None,
    mask_cloud: bool | None = None,
    mask_shadow: bool | None = None,
    mask_snow: bool | None = None,
) -> ee.ImageCollection:
    """Build a harmonized, cloud-masked Landsat 5/7/8/9 Collection 2 L2 time series.

    Parameters
    ----------
    roi : ee.Geometry
        Region of interest used to spatially filter collections.
    start_date : str, default '2000-01-01'
        Inclusive start date (``YYYY-MM-DD``).
    end_date : str, default '2025-12-31'
        Exclusive end date (``YYYY-MM-DD``).
    options : LandsatOptions, optional
        Base option bundle. Individual keyword arguments override fields on
        ``options`` when explicitly provided.
    reflectance_scale : float, optional
        Override for :attr:`LandsatOptions.reflectance_scale`.
    sensors : Sequence[str], optional
        Override for :attr:`LandsatOptions.sensors`.
    mask_fill, mask_cloud, mask_shadow, mask_snow : bool, optional
        Overrides for the corresponding ``QA_PIXEL`` masking flags.

    Returns
    -------
    ee.ImageCollection
        Merged six-band optical collection with ``system:time_start`` preserved.
    """
    base = options if options is not None else LandsatOptions()
    overrides = {}
    if reflectance_scale is not None:
        overrides["reflectance_scale"] = reflectance_scale
    if sensors is not None:
        overrides["sensors"] = tuple(sensors)
    if mask_fill is not None:
        overrides["mask_fill"] = mask_fill
    if mask_cloud is not None:
        overrides["mask_cloud"] = mask_cloud
    if mask_shadow is not None:
        overrides["mask_shadow"] = mask_shadow
    if mask_snow is not None:
        overrides["mask_snow"] = mask_snow

    opts = replace(base, **overrides) if overrides else base

    collections: list[ee.ImageCollection] = []
    for sensor_code in opts.sensors:
        collection_id, source_bands = LANDSAT_COLLECTIONS[sensor_code]
        col = (
            ee.ImageCollection(collection_id)
            .filterBounds(roi)
            .filterDate(start_date, end_date)
            .map(lambda img, sb=source_bands: _mask_and_scale(img, sb, opts))
        )
        collections.append(col)

    merged = collections[0]
    for col in collections[1:]:
        merged = merged.merge(col)
    return merged
