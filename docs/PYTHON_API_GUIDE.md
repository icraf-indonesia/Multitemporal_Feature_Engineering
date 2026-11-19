# Python API Guide (`ccdc_segment`)

This guide covers the architecture, design rationale, JavaScript-to-Python migration mapping, and common workflows for the `ccdc_segment` Earth Engine Python package under [`python/`](../python/).

For the mathematical formulation of CCDC harmonic regression, trend clamping, plausibility bounds, and multi-epoch stability filtering, see [CCDC Temporal Segmentation & Synthetic Reconstruction Architecture](CCDC_TEMPORAL_SEGMENTATION.md).

---

## 1. Architecture & Design Rationale

`ccdc_segment` preserves the **stage-based architecture** of the GEE JavaScript library while redesigning module boundaries to fit Python's Earth Engine API:

1. **Stage 1 — Optical Harmonization (`ccdc_segment.inputs`)**:
   - `landsat.get_collection()` (Landsat 5/7/8/9 Collection 2 L2, selectable mission subsets, `QA_PIXEL` bitmasking) and `s2.get_collection()` (Sentinel-2 L2A + Cloud Score+) both emit the exact six-band lowercase schema: `['blue', 'green', 'red', 'nir', 'swir1', 'swir2']`.
   - `composite.to_monthly_median()` and `composite.seasonal_composite()` support both CCDC pre-aggregation and direct composite mode without CCDC.
2. **Stage 2 — CCDC Fitting & Batch Export (`ccdc_segment.ccdc.fit`, `ccdc_segment.export`)**:
   - `CCDCParams` replaces untyped option dicts with frozen, validated presets (`CCDCParams.landsat()`, `CCDCParams.sentinel2()`) and safely maps `lambda_` to `"lambda"` for `ee.Algorithms.TemporalSegmentation.Ccdc`.
   - `export_ccdc_tiles()` leverages `ee.batch` for reproducible tiled exports with automatic band trimming (`prepare_ccdc_for_export`), mandatory `{'.default': 'sample'}` pyramiding, `skip_existing=True` idempotency, and `start=False` dry-run previews.
3. **Stage 3 — Sensor-Agnostic Evaluation (`ccdc_segment.ccdc.reconstruct`, `ccdc_segment.ccdc.stability`, `ccdc_segment.ccdc.model`)**:
   - Legacy JS compatibility facades (`ccdc_landsat.js`, `ccdc_sentinel2.js`) are **not ported**. Instead, `CCDCProfile` captures asset-specific metadata (`coef_scale`, `coef_case`, `harm_case`, `tol_years`, `bounds`) once.
   - **Hybrid API**: Every operation is available both as a pure stateless function (e.g., `get_synthetic_stack(img, 2025.65, profile=...)`) and as a method on the lightweight `CCDCModel` wrapper (`model.synthetic(2025.65)`).
4. **Decoupled Project Configuration (`ccdc_segment.config`)**:
   - Study-area AOIs, CRS, tile lists, and regional monsoon fractions live in external JSON/YAML files loaded via `ProjectConfig`—never hardcoded inside library modules.

---

## 2. JavaScript-to-Python Migration Table

| GEE JavaScript (`src/`) | Python (`ccdc_segment`) | Notes |
|---|---|---|
| `inputs/landsat.getCollection(roi, start, end, opts)` | `inputs.landsat.get_collection(roi, start, end, ...)` | Adds `sensors=("L5", "L7", "L8", "L9")` filter and `LandsatOptions`. |
| `inputs/s2.getCollection(roi, start, end, opts)` | `inputs.s2.get_collection(roi, start, end, ...)` | Adds `Sentinel2Options` validation. |
| `inputs/composite.toMonthlyMedian(col, start, end)` | `inputs.composite.to_monthly_median(col, start, end)` | Identical 15th-of-month stamping and `n > 0` filtering. |
| `inputs/composite.seasonalComposite(col, yr, m1, m2, red)` | `inputs.composite.seasonal_composite(col, yr, m1, m2, reducer=...)` | Fixes JS `endMonth == 12` rollover via `.advance(1, "month")`. |
| `ccdc/core.runCCDC(col, opts)` | `ccdc.run_ccdc(col, params=CCDCParams.sentinel2())` | Maps `lambda_` → `"lambda"`; preserves explicit `lambda_=0.0`. |
| `ccdc/core.nearestSegment(ccdc, t)` | `ccdc.nearest_segment(ccdc, t)` | Returns typed `SegmentMatch(idx, gap, t_start, t_end)`. |
| `ccdc/core.fillIsolated(img, minN)` | `ccdc.fill_isolated(img, min_neighbors=5)` | Validates `1 <= min_neighbors <= 8`. |
| `ccdc/core.getSyntheticStack(ccdc, t, opts)` | `ccdc.get_synthetic_stack(ccdc, t, profile=...)` or `model.synthetic(t)` | Adds `include_diagnostics=True` toggle; excludes spectral indices. |
| `ccdc/core.getHarmonics(ccdc, t, opts)` | `ccdc.get_harmonics(ccdc, t, profile=...)` or `model.harmonics(t)` | Output band case controlled via `CCDCProfile.harm_case` or `output_case`. |
| `ccdc/core.stableInPeriod(ccdc, s, e, opts)` | `ccdc.stable_in_period(ccdc, s, e, profile=...)` or `model.stable_in_period(s, e)` | Symmetric `floor(year) + 0.50` midpoints; configurable `drift_bands`. |
| `ccdc/ccdc_landsat.js` (legacy facade) | `CCDCModel.from_tiles(..., profile=CCDCProfile.landsat_legacy())` | Drops positional-argument hacks and duplicated index math. |
| `ccdc/ccdc_sentinel2.js` (legacy facade) | `CCDCModel.from_tiles(..., profile=CCDCProfile.standard())` | Multi-year helper preserved as `model.synthetic_series()` / `get_multi_year_stacks()`. |
| `config.loadCCDCTiles()` / `features.loadCCDCMosaic()` | `ccdc.load_ccdc_mosaic(source, aoi=...)` | Unified loader for single image, tile ID list, or `ImageCollection`. |
| `config.toAsset()` / `config.toDrive()` | `export.export_to_asset()`, `export.export_to_drive()`, `export.export_ccdc_tiles()` | Adds `make_tile_grid()`, `asset_exists()`, `skip_existing`, and dry-run `start=False`. |

