"""Decoupled project configuration models for ``ccdc_segment``.

This module keeps project-specific parameters (study-area AOI assets, CRS,
monsoon seasonal fractions, and pre-exported CCDC tile IDs) cleanly separated
from reusable library code. Configurations can be constructed programmatically
or loaded from external JSON/YAML files.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import ee

from ccdc_segment.constants import DEFAULT_MAX_PIXELS, DEFAULT_TOL_YEARS

SeasonName = Literal["wet", "dry", "harm"]


@dataclass(frozen=True)
class SeasonFractions:
    """Fractional-year offsets used to evaluate CCDC models at seasonal targets.

    Parameters
    ----------
    wet : float, default 0.16
        Fractional-year offset for peak wet season (e.g. ``0.16`` ~ mid-March).
    dry : float, default 0.65
        Fractional-year offset for peak dry season (e.g. ``0.65`` ~ late August).
    harm : float, default 0.50
        Mid-year fractional offset used when extracting harmonic amplitude/phase.
    """

    wet: float = 0.16
    dry: float = 0.65
    harm: float = 0.50

    def __post_init__(self) -> None:
        for attr in ("wet", "dry", "harm"):
            value = getattr(self, attr)
            if not (0.0 <= float(value) < 1.0):
                raise ValueError(
                    f"Season fraction '{attr}' must lie in [0.0, 1.0), got {value!r}."
                )

    def date_for(self, year: int, season: SeasonName) -> float:
        """Compute the fractional-year date for a given calendar year and season.

        Parameters
        ----------
        year : int
            Four-digit calendar year (e.g. ``2025``).
        season : {'wet', 'dry', 'harm'}
            Target seasonal offset name.

        Returns
        -------
        float
            Fractional year (e.g. ``2025.65``).
        """
        if season not in ("wet", "dry", "harm"):
            raise ValueError(f"Unknown season {season!r}; expected 'wet', 'dry', or 'harm'.")
        return float(year) + float(getattr(self, season))

    def to_dict(self) -> dict[str, float]:
        """Serialize seasonal fractions to a plain dictionary."""
        return {"wet": self.wet, "dry": self.dry, "harm": self.harm}


@dataclass(frozen=True)
class ExportDefaults:
    """Canonical project defaults for Google Earth Engine export tasks.

    Parameters
    ----------
    crs : str, default 'EPSG:4326'
        Target coordinate reference system EPSG code or WKT string.
    scale : int, default 20
        Default output pixel resolution in metres.
    max_pixels : int, default 10**13
        Maximum pixel count allowed per GEE export task.
    drive_folder : str, default 'GEE_Exports'
        Destination Google Drive folder for ``export_to_drive``.
    cloud_optimized : bool, default True
        Whether GeoTIFF Drive exports enable Cloud-Optimized GeoTIFF formatting.
    """

    crs: str = "EPSG:4326"
    scale: int = 20
    max_pixels: int = DEFAULT_MAX_PIXELS
    drive_folder: str = "GEE_Exports"
    cloud_optimized: bool = True

    def __post_init__(self) -> None:
        if not self.crs:
            raise ValueError("ExportDefaults.crs must be a non-empty string.")
        if self.scale <= 0:
            raise ValueError(f"ExportDefaults.scale must be > 0, got {self.scale!r}.")
        if self.max_pixels <= 0:
            raise ValueError(
                f"ExportDefaults.max_pixels must be > 0, got {self.max_pixels!r}."
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize export defaults to a plain dictionary."""
        return {
            "crs": self.crs,
            "scale": self.scale,
            "max_pixels": self.max_pixels,
            "drive_folder": self.drive_folder,
            "cloud_optimized": self.cloud_optimized,
        }


