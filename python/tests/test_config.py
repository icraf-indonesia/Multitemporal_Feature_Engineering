"""Unit tests for ``ccdc_segment.config``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FakeEE, FakeGeometry

from ccdc_segment.config import ExportDefaults, ProjectConfig, SeasonFractions


def test_season_fractions_date_for_and_validation() -> None:
    seasons = SeasonFractions(wet=0.16, dry=0.65, harm=0.50)
    assert seasons.date_for(2025, "wet") == pytest.approx(2025.16)
    assert seasons.date_for(2025, "dry") == pytest.approx(2025.65)
    assert seasons.date_for(2025, "harm") == pytest.approx(2025.50)

    with pytest.raises(ValueError, match="Unknown season"):
        seasons.date_for(2025, "winter")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Season fraction"):
        SeasonFractions(dry=1.0)


def test_export_defaults_validation() -> None:
    with pytest.raises(ValueError, match="crs"):
        ExportDefaults(crs="")
    with pytest.raises(ValueError, match="scale"):
        ExportDefaults(scale=0)
    with pytest.raises(ValueError, match="max_pixels"):
        ExportDefaults(max_pixels=-5)


def test_project_config_json_roundtrip(tmp_path: Path) -> None:
    cfg = ProjectConfig(
        aoi_asset="projects/demo/assets/aoi",
        seasons=SeasonFractions(wet=0.20, dry=0.70, harm=0.50),
        export=ExportDefaults(crs="EPSG:32751", scale=20, drive_folder="MyFolder"),
        ccdc_tiles={"s2": ("projects/demo/assets/t1", "projects/demo/assets/t2")},
        tol_years=1.5,
    )
    out = tmp_path / "project.json"
    out.write_text(json.dumps(cfg.to_dict()), encoding="utf-8")

    loaded = ProjectConfig.from_json(out)
    assert loaded == cfg


def test_project_config_example_timor_leste_loads() -> None:
    example_path = Path(__file__).resolve().parents[1] / "examples" / "timor_leste.json"
    cfg = ProjectConfig.from_json(example_path)
    assert cfg.export.crs == "EPSG:32751"
    assert len(cfg.ccdc_tiles["landsat"]) == 5
    assert len(cfg.ccdc_tiles["s2"]) == 5
    assert cfg.seasons.date_for(2025, "dry") == pytest.approx(2025.65)


def test_project_config_yaml_loading(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    yaml_file = tmp_path / "project.yaml"
    yaml_file.write_text(
        "aoi_asset: projects/demo/assets/aoi\n"
        "seasons:\n  wet: 0.15\n  dry: 0.65\n  harm: 0.50\n"
        "export:\n  crs: EPSG:4326\n  scale: 30\n"
        "ccdc_tiles:\n  landsat:\n    - projects/demo/assets/tile1\n"
        "tol_years: 1.0\n",
        encoding="utf-8",
    )
    cfg = ProjectConfig.from_yaml(yaml_file)
    assert cfg.aoi_asset == "projects/demo/assets/aoi"
    assert cfg.export.scale == 30
    assert cfg.ccdc_tiles["landsat"] == ("projects/demo/assets/tile1",)


def test_resolve_aoi_variants(fake_ee: FakeEE) -> None:
    cfg = ProjectConfig(aoi_asset="projects/demo/assets/aoi")

    # Fallback to aoi_asset string
    geom_from_default = cfg.resolve_aoi()
    assert isinstance(geom_from_default, FakeGeometry)
    assert any(
        name == "ee.FeatureCollection" and args == ("projects/demo/assets/aoi",)
        for name, args, _ in fake_ee.calls
    )

    # Explicit FeatureCollection
    fc = fake_ee.FeatureCollection("projects/demo/assets/other")
    geom_from_fc = cfg.resolve_aoi(fc)
    assert isinstance(geom_from_fc, FakeGeometry)

    # Explicit Geometry passthrough
    raw_geom = fake_ee.Geometry.Rectangle([0, 0, 1, 1])
    assert cfg.resolve_aoi(raw_geom) is raw_geom

    # Missing AOI raises ValueError
    with pytest.raises(ValueError, match="No AOI provided"):
        ProjectConfig().resolve_aoi()
