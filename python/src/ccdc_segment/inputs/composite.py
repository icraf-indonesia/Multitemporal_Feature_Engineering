"""Temporal compositing helpers for harmonized optical collections.

Supports both Stage 2 CCDC pre-aggregation (:func:`to_monthly_median`) and
Path A direct composite workflows (:func:`seasonal_composite`) without CCDC.
"""

from __future__ import annotations

from typing import Literal

import ee

ReducerName = Literal["median", "mean"]


def to_monthly_median(
    collection: ee.ImageCollection,
    start_date: str,
    end_date: str,
) -> ee.ImageCollection:
    """Aggregate an optical time series into monthly median composites.

    Each non-empty monthly median is stamped at the 15th day of its month
    (``system:time_start``); months with zero source acquisitions (``n == 0``)
    are dropped so CCDC never ingests empty images.

    Parameters
    ----------
    collection : ee.ImageCollection
        Harmonized optical collection (e.g. from :mod:`ccdc_segment.inputs.s2`
        or :mod:`ccdc_segment.inputs.landsat`).
    start_date : str
        Inclusive start date (``YYYY-MM-DD``).
    end_date : str
        Exclusive end date (``YYYY-MM-DD``).

    Returns
    -------
    ee.ImageCollection
        Monthly median collection retaining ``system:time_start`` and ``n``.
    """
    start = ee.Date(start_date)
    n_months = ee.Date(end_date).difference(start, "month").floor()

    def _monthly_image(month_offset: ee.Number) -> ee.Image:
        month_start = start.advance(month_offset, "month")
        monthly_images = collection.filterDate(month_start, month_start.advance(1, "month"))
        return (
            monthly_images.median()
            .set("system:time_start", month_start.advance(15, "day").millis())
            .set("n", monthly_images.size())
        )

    composites = ee.List.sequence(0, n_months.subtract(1)).map(_monthly_image)
    return ee.ImageCollection.fromImages(composites).filter(ee.Filter.gt("n", 0))


def seasonal_composite(
    collection: ee.ImageCollection,
    year: int,
    start_month: int,
    end_month: int,
    *,
    reducer: ReducerName | int | float = "median",
) -> ee.Image:
    """Generate a direct seasonal composite for a target calendar year.

    Supports both intra-year seasons (e.g. ``start_month=6, end_month=10``)
    and year-wrapping seasons (e.g. ``start_month=12, end_month=4``, which
    spans December of ``year - 1`` through April of ``year``). Safely handles
    ``end_month=12`` via ``ee.Date.advance(1, 'month')``.

    Parameters
    ----------
    collection : ee.ImageCollection
        Harmonized optical collection (typically ``reflectance_scale=1.0``).
    year : int
        Target calendar year.
    start_month : int
        Starting calendar month (1..12).
    end_month : int
        Ending calendar month (1..12, inclusive).
    reducer : {'median', 'mean'} or float, default 'median'
        Temporal reduction mode. Numeric values in ``[0, 100]`` compute the
        corresponding percentile via ``ee.Reducer.percentile([reducer])``.

    Returns
    -------
    ee.Image
        Reduced seasonal composite image.
    """
    if not (1 <= start_month <= 12):
        raise ValueError(f"start_month must be in 1..12, got {start_month!r}.")
    if not (1 <= end_month <= 12):
        raise ValueError(f"end_month must be in 1..12, got {end_month!r}.")

    end_date = ee.Date.fromYMD(year, end_month, 1).advance(1, "month")

    if start_month > end_month:
        start_date = ee.Date.fromYMD(year - 1, start_month, 1)
        filtered = collection.filterDate(start_date, end_date).filter(
            ee.Filter.calendarRange(start_month, end_month, "month")
        )
    else:
        start_date = ee.Date.fromYMD(year, start_month, 1)
        filtered = collection.filterDate(start_date, end_date)

    if isinstance(reducer, bool):
        raise TypeError("reducer must be 'median', 'mean', or a percentile number, not bool.")
    if isinstance(reducer, int | float):
        if not (0 <= reducer <= 100):
            raise ValueError(f"Percentile reducer must lie in [0, 100], got {reducer!r}.")
        return filtered.reduce(ee.Reducer.percentile([reducer]))
    if reducer == "median":
        return filtered.median()
    if reducer == "mean":
        return filtered.mean()

    raise ValueError(
        f"Unsupported reducer {reducer!r}; expected 'median', 'mean', or a percentile in [0, 100]."
    )