@dataclass(frozen=True)
class ProjectConfig:
    """Externalizable project configuration for multitemporal CCDC pipelines.

    Parameters
    ----------
    aoi_asset : str or None, default None
        Optional GEE ``FeatureCollection`` asset ID representing the study area.
    seasons : SeasonFractions, optional
        Fractional-year offsets for wet, dry, and harmonic evaluation dates.
    export : ExportDefaults, optional
        Project-wide CRS, scale, and Google Drive export defaults.
    ccdc_tiles : dict[str, tuple[str, ...]], optional
        Named collections of pre-exported CCDC tile asset IDs (e.g.
        ``{"landsat": (...), "s2": (...)}``).
    tol_years : float, default 1.0
        Default temporal gap tolerance (years) passed to CCDC reconstruction.
    """

    aoi_asset: str | None = None
    seasons: SeasonFractions = field(default_factory=SeasonFractions)
    export: ExportDefaults = field(default_factory=ExportDefaults)
    ccdc_tiles: dict[str, tuple[str, ...]] = field(default_factory=dict)
    tol_years: float = DEFAULT_TOL_YEARS

    def __post_init__(self) -> None:
        if self.tol_years < 0:
            raise ValueError(f"ProjectConfig.tol_years must be >= 0, got {self.tol_years!r}.")
        normalized_tiles: dict[str, tuple[str, ...]] = {}
        for name, tiles in self.ccdc_tiles.items():
            if isinstance(tiles, str):
                normalized_tiles[name] = (tiles,)
            elif isinstance(tiles, Sequence):
                normalized_tiles[name] = tuple(str(t) for t in tiles)
            else:
                raise TypeError(
                    f"ccdc_tiles[{name!r}] must be a string or sequence of strings."
                )
        object.__setattr__(self, "ccdc_tiles", normalized_tiles)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProjectConfig:
        """Construct a :class:`ProjectConfig` from a mapping (e.g. parsed JSON/YAML)."""
        if not isinstance(data, Mapping):
            raise TypeError(f"Expected a mapping for ProjectConfig, got {type(data).__name__}.")

        seasons_raw = data.get("seasons")
        seasons = (
            seasons_raw
            if isinstance(seasons_raw, SeasonFractions)
            else SeasonFractions(**seasons_raw)
            if isinstance(seasons_raw, Mapping)
            else SeasonFractions()
        )

        export_raw = data.get("export")
        export_cfg = (
            export_raw
            if isinstance(export_raw, ExportDefaults)
            else ExportDefaults(**export_raw)
            if isinstance(export_raw, Mapping)
            else ExportDefaults()
        )

        tiles_raw = data.get("ccdc_tiles") or {}
        if not isinstance(tiles_raw, Mapping):
            raise TypeError("ProjectConfig.ccdc_tiles must be a mapping of name -> asset IDs.")

        return cls(
            aoi_asset=data.get("aoi_asset"),
            seasons=seasons,
            export=export_cfg,
            ccdc_tiles=dict(tiles_raw),
            tol_years=float(data.get("tol_years", DEFAULT_TOL_YEARS)),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> ProjectConfig:
        """Load a :class:`ProjectConfig` from a UTF-8 JSON file."""
        file_path = Path(path)
        with file_path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return cls.from_dict(payload)

    @classmethod
    def from_yaml(cls, path: str | Path) -> ProjectConfig:
        """Load a :class:`ProjectConfig` from a YAML file.

        Requires the optional ``yaml`` extra (``pip install ccdc-segment[yaml]``).
        """
        try:
            import yaml
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required to load YAML configs. "
                "Install it with: pip install 'ccdc-segment[yaml]'"
            ) from exc

        file_path = Path(path)
        with file_path.open("r", encoding="utf-8") as fh:
            payload = yaml.safe_load(fh)
        return cls.from_dict(payload or {})

    def to_dict(self) -> dict[str, Any]:
        """Serialize the configuration to a JSON-compatible dictionary."""
        return {
            "aoi_asset": self.aoi_asset,
            "seasons": self.seasons.to_dict(),
            "export": self.export.to_dict(),
            "ccdc_tiles": {k: list(v) for k, v in self.ccdc_tiles.items()},
            "tol_years": self.tol_years,
        }

    def resolve_aoi(
        self,
        aoi: str | ee.Geometry | ee.FeatureCollection | None = None,
    ) -> ee.Geometry:
        """Resolve an AOI geometry from an explicit argument or ``self.aoi_asset``.

        Parameters
        ----------
        aoi : str, ee.Geometry, ee.FeatureCollection, or None, optional
            Explicit geometry, feature collection, or GEE FeatureCollection asset ID.
            When ``None``, falls back to ``self.aoi_asset``.

        Returns
        -------
        ee.Geometry
            Study-area geometry.
        """
        target = self.aoi_asset if aoi is None else aoi
        if target is None:
            raise ValueError(
                "No AOI provided and ProjectConfig.aoi_asset is None. "
                "Pass an explicit geometry/asset ID or set aoi_asset."
            )
        if isinstance(target, str):
            return ee.FeatureCollection(target).geometry()
        if isinstance(target, ee.FeatureCollection):
            return target.geometry()
        return target
