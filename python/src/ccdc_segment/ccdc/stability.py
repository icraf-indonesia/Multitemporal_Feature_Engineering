"""Multi-epoch training sample stability filtering using CCDC segments."""

from __future__ import annotations

import math
from collections.abc import Sequence

import ee

from ccdc_segment.ccdc.reconstruct import nearest_segment
from ccdc_segment.ccdc.specs import CCDCProfile


def stable_in_period(
    ccdc: ee.Image,
    start_year: float,
    end_year: float,
    *,
    profile: CCDCProfile | None = None,
    apply_slope_filter: bool = True,
    drift_bands: Sequence[str] = ("nir", "swir1"),
    max_drift: float = 0.12,
    midpoint_offset: float = 0.50,
) -> ee.Image:
    """Compute a binary stability mask for transferring samples across epochs.

    A pixel is marked stable (``1``) over ``[start_year, end_year]`` iff:
    1. **Zero confirmed breakpoints**: No segment break with ``changeProb == 1``
       occurs within ``[start_year, end_year]``.
    2. **Continuous single-segment coverage**: Both epoch midpoints
       (``floor(start_year) + midpoint_offset`` and
       ``floor(end_year) + midpoint_offset``) fall within ``profile.tol_years``
       and map to the exact same CCDC segment index.
    3. **Gradual drift bound** (when ``apply_slope_filter=True``): The
       cumulative linear reflectance drift ``|c1 / coef_scale| * (end_year - start_year)``
       does not exceed ``max_drift`` for every band in ``drift_bands``.

    Parameters
    ----------
    ccdc : ee.Image
        CCDC array image containing ``tStart``, ``tEnd``, ``tBreak``,
        ``changeProb``, and coefficient arrays for ``drift_bands``.
    start_year : float
        Start of stability window (e.g. ``2015.0``).
    end_year : float
        End of stability window (e.g. ``2025.99``). Must be ``>= start_year``.
    profile : CCDCProfile, optional
        Asset metadata profile governing ``tol_years``, ``coef_scale``, and
        ``coef_case``. Defaults to :meth:`CCDCProfile.standard`.
    apply_slope_filter : bool, default True
        Whether to enforce the gradual linear drift threshold.
    drift_bands : Sequence[str], default ('nir', 'swir1')
        Bands evaluated for gradual linear reflectance drift.
    max_drift : float, default 0.12
        Maximum allowable cumulative reflectance change (0..1 scale) across the
        period.
    midpoint_offset : float, default 0.50
        Fractional-year offset added to ``floor(start_year)`` and
        ``floor(end_year)`` for segment coverage checks.

    Returns
    -------
    ee.Image
        Unmasked single-band ``uint8`` (byte) image where ``1`` indicates a
        stable pixel and ``0`` indicates an unstable or unmodeled pixel.
    """
    if end_year < start_year:
        raise ValueError(
            f"end_year ({end_year}) must be >= start_year ({start_year})."
        )
    if max_drift < 0:
        raise ValueError(f"max_drift must be >= 0, got {max_drift!r}.")
    if not (0.0 <= midpoint_offset < 1.0):
        raise ValueError(
            f"midpoint_offset must lie in [0.0, 1.0), got {midpoint_offset!r}."
        )

    prof = profile if profile is not None else CCDCProfile.standard()

    # Condition 1: Zero confirmed breakpoints (changeProb == 1) in [start_year, end_year]
    t_break = ccdc.select("tBreak")
    change_prob = ccdc.select("changeProb")
    confirmed_break = t_break.multiply(change_prob.eq(1))
    breaks_in_window = confirmed_break.arrayMask(
        confirmed_break.gte(start_year).And(confirmed_break.lte(end_year))
    )
    no_break = breaks_in_window.arrayLength(0).eq(0)

    # Condition 2: Symmetric single-segment coverage within tol_years
    seg_start = nearest_segment(ccdc, math.floor(start_year) + midpoint_offset)
    seg_end = nearest_segment(ccdc, math.floor(end_year) + midpoint_offset)

    valid_coverage = (
        seg_start.gap.lte(prof.tol_years)
        .And(seg_end.gap.lte(prof.tol_years))
        .And(seg_start.idx.eq(seg_end.idx))
    )

    is_stable = no_break.And(valid_coverage)

    # Condition 3: Gradual linear drift constraint across drift_bands
    if apply_slope_filter and drift_bands:
        delta_years = float(end_year) - float(start_year)
        for band in drift_bands:
            coef_band = prof.coef_band_name(band)
            slope = (
                ccdc.select(coef_band)
                .arraySlice(0, seg_end.idx, seg_end.idx.add(1))
                .arrayProject([1])
                .arrayGet([1])
                .divide(prof.coef_scale)
                .abs()
            )
            is_stable = is_stable.And(slope.multiply(delta_years).lte(max_drift))

    return is_stable.unmask(0).toByte()