---

## 3. Common Recipes

### 3.1. Direct Composite Mode (No CCDC)

```python
import ee
from ccdc_segment.inputs import composite, s2

ee.Initialize()
aoi = ee.Geometry.Rectangle([125.5, -8.7, 125.7, -8.5])

col = s2.get_collection(aoi, "2024-01-01", "2025-12-31", reflectance_scale=1.0)
dry_2025 = composite.seasonal_composite(col, 2025, start_month=6, end_month=10, reducer="median")
wet_2025 = composite.seasonal_composite(col, 2025, start_month=12, end_month=4, reducer="median")
```

### 3.2. Functional Style vs. `CCDCModel` Facade

Use **stateless functions** when composing custom pipelines or passing individual `ee.Image` objects between steps:

```python
from ccdc_segment.ccdc import CCDCProfile, get_harmonics, get_synthetic_stack

profile = CCDCProfile.google_global()
dry_2018 = get_synthetic_stack(global_ccdc_img, 2018.65, profile=profile, include_diagnostics=False)
harm_2018 = get_harmonics(global_ccdc_img, 2018.50, profile=profile)
```

Use **`CCDCModel`** when calling multiple operations against the same CCDC mosaic so you configure `CCDCProfile` only once:

```python
from ccdc_segment.ccdc import CCDCModel, CCDCProfile

model = CCDCModel.from_tiles(
    "GOOGLE/GLOBAL_CCDC/V1",
    aoi=aoi,
    profile=CCDCProfile.google_global(),
    is_collection=True,
)
series = model.synthetic_series([2015, 2017, 2019], season_fraction=0.65)
stable = model.stable_in_period(2015.0, 2019.99)
```

### 3.3. Loading Project Config & Legacy Timor-Leste Assets

```python
from ccdc_segment.ccdc import CCDCModel, CCDCProfile
from ccdc_segment.config import ProjectConfig

cfg = ProjectConfig.from_json("python/examples/timor_leste.json")
aoi = cfg.resolve_aoi()

landsat_model = CCDCModel.from_tiles(
    cfg.ccdc_tiles["landsat"],
    aoi=aoi,
    profile=CCDCProfile.landsat_legacy(tol_years=cfg.tol_years),
)
wet_2015 = landsat_model.synthetic(cfg.seasons.date_for(2015, "wet"))
```

### 3.4. Idempotent Tiled CCDC Batch Export

```python
from ccdc_segment.export import export_ccdc_tiles, make_tile_grid

tiles = make_tile_grid(aoi, tile_size_deg=0.5, prefix="tl", filter_intersecting=True)

# 1. Dry run: verify asset names and already-exported tiles without launching tasks
plan = export_ccdc_tiles(
    ccdc_img,
    asset_prefix="projects/my-proj/assets/CCDC_S2_2020_2025",
    tiles=tiles,
    scale=20,
    crs="EPSG:32751",
    trim_bands=True,
    skip_existing=True,
    start=False,
)

# 2. Submit only missing tiles once the plan looks right
submitted = export_ccdc_tiles(
    ccdc_img,
    asset_prefix="projects/my-proj/assets/CCDC_S2_2020_2025",
    tiles=tiles,
    scale=20,
    crs="EPSG:32751",
    trim_bands=True,
    skip_existing=True,
    start=True,
)
```

---

## 4. Development & Verification Workflow

```bash
# Install editable package with dev tools
pip install -e "./python[dev]"

# Run offline unit tests (no GEE credentials needed)
pytest python

# Run linter
ruff check python/src python/tests python/examples

# Optional: run live Earth Engine smoke tests against public archives
RUN_GEE_TESTS=1 pytest python -m gee
```
