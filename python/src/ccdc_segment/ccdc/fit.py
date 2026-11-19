"""Stage 2 CCDC fitting, tiled mosaic loading, and export band preparation."""

from __future__ import annotations

from collections.abc import Sequence

import ee

from ccdc_segment.ccdc.specs import CCDCParams
from ccdc_segment.constants import CCDC_CORE_EXPORT_BANDS


def run_ccdc(
    collection: ee.ImageCollection,
    params: CCDCParams | None = None,
) -> ee.Image:
    """Execute GEE Continuous Change Detection and Classification (CCDC).

    Parameters
    ----------
    collection : ee.ImageCollection
        Harmonized optical time-series collection (scaled to ``0..10000`` for
        standard ``lambda_=20`` regularization).
    params : CCDCParams, optional
        CCDC hyperparameter configuration. Defaults to :class:`CCDCParams`
        (five breakpoint bands, ``date_format=1``, ``min_observations=6``,
        ``chi_square_probability=0.99``, ``lambda_=20``).

    Returns
    -------
    ee.Image
        Multi-band array image containing segment timing (``tStart``, ``tEnd``,
        ``tBreak``, ``changeProb``) and harmonic regression coefficients
        (``*_coefs``).
    """
    cfg = params if params is not None else CCDCParams()
    return ee.Algorithms.TemporalSegmentation.Ccdc(**cfg.to_ee_params(collection))


def load_ccdc_mosaic(
    source: str | Sequence[str] | ee.ImageCollection,
    aoi: ee.Geometry | None = None,
    *,
    is_collection: bool = False,
) -> ee.Image:
    """Load and mosaic one or more pre-exported CCDC GEE assets.

    Parameters
    ----------
    source : str, Sequence[str], or ee.ImageCollection
        One of:
        - An ``ee.ImageCollection`` of CCDC tiles (e.g. ``GOOGLE/GLOBAL_CCDC/V1``),
        - A sequence of GEE ``ee.Image`` asset IDs to mosaic,
        - A single GEE ``ee.Image`` asset ID (or ``ImageCollection`` ID when
          ``is_collection=True``).
    aoi : ee.Geometry, optional
        If provided, filters ``ImageCollection`` sources by bounds before
        mosaicking and clips the final mosaic to ``aoi``.
    is_collection : bool, default False
        When ``source`` is a single string asset ID, set ``True`` to load it
        as ``ee.ImageCollection(source)`` (e.g. ``'GOOGLE/GLOBAL_CCDC/V1'``)
        instead of ``ee.Image(source)``.

    Returns
    -------
    ee.Image
        Seamless CCDC array image mosaic, optionally clipped to ``aoi``.
    """
    if isinstance(source, str):
        if is_collection:
            col = ee.ImageCollection(source)
            if aoi is not None:
                col = col.filterBounds(aoi)
            mosaic = col.mosaic()
        else:
            mosaic = ee.Image(source)
    elif isinstance(source, ee.ImageCollection):
        col = source.filterBounds(aoi) if aoi is not None else source
        mosaic = col.mosaic()
    elif isinstance(source, Sequence):
        if not source:
            raise ValueError("source must contain at least one CCDC tile asset ID.")
        images = [ee.Image(tile_id) if isinstance(tile_id, str) else tile_id for tile_id in source]
        mosaic = ee.ImageCollection(images).mosaic()
    else:
        raise TypeError(
            "source must be a GEE asset ID string, a sequence of tile IDs, "
            f"or an ee.ImageCollection; got {type(source).__name__}."
        )

    return mosaic.clip(aoi) if aoi is not None else mosaic


def prepare_ccdc_for_export(
    ccdc_image: ee.Image,
    *,
    bands: Sequence[str] = CCDC_CORE_EXPORT_BANDS,
) -> ee.Image:
    """Trim a raw CCDC output image to the bands required downstream.

    Retaining only ``tStart``, ``tEnd``, ``tBreak``, ``changeProb``, and
    ``.*_coefs`` reduces asset storage and export EECU overhead while keeping
    every band needed by synthetic reconstruction, harmonics, and stability
    filtering.

    Parameters
    ----------
    ccdc_image : ee.Image
        Raw output image from :func:`run_ccdc`.
    bands : Sequence[str], default CCDC_CORE_EXPORT_BANDS
        Exact band names or GEE regex selectors to retain.

    Returns
    -------
    ee.Image
        Band-trimmed CCDC array image ready for asset export with
        ``pyramidingPolicy={'.default': 'sample'}``.
    """
    band_list = list(bands)
    if not band_list:
        raise ValueError("bands must contain at least one band name or regex selector.")
    return ccdc_image.select(band_list)
