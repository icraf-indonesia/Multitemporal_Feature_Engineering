"""Sentinel-2 L2A Harmonized optical input preparation with Cloud Score+.

Links ``COPERNICUS/S2_SR_HARMONIZED`` with
``GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED``, applies clear-sky masking, and
harmonizes bands to the canonical six-band lowercase schema.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

import ee

from ccdc_segment.constants import DEFAULT_CCDC_REFLECTANCE_SCALE, OPTICAL_BANDS

S2_SR_COLLECTION_ID: str = "COPERNICUS/S2_SR_HARMONIZED"
CLOUD_SCORE_PLUS_COLLECTION_ID: str = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"
S2_SOURCE_BANDS: list[str] = ["B2", "B3", "B4", "B8", "B11", "B12"]

CloudScoreBand = Literal["cs_cdf", "cs"]


@dataclass(frozen=True)
class Sentinel2Options:
    """Configuration for Sentinel-2 L2A ingestion and Cloud Score+ masking.

    Parameters
    ----------
    clear_threshold : float, default 0.60
        Minimum Cloud Score+ quality value retained as clear sky (typically
        ``0.50`` to ``0.65``).
    qa_band : {'cs_cdf', 'cs'}, default 'cs_cdf'
        Cloud Score+ quality band used for masking.
    reflectance_scale : float, default 10000.0
        Output reflectance scale. Native S2 L2A values are stored in
        ``0..10000``; use ``10000.0`` for CCDC fitting (zero rescaling overhead)
        or ``1.0`` for direct 0..1 surface reflectance composites.
    """

    clear_threshold: float = 0.60
    qa_band: CloudScoreBand = "cs_cdf"
    reflectance_scale: float = DEFAULT_CCDC_REFLECTANCE_SCALE

    def __post_init__(self) -> None:
        if not (0.0 <= self.clear_threshold <= 1.0):
            raise ValueError(
                "Sentinel2Options.clear_threshold must lie in [0.0, 1.0], "
                f"got {self.clear_threshold!r}."
            )
        if self.qa_band not in ("cs_cdf", "cs"):
            raise ValueError(
                f"Sentinel2Options.qa_band must be 'cs_cdf' or 'cs', got {self.qa_band!r}."
            )
        if self.reflectance_scale <= 0:
            raise ValueError(
                "Sentinel2Options.reflectance_scale must be > 0, "
                f"got {self.reflectance_scale!r}."
            )


def get_collection(
    roi: ee.Geometry,
    start_date: str = "2019-01-01",
    end_date: str = "2025-12-31",
    *,
    options: Sentinel2Options | None = None,
    clear_threshold: float | None = None,
    qa_band: CloudScoreBand | None = None,
    reflectance_scale: float | None = None,
) -> ee.ImageCollection:
    """Build a Cloud Score+ masked, harmonized Sentinel-2 L2A time series.

    Parameters
    ----------
    roi : ee.Geometry
        Region of interest used to spatially filter collections.
    start_date : str, default '2019-01-01'
        Inclusive start date (``YYYY-MM-DD``).
    end_date : str, default '2025-12-31'
        Exclusive end date (``YYYY-MM-DD``).
    options : Sentinel2Options, optional
        Base option bundle. Individual keyword arguments override fields on
        ``options`` when explicitly provided.
    clear_threshold : float, optional
        Override for :attr:`Sentinel2Options.clear_threshold`.
    qa_band : {'cs_cdf', 'cs'}, optional
        Override for :attr:`Sentinel2Options.qa_band`.
    reflectance_scale : float, optional
        Override for :attr:`Sentinel2Options.reflectance_scale`.

    Returns
    -------
    ee.ImageCollection
        Harmonized six-band optical collection with ``system:time_start`` preserved.
    """
    base = options if options is not None else Sentinel2Options()
    overrides = {}
    if clear_threshold is not None:
        overrides["clear_threshold"] = clear_threshold
    if qa_band is not None:
        overrides["qa_band"] = qa_band
    if reflectance_scale is not None:
        overrides["reflectance_scale"] = reflectance_scale

    opts = replace(base, **overrides) if overrides else base

    s2_col = (
        ee.ImageCollection(S2_SR_COLLECTION_ID)
        .filterBounds(roi)
        .filterDate(start_date, end_date)
    )
    cs_plus = (
        ee.ImageCollection(CLOUD_SCORE_PLUS_COLLECTION_ID)
        .filterBounds(roi)
        .filterDate(start_date, end_date)
    )

    s2_linked = s2_col.linkCollection(cs_plus, [opts.qa_band])
    multiplier = opts.reflectance_scale / 10000.0
    output_bands = list(OPTICAL_BANDS)

    def _mask_and_scale(img: ee.Image) -> ee.Image:
        cloud_mask = img.select(opts.qa_band).gte(opts.clear_threshold)
        scaled = img.select(S2_SOURCE_BANDS, output_bands)
        if multiplier != 1.0:
            scaled = scaled.multiply(multiplier)
        return scaled.updateMask(cloud_mask).copyProperties(img, ["system:time_start"])

    return s2_linked.map(_mask_and_scale)
