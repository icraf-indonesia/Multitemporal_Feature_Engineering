"""Unit tests for ``ccdc_segment.export``."""

from __future__ import annotations

import pytest
from conftest import FakeEE, FakeFeature

from ccdc_segment.export import (
    asset_exists,
    export_ccdc_tiles,
    export_to_asset,
    export_to_drive,
    make_tile_grid,
)


def test_asset_exists_checks_ee_data(fake_ee: FakeEE) -> None:
    fake_ee.existing_assets.add("projects/demo/assets/already_there")
    assert asset_exists("projects/demo/assets/already_there") is True
    assert asset_exists("projects/demo/assets/missing") is False


def test_make_tile_grid_from_bbox_and_aoi_filtering(fake_ee: FakeEE) -> None:
    # 1.0 x 1.0 deg box at 0.5 deg spacing -> 2x2 = 4 tiles without AOI filtering
    tiles = make_tile_grid(bbox=(125.0, -9.0, 126.0, -8.0), tile_size_deg=0.5, prefix="tl")
    assert list(tiles.keys()) == [
        "tl_r00_c00",
        "tl_r00_c01",
        "tl_r01_c00",
        "tl_r01_c01",
    ]

    # Single-RPC intersection pruning via AOI
    aoi = fake_ee.Geometry.Rectangle([125.0, -9.0, 126.0, -8.0])
    fake_ee.intersecting_tile_names = {"tl_r00_c00", "tl_r01_c01"}
    pruned = make_tile_grid(aoi, tile_size_deg=0.5, prefix="tl", filter_intersecting=True)
    assert list(pruned.keys()) == ["tl_r00_c00", "tl_r01_c01"]

    with pytest.raises(ValueError, match="tile_size_deg"):
        make_tile_grid(bbox=(0, 0, 1, 1), tile_size_deg=0)
    with pytest.raises(ValueError, match="Provide either"):
        make_tile_grid()


def test_export_to_asset_and_drive_respect_start_flag(fake_ee: FakeEE) -> None:
    img = fake_ee.Image("SYNTH")
    aoi = fake_ee.Geometry.Rectangle([0, 0, 1, 1])

    t_asset = export_to_asset(img, "projects/p/assets/out_img", region=aoi, scale=20, start=False)
    assert t_asset.started is False
    assert t_asset.kwargs["description"] == "out_img"
    assert t_asset.kwargs["pyramidingPolicy"] == {".default": "mean"}

    t_drive = export_to_drive(img, "out_cog", region=aoi, folder="MyDrive", start=True)
    assert t_drive.started is True
    assert t_drive.kwargs["formatOptions"] == {"cloudOptimized": True}
    assert t_drive.kwargs["folder"] == "MyDrive"


def test_export_ccdc_tiles_enforces_sample_pyramiding_skip_existing_and_dry_run(
    fake_ee: FakeEE,
) -> None:
    ccdc_img = fake_ee.Image("RAW_CCDC")
    tiles = {
        "west": fake_ee.Geometry.Rectangle([125.0, -9.0, 125.5, -8.5]),
        "east": fake_ee.Geometry.Rectangle([125.5, -9.0, 126.0, -8.5]),
    }
    fake_ee.existing_assets.add("projects/p/assets/CCDC_S2_west")

    # Dry run (start=False) skips 'west' and creates unstarted task for 'east'
    records = export_ccdc_tiles(
        ccdc_img,
        asset_prefix="projects/p/assets/CCDC_S2",
        tiles=tiles,
        scale=20,
        crs="EPSG:32751",
        trim_bands=True,
        skip_existing=True,
        start=False,
    )

    assert len(records) == 2
    assert records[0].tile_name == "west"
    assert records[0].status == "skipped_existing"
    assert records[0].task is None

    assert records[1].tile_name == "east"
    assert records[1].asset_id == "projects/p/assets/CCDC_S2_east"
    assert records[1].status == "created"
    assert records[1].task is not None
    assert records[1].task.started is False
    assert records[1].task.kwargs["pyramidingPolicy"] == {".default": "sample"}

    # Band trimming happened once
    assert any(
        name == "select" and args == (["tStart", "tEnd", "tBreak", "changeProb", ".*_coefs"],)
        for name, args, _ in fake_ee.calls
    )


def test_export_ccdc_tiles_supports_feature_collection_and_folder_prefix(fake_ee: FakeEE) -> None:
    ccdc_img = fake_ee.Image("RAW_CCDC")
    fc = fake_ee.FeatureCollection(
        [
            FakeFeature(fake_ee.Geometry.Rectangle([0, 0, 1, 1]), {"tile_id": "t1"}),
            FakeFeature(fake_ee.Geometry.Rectangle([1, 0, 2, 1]), {"tile_id": "t2"}),
        ]
    )

    records = export_ccdc_tiles(
        ccdc_img,
        asset_prefix="projects/p/assets/ccdc_folder/",
        tiles=fc,
        tile_name_property="tile_id",
        skip_existing=False,
        start=True,
    )
    assert [r.asset_id for r in records] == [
        "projects/p/assets/ccdc_folder/t1",
        "projects/p/assets/ccdc_folder/t2",
    ]
    assert all(r.status == "started" and r.task is not None and r.task.started for r in records)
