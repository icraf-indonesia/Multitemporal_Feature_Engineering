"""Stage 3 sensor-agnostic CCDC synthetic reconstruction and harmonic extraction.

Implements the methodological safeguards documented in
``docs/CCDC_TEMPORAL_SEGMENTATION.md``:
- Nearest-segment lookup with configurable temporal gap tolerance.
- Linear trend clamping to segment bounds ``[tStart, tEnd]`` while evaluating
  1st–3rd order seasonal harmonics at the exact target date ``t``.
- Unified all-band physical surface reflectance plausibility masking.
- Conditional 3x3 focal median hole repair for isolated dropouts.
- Polar first-harmonic amplitude and phase extraction.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import ee

from ccdc_segment.ccdc.specs import BandCase, CCDCProfile, SegmentMatch


def nearest_segment(
    ccdc: ee.Image,
    target_date: float | ee.Number,
) -> SegmentMatch:
    """Locate the temporally closest CCDC segment per pixel at ``target_date``.

    Computes ``d(t, s) = max(0, tStart_s - t, t - tEnd_s)``. When ``t`` falls
    strictly inside an active segment, ``gap`` is ``0``.

    Parameters
    ----------
    ccdc : ee.Image
        CCDC array image containing ``tStart`` and ``tEnd``.
    target_date : float or ee.Number
        Evaluation date in fractional years (e.g. ``2025.65``).

    Returns
    -------
    SegmentMatch
        Dataclass holding per-pixel ``idx``, ``gap`` (named ``'gap_years'``),
        ``t_start``, and ``t_end``.
    """
    t = ee.Number(target_date)
    t_start = ccdc.select("tStart")
    t_end = ccdc.select("tEnd")

    dist = t_start.subtract(t).max(t_end.multiply(-1).add(t)).max(0)

    idx = dist.multiply(-1).arrayArgmax().arrayGet([0])
    gap = dist.arrayReduce(ee.Reducer.min(), [0]).arrayGet([0]).rename("gap_years")

    return SegmentMatch(idx=idx, gap=gap, t_start=t_start, t_end=t_end)


def fill_isolated(
    image: ee.Image,
    min_neighbors: int = 5,
) -> ee.Image:
    """Repair isolated masked pixels via a conditional 3x3 focal median.

    A masked pixel is filled only when at least ``min_neighbors`` of its 8
    immediate neighbors are valid, preventing hallucination across larger
    contiguous gaps.

    Parameters
    ----------
    image : ee.Image
        Multi-band image containing potential isolated nodata dropouts.
    min_neighbors : int, default 5
        Minimum count of valid pixels in the 3x3 neighborhood (1..8).

    Returns
    -------
    ee.Image
        Image with isolated single/two-pixel dropouts repaired.
    """
    if not (1 <= min_neighbors <= 8):
        raise ValueError(f"min_neighbors must be between 1 and 8, got {min_neighbors!r}.")

    valid_neighbors = (
        image.select(0)
        .mask()
        .reduceNeighborhood(
            reducer=ee.Reducer.sum(),
            kernel=ee.Kernel.square(1),
        )
    )
    median_img = image.focalMedian(1, "square", "pixels")
    return image.unmask(median_img.updateMask(valid_neighbors.gte(min_neighbors)))


def get_synthetic_stack(
    ccdc: ee.Image,
    target_date: float | ee.Number,
    *,
    profile: CCDCProfile | None = None,
    bands: Sequence[str] | None = None,
    fill_holes: bool = True,
    min_neighbors: int = 5,
    include_diagnostics: bool = True,
) -> ee.Image:
    """Reconstruct cloud-free synthetic surface reflectance at ``target_date``.

    Evaluates the 8-parameter harmonic model with trend clamping:
    linear slope ``c1`` is evaluated at ``tc = clamp(t, tStart, tEnd)`` while
    the 1st, 2nd, and 3rd seasonal harmonics are evaluated at exact ``t``.
    Spectral indices are intentionally excluded to preserve stage separation.

    Parameters
    ----------
    ccdc : ee.Image
        CCDC array image containing ``tStart``, ``tEnd``, and ``*_coefs`` bands.
    target_date : float or ee.Number
        Target evaluation date in fractional years (e.g. ``2025.65``).
    profile : CCDCProfile, optional
        Asset metadata profile controlling ``coef_scale``, ``coef_case``,
        ``tol_years``, ``bounds``, and default ``bands``. Defaults to
        :meth:`CCDCProfile.standard`.
    bands : Sequence[str], optional
        Canonical optical bands to reconstruct (overrides ``profile.bands``).
    fill_holes : bool, default True
        Whether to apply :func:`fill_isolated` after plausibility masking.
    min_neighbors : int, default 5
        Minimum valid neighbors passed to :func:`fill_isolated`.
    include_diagnostics : bool, default True
        If ``True``, appends ``'gap_years'`` and ``'synth_valid'`` bands.

    Returns
    -------
    ee.Image
        Synthetic surface reflectance stack in ``0..1`` scale (lowercase band
        names), optionally accompanied by diagnostic bands.
    """
    prof = profile if profile is not None else CCDCProfile.standard()
    target_bands = tuple(b.lower() for b in bands) if bands is not None else prof.bands
    if not target_bands:
        raise ValueError("bands must contain at least one band name.")

    t = ee.Number(target_date)
    seg = nearest_segment(ccdc, t)

    # Clamp linear trend time strictly to segment bounds [tStart, tEnd];
    # evaluate harmonic terms at the exact target fractional date t.
    tc = ee.Image(t).max(seg.t_start.arrayGet(seg.idx)).min(seg.t_end.arrayGet(seg.idx))
    omega = 2.0 * math.pi

    terms = ee.Image.cat(
        [
            ee.Image.constant(1),
            tc,
            ee.Image.constant(t.multiply(omega).cos()),
            ee.Image.constant(t.multiply(omega).sin()),
            ee.Image.constant(t.multiply(omega * 2.0).cos()),
            ee.Image.constant(t.multiply(omega * 2.0).sin()),
            ee.Image.constant(t.multiply(omega * 3.0).cos()),
            ee.Image.constant(t.multiply(omega * 3.0).sin()),
        ]
    ).toArray()

    synthetic_bands: list[ee.Image] = []
    for band in target_bands:
        coef_band_name = prof.coef_band_name(band)
        coefs = (
            ccdc.select(coef_band_name)
            .arraySlice(0, seg.idx, seg.idx.add(1))
            .arrayProject([1])
        )
        evaluated = (
            coefs.multiply(terms)
            .arrayReduce(ee.Reducer.sum(), [0])
            .arrayGet([0])
            .divide(prof.coef_scale)
            .rename(band)
        )
        synthetic_bands.append(evaluated)

    stack = ee.Image.cat(synthetic_bands)

    plausible = (
        stack.reduce(ee.Reducer.min())
        .gt(prof.bounds.min)
        .And(stack.reduce(ee.Reducer.max()).lt(prof.bounds.max))
    )
    within_tol = seg.gap.lte(prof.tol_years)
    synth_valid = plausible.And(within_tol).rename("synth_valid")

    masked_stack = stack.updateMask(synth_valid)
    if fill_holes:
        masked_stack = fill_isolated(masked_stack, min_neighbors=min_neighbors)

    if include_diagnostics:
        return masked_stack.addBands([seg.gap, synth_valid])
    return masked_stack


def get_harmonics(
    ccdc: ee.Image,
    target_date: float | ee.Number,
    *,
    profile: CCDCProfile | None = None,
    bands: Sequence[str] = ("nir", "red", "swir1"),
    output_case: BandCase | None = None,
) -> ee.Image:
    """Extract first-order annual harmonic amplitude and phase at ``target_date``.

    From the nearest segment's first-harmonic coefficients ``(a1, b1)`` scaled
    by ``profile.coef_scale``, computes:
    - ``amplitude = sqrt(a1^2 + b1^2)`` (via ``a1.hypot(b1)``)
    - ``phase = atan2(b1, a1)`` in ``[-pi, pi]``

    Parameters
    ----------
    ccdc : ee.Image
        CCDC array image containing ``tStart``, ``tEnd``, and ``*_coefs`` bands.
    target_date : float or ee.Number
        Evaluation date in fractional years (typically mid-year ``YYYY.50``).
    profile : CCDCProfile, optional
        Asset metadata profile. Defaults to :meth:`CCDCProfile.standard`.
    bands : Sequence[str], default ('nir', 'red', 'swir1')
        Bands for which to extract amplitude and phase.
    output_case : {'lower', 'upper'}, optional
        Override for :attr:`CCDCProfile.harm_case` controlling output band
        prefix casing (e.g. ``'nir_amp'`` vs ``'NIR_amp'``).

    Returns
    -------
    ee.Image
        Multi-band amplitude/phase image masked where ``gap_years > tol_years``.
    """
    prof = profile if profile is not None else CCDCProfile.standard()
    target_bands = tuple(b.lower() for b in bands)
    if not target_bands:
        raise ValueError("bands must contain at least one band name.")

    t = ee.Number(target_date)
    seg = nearest_segment(ccdc, t)

    harmonic_images: list[ee.Image] = []
    for band in target_bands:
        coef_band_name = prof.coef_band_name(band)
        coefficients = (
            ccdc.select(coef_band_name)
            .arraySlice(0, seg.idx, seg.idx.add(1))
            .arrayProject([1])
        )
        a1 = coefficients.arrayGet([2]).divide(prof.coef_scale)  # cos(wt)
        b1 = coefficients.arrayGet([3]).divide(prof.coef_scale)  # sin(wt)

        amp_name, phase_name = prof.harmonic_band_names(band, output_case=output_case)
        harmonic_images.append(
            ee.Image.cat(
                [
                    a1.hypot(b1).rename(amp_name),
                    b1.atan2(a1).rename(phase_name),
                ]
            )
        )

    return ee.Image.cat(harmonic_images).updateMask(seg.gap.lte(prof.tol_years))


def get_multi_year_stacks(
    ccdc: ee.Image,
    years: Sequence[int],
    season_fraction: float = 0.50,
    *,
    profile: CCDCProfile | None = None,
    **kwargs: Any,
) -> dict[int, ee.Image]:
    """Generate synthetic reflectance stacks across multiple target years.

    Parameters
    ----------
    ccdc : ee.Image
        CCDC array image.
    years : Sequence[int]
        Calendar years to evaluate (e.g. ``[2015, 2020, 2025]``).
    season_fraction : float, default 0.50
        Fractional-year offset added to each year (must lie in ``[0.0, 1.0)``).
    profile : CCDCProfile, optional
        Asset metadata profile forwarded to :func:`get_synthetic_stack`.
    **kwargs : Any
        Additional keyword arguments forwarded to :func:`get_synthetic_stack`.

    Returns
    -------
    dict[int, ee.Image]
        Mapping from calendar year to its reconstructed synthetic stack.
    """
    if not (0.0 <= season_fraction < 1.0):
        raise ValueError(
            f"season_fraction must lie in [0.0, 1.0), got {season_fraction!r}."
        )
    return {
        int(yr): get_synthetic_stack(
            ccdc,
            float(yr) + float(season_fraction),
            profile=profile,
            **kwargs,
        )
        for yr in years
    }
