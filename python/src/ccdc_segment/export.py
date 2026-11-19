"""Batch export helpers and tiled CCDC export orchestration for Earth Engine."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import ee

from ccdc_segment.ccdc.fit import prepare_ccdc_for_export
from ccdc_segment.constants import (
    CCDC_PYRAMIDING_POLICY,
    DEFAULT_MAX_PIXELS,
    DEFAULT_PYRAMIDING_POLICY,
)

ExportStatus = Literal["started", "created", "skipped_existing"]


@dataclass(frozen=True)
class ExportTaskRecord:
    """Audit record returned for each tile processed by :func:`export_ccdc_tiles`.

    Attributes
    ----------
    tile_name : str
        Identifier of the exported spatial tile.
    asset_id : str
        Full destination GEE asset path.
    status : {'started', 'created', 'skipped_existing'}
        Outcome for this tile: ``'started'`` when submitted to GEE, ``'created'``
        in dry-run mode (``start=False``), or ``'skipped_existing'`` when an
        existing asset was detected.
    task : ee.batch.Task or None
        Underlying Earth Engine batch task object (``None`` when skipped).
    """

    tile_name: str
    asset_id: str
    status: ExportStatus
    task: ee.batch.Task | None = None


def asset_exists(asset_id: str) -> bool:
    """Check whether a Google Earth Engine asset already exists.

    Parameters
    ----------
    asset_id : str
        Full GEE asset path (e.g. ``'projects/my-proj/assets/my_tile'``).

    Returns
    -------
    bool
        ``True`` if ``ee.data.getAsset(asset_id)`` succeeds, ``False`` if the
        asset does not exist (raises ``ee.EEException``).
    """
    try:
        ee.data.getAsset(asset_id)
        return True
    except ee.EEException:
        return False


def _extract_bbox_from_aoi(aoi: ee.Geometry) -> tuple[float, float, float, float]:
    """Query an ``ee.Geometry`` bounding box in EPSG:4326 as ``(min_x, min_y, max_x, max_y)``."""
    coords = aoi.bounds(maxError=1, proj="EPSG:4326").coordinates().getInfo()
    ring = coords[0]
    xs = [pt[0] for pt in ring]
    ys = [pt[1] for pt in ring]
    return float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))


def make_tile_grid(
    aoi: ee.Geometry | None = None,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    tile_size_deg: float = 0.5,
    prefix: str = "tile",
    filter_intersecting: bool = True,
) -> dict[str, ee.Geometry]:
    """Generate a rectangular lon/lat tile grid covering an AOI or bounding box.

    When ``filter_intersecting=True`` and ``aoi`` is provided, candidate tiles
    are pruned against ``aoi`` in a single server-side ``FeatureCollection``
    query rather than issuing one RPC per tile.

    Parameters
    ----------
    aoi : ee.Geometry, optional
        Study-area geometry. Required when ``bbox`` is ``None`` or when
        ``filter_intersecting=True``.
    bbox : tuple[float, float, float, float], optional
        Explicit ``(min_lon, min_lat, max_lon, max_lat)`` in degrees. Passing
        ``bbox`` avoids an extra ``aoi.bounds().getInfo()`` roundtrip.
    tile_size_deg : float, default 0.5
        Width and height of each rectangular tile in decimal degrees.
    prefix : str, default 'tile'
        Name prefix for generated tiles (formatted ``'{prefix}_r{row:02d}_c{col:02d}'``).
    filter_intersecting : bool, default True
        When ``True`` and ``aoi`` is supplied, keep only tiles intersecting ``aoi``.

    Returns
    -------
    dict[str, ee.Geometry]
        Ordered mapping of ``tile_name -> ee.Geometry.Rectangle``.
    """
    if tile_size_deg <= 0:
        raise ValueError(f"tile_size_deg must be > 0, got {tile_size_deg!r}.")
    if bbox is None:
        if aoi is None:
            raise ValueError("Provide either 'aoi' or 'bbox' to make_tile_grid().")
        min_x, min_y, max_x, max_y = _extract_bbox_from_aoi(aoi)
    else:
        min_x, min_y, max_x, max_y = (float(v) for v in bbox)

    if min_x >= max_x or min_y >= max_y:
        raise ValueError(
            f"Invalid bounding box {(min_x, min_y, max_x, max_y)}: "
            "expected min_lon < max_lon and min_lat < max_lat."
        )

    n_cols = max(1, math.ceil((max_x - min_x) / tile_size_deg))
    n_rows = max(1, math.ceil((max_y - min_y) / tile_size_deg))

    candidates: dict[str, ee.Geometry] = {}
    for row in range(n_rows):
        y0 = min_y + row * tile_size_deg
        y1 = min(y0 + tile_size_deg, max_y)
        for col in range(n_cols):
            x0 = min_x + col * tile_size_deg
            x1 = min(x0 + tile_size_deg, max_x)
            name = f"{prefix}_r{row:02d}_c{col:02d}"
            candidates[name] = ee.Geometry.Rectangle(
                [x0, y0, x1, y1],
                proj="EPSG:4326",
                geodesic=False,
            )

    if filter_intersecting and aoi is not None:
        fc = ee.FeatureCollection(
            [ee.Feature(geom, {"tile_name": name}) for name, geom in candidates.items()]
        )
        matching_names = set(fc.filterBounds(aoi).aggregate_array("tile_name").getInfo())
        return {name: geom for name, geom in candidates.items() if name in matching_names}

    return candidates


def export_to_asset(
    image: ee.Image,
    asset_id: str,
    *,
    region: ee.Geometry,
    scale: int = 20,
    crs: str = "EPSG:4326",
    description: str | None = None,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    pyramiding_policy: Mapping[str, str] | None = None,
    start: bool = False,
) -> ee.batch.Task:
    """Create (and optionally start) a GEE ``Export.image.toAsset`` batch task.

    Parameters
    ----------
    image : ee.Image
        Image to export.
    asset_id : str
        Full destination GEE asset path.
    region : ee.Geometry
        Export bounding region.
    scale : int, default 20
        Output pixel resolution in metres.
    crs : str, default 'EPSG:4326'
        Output coordinate reference system.
    description : str, optional
        Task label shown in the GEE Tasks list. Defaults to the final asset
        path segment.
    max_pixels : int, default 10**13
        Maximum pixel count permitted for the export.
    pyramiding_policy : Mapping[str, str], optional
        GEE pyramiding policy. Defaults to ``{'.default': 'mean'}``. For CCDC
        array images, pass ``{'.default': 'sample'}`` (or use
        :func:`export_ccdc_tiles`).
    start : bool, default False
        If ``True``, immediately calls ``task.start()``. Defaults to ``False``
        so callers can inspect tasks safely before submitting.

    Returns
    -------
    ee.batch.Task
        Configured Earth Engine export task.
    """
    policy = dict(pyramiding_policy) if pyramiding_policy is not None else dict(DEFAULT_PYRAMIDING_POLICY)
    task = ee.batch.Export.image.toAsset(
        image=image,
        description=description or asset_id.rstrip("/").split("/")[-1],
        assetId=asset_id,
        region=region,
        scale=scale,
        crs=crs,
        maxPixels=max_pixels,
        pyramidingPolicy=policy,
    )
    if start:
        task.start()
    return task


def export_to_drive(
    image: ee.Image,
    file_name: str,
    *,
    region: ee.Geometry,
    folder: str = "GEE_Exports",
    scale: int = 20,
    crs: str = "EPSG:4326",
    description: str | None = None,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    cloud_optimized: bool = True,
    start: bool = False,
) -> ee.batch.Task:
    """Create (and optionally start) a GEE ``Export.image.toDrive`` GeoTIFF task.

    Parameters
    ----------
    image : ee.Image
        Image to export.
    file_name : str
        Output file name prefix (without ``.tif`` extension).
    region : ee.Geometry
        Export bounding region.
    folder : str, default 'GEE_Exports'
        Target Google Drive folder name.
    scale : int, default 20
        Output pixel resolution in metres.
    crs : str, default 'EPSG:4326'
        Output coordinate reference system.
    description : str, optional
        Task label shown in GEE. Defaults to ``file_name``.
    max_pixels : int, default 10**13
        Maximum pixel count permitted for the export.
    cloud_optimized : bool, default True
        Whether to write a Cloud-Optimized GeoTIFF (COG).
    start : bool, default False
        If ``True``, immediately calls ``task.start()``.

    Returns
    -------
    ee.batch.Task
        Configured Earth Engine Drive export task.
    """
    task = ee.batch.Export.image.toDrive(
        image=image,
        description=description or file_name,
        folder=folder,
        fileNamePrefix=file_name,
        region=region,
        scale=scale,
        crs=crs,
        maxPixels=max_pixels,
        formatOptions={"cloudOptimized": cloud_optimized},
    )
    if start:
        task.start()
    return task


def _resolve_tiles(
    tiles: Mapping[str, ee.Geometry] | ee.FeatureCollection,
    tile_name_property: str,
) -> list[tuple[str, ee.Geometry]]:
    """Normalize a mapping or ``ee.FeatureCollection`` of tiles into ``(name, geometry)`` pairs."""
    if isinstance(tiles, Mapping):
        if not tiles:
            raise ValueError("tiles mapping must contain at least one tile.")
        return [(str(name), geom) for name, geom in tiles.items()]

    if isinstance(tiles, ee.FeatureCollection):
        names = tiles.aggregate_array(tile_name_property).getInfo()
        if not names:
            raise ValueError(
                f"FeatureCollection produced no tile names for property {tile_name_property!r}."
            )
        return [
            (
                str(name),
                tiles.filter(ee.Filter.eq(tile_name_property, name)).geometry(),
            )
            for name in names
        ]

    raise TypeError(
        "tiles must be a Mapping[str, ee.Geometry] or ee.FeatureCollection; "
        f"got {type(tiles).__name__}."
    )


def _format_tile_asset_id(asset_prefix: str, tile_name: str) -> str:
    """Join an asset folder or name prefix cleanly with a tile identifier."""
    if not asset_prefix:
        raise ValueError("asset_prefix must be a non-empty GEE asset path prefix.")
    if asset_prefix.endswith("/"):
        return f"{asset_prefix}{tile_name}"
    return f"{asset_prefix}_{tile_name}"


def export_ccdc_tiles(
    ccdc_image: ee.Image,
    asset_prefix: str,
    tiles: Mapping[str, ee.Geometry] | ee.FeatureCollection,
    *,
    scale: int = 20,
    crs: str = "EPSG:4326",
    tile_name_property: str = "name",
    trim_bands: bool = True,
    skip_existing: bool = True,
    start: bool = False,
    max_pixels: int = DEFAULT_MAX_PIXELS,
) -> list[ExportTaskRecord]:
    """Batch-export a CCDC array image across spatial tiles with safe defaults.

    Automatically enforces ``pyramidingPolicy={'.default': 'sample'}`` (required
    for array-valued GEE images) and optionally trims the CCDC output to core
    downstream bands before task creation.

    Parameters
    ----------
    ccdc_image : ee.Image
        CCDC array image (e.g. from :func:`ccdc_segment.ccdc.run_ccdc`).
    asset_prefix : str
        Destination asset path prefix. If ending with ``'/'``, tiles are named
        ``'{asset_prefix}{tile_name}'``; otherwise ``'{asset_prefix}_{tile_name}'``.
    tiles : Mapping[str, ee.Geometry] or ee.FeatureCollection
        Named spatial tiles (e.g. from :func:`make_tile_grid` or custom
        sub-regional boxes).
    scale : int, default 20
        Export pixel resolution in metres (``20`` for Sentinel-2, ``30`` for Landsat).
    crs : str, default 'EPSG:4326'
        Target coordinate reference system.
    tile_name_property : str, default 'name'
        Feature property used as the tile name when ``tiles`` is an
        ``ee.FeatureCollection``.
    trim_bands : bool, default True
        When ``True``, calls :func:`ccdc_segment.ccdc.prepare_ccdc_for_export`
        to drop auxiliary bands not needed downstream.
    skip_existing : bool, default True
        When ``True``, checks :func:`asset_exists` and skips tiles whose
        destination asset already exists in Earth Engine.
    start : bool, default False
        When ``False`` (safe default), performs a dry run creating tasks without
        starting them. Set ``True`` to submit tasks to Earth Engine.
    max_pixels : int, default 10**13
        Maximum pixel count per tile export.

    Returns
    -------
    list[ExportTaskRecord]
        One audit record per tile describing its asset path, status, and task.
    """
    export_img = prepare_ccdc_for_export(ccdc_image) if trim_bands else ccdc_image
    resolved_tiles = _resolve_tiles(tiles, tile_name_property=tile_name_property)

    records: list[ExportTaskRecord] = []
    for tile_name, tile_geom in resolved_tiles:
        asset_id = _format_tile_asset_id(asset_prefix, tile_name)
        if skip_existing and asset_exists(asset_id):
            records.append(
                ExportTaskRecord(
                    tile_name=tile_name,
                    asset_id=asset_id,
                    status="skipped_existing",
                    task=None,
                )
            )
            continue

        task = export_to_asset(
            export_img,
            asset_id,
            region=tile_geom,
            scale=scale,
            crs=crs,
            max_pixels=max_pixels,
            pyramiding_policy=CCDC_PYRAMIDING_POLICY,
            start=start,
        )
        records.append(
            ExportTaskRecord(
                tile_name=tile_name,
                asset_id=asset_id,
                status="started" if start else "created",
                task=task,
            )
        )

    return records
