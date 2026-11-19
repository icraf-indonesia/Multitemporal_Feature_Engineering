# Multitemporal Feature Engineering

A Google Earth Engine (GEE) JavaScript library for preparing optical and radar feature stacks for multitemporal land use and land cover (LULC) mapping.

The repository combines harmonized Landsat and Sentinel-2 time series, Continuous Change Detection and Classification (CCDC), seasonal synthetic reflectance reconstruction, Sentinel-1 and PALSAR-derived radar features, spectral indices, GLCM texture, and terrain variables.

## Features

- Harmonized surface reflectance from Landsat 5/7/8/9 and Sentinel-2
- Cloud, cloud-shadow, snow, fill, and SLC-off masking
- Monthly median and wet/dry seasonal composites
- CCDC fitting, nearest-segment lookup, synthetic reconstruction, and stability filtering
- Wet/dry spectral indices and phenological deltas
- Sentinel-1 analysis-ready backscatter with terrain flattening and speckle filtering
- ALOS-2/PALSAR-2 ScanSAR and PALSAR backscatter
- GLCM texture and NASADEM terrain features
- Shared project configuration and Earth Engine export helpers

## Repository Structure

```text
src/
  config.js                 Project AOI, CRS, scales, class schema, and exports
  features.js               Optical, SAR, texture, and terrain feature helpers
  inputs/
    landsat.js              Landsat 5/7/8/9 Collection 2 input preparation
    s2.js                   Sentinel-2 and Cloud Score+ input preparation
    composite.js            Monthly and seasonal composite generation
  ccdc/
    core.js                 Sensor-independent CCDC operations
    ccdc_landsat.js         Landsat compatibility facade
    ccdc_sentinel2.js       Sentinel-2 compatibility facade
docs/
  CCDC_TEMPORAL_SEGMENTATION.md
LICENSE
```

## Requirements

- A Google Earth Engine account
- The Earth Engine Code Editor or an environment that loads GEE JavaScript modules
- Access to the required public GEE datasets
- The `users/dmlmont/spectral:spectral` GEE module for `src/features.js`

## Installation

This repository is intended to be added to an Earth Engine user's module repository and loaded with `require()`.

For example, publish the `src` directory so that it appears as the `Luma` module, then use:

```javascript
var cfg = require('users/your-user/Luma:config');
var s2 = require('users/your-user/Luma:inputs/s2');
var core = require('users/your-user/Luma:ccdc/core');
var features = require('users/your-user/Luma:features');
```

The source currently uses the `users/rg2icraf/Luma` namespace in cross-module imports and comments. When deploying under a different GEE account or module name, update those `require()` paths consistently.

## Quick Start

### Sentinel-2 synthetic dry-season image

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

For the complete model formulation and methodological safeguards, see [CCDC Temporal Segmentation & Synthetic Reconstruction Architecture](docs/CCDC_TEMPORAL_SEGMENTATION.md).

## Contributing

Contributions should preserve the stage-based architecture:

1. Keep sensor-specific ingestion and QA logic in `src/inputs/`.
2. Keep sensor-independent CCDC mathematics in `src/ccdc/core.js`.
3. Preserve the common six-band optical schema.
4. Add project-specific constants to `src/config.js` rather than hardcoding them in feature scripts.

## License

This project is licensed under the GNU General Public License v3.0. See [`LICENSE`](LICENSE).
