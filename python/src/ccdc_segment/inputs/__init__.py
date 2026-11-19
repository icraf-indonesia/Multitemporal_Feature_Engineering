"""Stage 1 optical ingestion and temporal compositing subpackage."""

from __future__ import annotations

from typing import Any, Literal

import ee

from ccdc_segment.inputs import composite, landsat, s2
from ccdc_segment.inputs.composite import seasonal_composite, to_monthly_median
from ccdc_segment.inputs.landsat import LandsatOptions
from ccdc_segment.inputs.s2 import Sentinel2Options

OpticalSensor = Literal["landsat", "sentinel2", "s2"]


def get_optical_collection(
    sensor: OpticalSensor,
    roi: ee.Geometry,
    start_date: str,
    end_date: str,
    **kwargs: Any,
) -> ee.ImageCollection:
    """Dispatch to the appropriate sensor harmonization module.

    Parameters
    ----------
    sensor : {'landsat', 'sentinel2', 's2'}
        Optical sensor family to ingest.
    roi : ee.Geometry
        Study-area geometry.
    start_date : str
        Inclusive start date (``YYYY-MM-DD``).
    end_date : str
        Exclusive end date (``YYYY-MM-DD``).
    **kwargs : Any
        Sensor-specific keyword arguments forwarded to
        :func:`landsat.get_collection` or :func:`s2.get_collection`.

    Returns
    -------
    ee.ImageCollection
        Harmonized six-band optical collection.
    """
    normalized = sensor.strip().lower()
    if normalized == "landsat":
        return landsat.get_collection(roi, start_date, end_date, **kwargs)
    if normalized in ("sentinel2", "s2"):
        return s2.get_collection(roi, start_date, end_date, **kwargs)
    raise ValueError(
        f"Unsupported optical sensor {sensor!r}; expected 'landsat', 'sentinel2', or 's2'."
    )


__all__ = [
    "LandsatOptions",
    "Sentinel2Options",
    "composite",
    "get_optical_collection",
    "landsat",
    "s2",
    "seasonal_composite",
    "to_monthly_median",
]
