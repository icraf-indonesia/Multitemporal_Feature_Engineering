# Multitemporal Feature Engineering

A Google Earth Engine (GEE) **JavaScript** and **Python (`ccdc_segment`)** library for preparing optical and radar feature stacks for multitemporal land use and land cover (LULC) mapping.

The repository combines harmonized Landsat and Sentinel-2 time series, Continuous Change Detection and Classification (CCDC), seasonal synthetic reflectance reconstruction, Sentinel-1 and PALSAR-derived radar features, spectral indices, GLCM texture, terrain variables, and tiled Python batch export orchestration.

## Features

- Harmonized surface reflectance from Landsat 5/7/8/9 and Sentinel-2 (JS & Python)
- Cloud, cloud-shadow, snow, fill, and SLC-off masking (JS & Python)
- Monthly median and wet/dry seasonal composites (JS & Python)
- CCDC fitting, nearest-segment lookup, trend-clamped synthetic reconstruction, harmonics, and stability filtering (JS & Python)
- Programmatic tiled CCDC batch exports with auto-grid generation, dry-run previews, and `skip_existing` resume support (Python)
- Wet/dry spectral indices and phenological deltas (JS)
- Sentinel-1 analysis-ready backscatter with terrain flattening and speckle filtering (JS)
- ALOS-2/PALSAR-2 ScanSAR and PALSAR backscatter (JS)
- GLCM texture and NASADEM terrain features (JS)
- Decoupled JSON/YAML project configuration (`ProjectConfig` in Python) and GEE export helpers

## Repository Structure

```text
src/                              GEE Code Editor JavaScript library (kept standalone for GEE sync)
  config.js                       Project AOI, CRS, scales, class schema, and exports
  features.js                     Optical, SAR, texture, and terrain feature helpers
  inputs/
    landsat.js                    Landsat 5/7/8/9 Collection 2 input preparation
    s2.js                         Sentinel-2 and Cloud Score+ input preparation
    composite.js                  Monthly and seasonal composite generation
  ccdc/
    core.js                       Sensor-independent CCDC operations
    ccdc_landsat.js               Landsat compatibility facade
    ccdc_sentinel2.js             Sentinel-2 compatibility facade
python/                           Earth Engine Python API package (ccdc-segment)
  pyproject.toml                  Package metadata, ruff & pytest configuration
  README.md                       Python package installation & test guide
  src/ccdc_segment/
    constants.py                  Shared optical schema & CCDC library defaults
    config.py                     Externalizable ProjectConfig (dict / JSON / YAML)
    inputs/                       Landsat, Sentinel-2 + Cloud Score+, and composites
    ccdc/                         Typed specs, fitting, reconstruction, stability, & CCDCModel
    export.py                     Asset/Drive exports, tile grid, & idempotent tiled CCDC exports
  examples/                       External project config & runnable Python workflows
  tests/                          Offline pytest suite + gated live GEE smoke tests
docs/
  CCDC_TEMPORAL_SEGMENTATION.md   Scientific methodology & dual-runtime stage architecture
  PYTHON_API_GUIDE.md             Python API design, JS-to-Python migration table, & recipes
.gitignore
LICENSE
```

## Requirements

- A Google Earth Engine account
- Access to the required public GEE datasets
- **JavaScript (`src/`)**: Earth Engine Code Editor (or GEE JS module loader) and `users/dmlmont/spectral:spectral` for `src/features.js`
- **Python (`python/`)**: Python 3.10+ and `earthengine-api` (installed via `pyproject.toml`; optional `PyYAML` for YAML configs)

## Installation

### Python API (`ccdc_segment`)

```bash
# Core package (earthengine-api only)
pip install -e ./python

# Optional YAML config support or development tools (pytest, ruff)
pip install -e "./python[yaml]"
pip install -e "./python[dev]"
```

### Earth Engine JavaScript (`src/`)

The `src/` directory is intended to be added to an Earth Engine user's module repository and loaded with `require()`.

For example, publish the `src` directory so that it appears as the `Luma` module, then use:

```javascript
var cfg = require('users/your-user/Luma:config');
var s2 = require('users/your-user/Luma:inputs/s2');
var core = require('users/your-user/Luma:ccdc/core');
var features = require('users/your-user/Luma:features');
```

The JS source currently uses the `users/rg2icraf/Luma` namespace in cross-module imports and comments. When deploying under a different GEE account or module name, update those `require()` paths consistently.

## Quick Start

### Python API (`ccdc_segment`): Sentinel-2 CCDC & Synthetic Stack

```python
import ee
from ccdc_segment.ccdc import CCDCModel, CCDCParams, CCDCProfile
from ccdc_segment.inputs import composite, s2

ee.Initialize()
aoi = ee.Geometry.Rectangle([125.5, -8.7, 125.7, -8.5])

s2_col = s2.get_collection(aoi, "2020-01-01", "2025-12-31", reflectance_scale=10000.0)
monthly = composite.to_monthly_median(s2_col, "2020-01-01", "2025-12-31")

model = CCDCModel.fit(monthly, params=CCDCParams.sentinel2(), profile=CCDCProfile.standard())
dry_2025 = model.synthetic(2025.65)
harm_2025 = model.harmonics(2025.50)
stable_2020_2025 = model.stable_in_period(2020.0, 2025.99)
```

See [Python API Guide](docs/PYTHON_API_GUIDE.md) and [`python/examples/`](python/examples/) for tiled batch exports, legacy asset presets (`CCDCProfile.landsat_legacy()`, `CCDCProfile.google_global()`), and external JSON/YAML configuration.

### JavaScript API (`src/`): Sentinel-2 synthetic dry-season image

```javascript
var cfg = require('users/your-user/Luma:config');
var s2 = require('users/your-user/Luma:inputs/s2');
var core = require('users/your-user/Luma:ccdc/core');

var aoi = ee.FeatureCollection(cfg.AOI_ASSET).geometry();

var s2Collection = s2.getCollection(
  aoi,
  '2020-01-01',
  '2025-12-31',
  {
    clearThreshold: 0.60,
    qaBand: 'cs_cdf',
    reflectanceScale: 10000
  }
);

var ccdc = core.runCCDC(s2Collection, {
  breakpointBands: ['green', 'red', 'nir', 'swir1'],
  minObservations: 6,
  lambda: 20
});

var dry2025 = core.getSyntheticStack(ccdc, 2025.65, {
  bands: ['blue', 'green', 'red', 'nir', 'swir1', 'swir2'],
  coefScale: 10000,
  coefCase: 'lower',
  tolYears: 1.0
});

Map.centerObject(aoi, 10);
Map.addLayer(dry2025, {
  bands: ['red', 'green', 'blue'],
  min: 0,
  max: 0.3
}, '2025 dry-season synthetic reflectance');
```

The fractional-year convention is a calendar year plus a season fraction. The default project fractions are approximately:

- Wet: `0.16`
- Dry: `0.65`
- Harmonic midpoint: `0.50`

### Landsat time series

```javascript
var landsat = require('users/your-user/Luma:inputs/landsat');
var core = require('users/your-user/Luma:ccdc/core');

var aoi = ee.FeatureCollection(cfg.AOI_ASSET).geometry();
var collection = landsat.getCollection(
  aoi,
  '2000-01-01',
  '2025-12-31',
  { reflectanceScale: 10000 }
);

var ccdc = core.runCCDC(collection, {
  breakpointBands: ['green', 'red', 'nir', 'swir1', 'swir2'],
  tmaskBands: ['green', 'swir1']
});
```

## Direct Composite Mode

CCDC is optional. Optical collections can be used directly with fractional reflectance for rapid composites:

```javascript
var s2 = require('users/your-user/Luma:inputs/s2');
var composite = require('users/your-user/Luma:inputs/composite');

var aoi = ee.FeatureCollection(cfg.AOI_ASSET).geometry();
var collection = s2.getCollection(
  aoi,
  '2024-01-01',
  '2025-12-31',
  { reflectanceScale: 1.0 }
);

var monthly = composite.toMonthlyMedian(
  collection,
  '2024-01-01',
  '2025-12-31'
);

var dry2025 = composite.seasonalComposite(
  collection,
  2025,
  6,
  10,
  'median'
);
```

## Feature Examples

```javascript
var features = require('users/your-user/Luma:features');

var indices = features.computeSeasonalIndices(
  dry2025,
  'S2',
  ['NDVI', 'MNDWI', 'NDBI'],
  'dry'
);

var texture = features.getGlcmTexture(
  dry2025.select('nir')
);

var s1 = features.getSeasonalS1(2025, aoi, {
  wetMonths: [12, 4],
  dryMonths: [5, 11],
  applyTerrainFlattening: true,
  applySpeckleFilter: true
});

var terrain = features.getTopography(aoi);
```

Available feature helpers include SAR speckle filtering, Sentinel-1 seasonal backscatter, PALSAR/ScanSAR features, GLCM texture, phenological index deltas, and topographic variables.

## Configuration

[`src/config.js`](src/config.js) is the central configuration module. Before using the repository, review and customize:

- `DEFAULT_AOI_ASSET`
- `DEFAULT_CRS`
- `SCALE`
- `CLASS_SCHEMA` and `CLASS_PALETTE`
- `SMOOTHNESS`
- `LANDSAT_CCDC_TILES`
- `S2_CCDC_TILES`
- `S2_SNIC_TILES`
- `CCDC_COEF_SCALE`

Use `cfg.toAsset()` or `cfg.toDrive()` for export tasks with the repository's default CRS, scale, pixel limit, and pyramiding policy.

```javascript
cfg.toAsset(dry2025, 'projects/your-project/assets/dry_2025', {
  region: aoi,
  scale: cfg.SCALE.S2,
  pyramidingPolicy: {'.default': 'mean'}
});
```

## CCDC and Export Notes

- CCDC inputs should use reflectance scaling of `10000`; direct composites can use `1.0`.
- Custom CCDC coefficient arrays commonly use `coefScale: 10000`.
- Google's `GOOGLE/GLOBAL_CCDC/V1` coefficients may use `coefScale: 1`.
- Use lowercase coefficient bands for standard assets (`blue_coefs`) and uppercase bands for legacy Landsat assets (`BLUE_coefs`).
- Use `pyramidingPolicy: {'.default': 'sample'}` when exporting CCDC array images.

For the complete model formulation and methodological safeguards, see [CCDC Temporal Segmentation & Synthetic Reconstruction Architecture](docs/CCDC_TEMPORAL_SEGMENTATION.md) and the [Python API Guide](docs/PYTHON_API_GUIDE.md).

## Contributing & Repository Best Practices

Contributions should preserve the stage-based architecture and maintain JS/Python parity:

1. Keep `src/` strictly GEE-compatible JavaScript (do not mix Python build artifacts or tooling into `src/`).
2. Keep sensor-specific ingestion and QA logic in `src/inputs/` (JS) and `python/src/ccdc_segment/inputs/` (Python).
3. Keep sensor-independent CCDC mathematics in `src/ccdc/core.js` (JS) and `python/src/ccdc_segment/ccdc/` (Python).
4. Preserve the common six-band lowercase optical schema (`['blue', 'green', 'red', 'nir', 'swir1', 'swir2']`) across both runtimes.
5. Keep study-area asset IDs, CRS, credentials, and seasonal dates out of Python library code—use external `ProjectConfig` JSON/YAML files (and `src/config.js` in JS).
6. Run offline verification before opening a pull request on Python code:
   ```bash
   pytest python
   ruff check python/src python/tests python/examples
   ```
7. Update `docs/CCDC_TEMPORAL_SEGMENTATION.md` whenever scientific formulas, defaults, or safeguards change so JavaScript and Python implementations never silently diverge.

## License

This project is licensed under the GNU General Public License v3.0. See [`LICENSE`](LICENSE).
