# `ccdc_segment` — Earth Engine Python API Package

A modular, lightweight Google Earth Engine Python package for optical surface reflectance harmonization (Landsat 5/7/8/9 and Sentinel-2 + Cloud Score+), temporal compositing, sensor-agnostic CCDC segmentation, trend-clamped synthetic reconstruction, harmonic phenology extraction, multi-epoch stability filtering, and tiled batch export orchestration.

## Installation

From the repository root:

```bash
# Core package (earthengine-api only)
pip install -e ./python

# With YAML configuration support
pip install -e "./python[yaml]"

# With development tools (pytest, ruff, PyYAML)
pip install -e "./python[dev]"
```

Requires **Python 3.10+** and an authenticated Google Earth Engine account (`earthengine authenticate`).

## Quick Start

```python
import ee
from ccdc_segment.ccdc import CCDCModel, CCDCParams, CCDCProfile
from ccdc_segment.inputs import composite, s2

ee.Initialize()

aoi = ee.Geometry.Rectangle([125.5, -8.7, 125.7, -8.5])

# Stage 1: Cloud Score+ masked S2 scaled to 0..10000 for CCDC
col = s2.get_collection(aoi, "2020-01-01", "2025-12-31", reflectance_scale=10000.0)
monthly = composite.to_monthly_median(col, "2020-01-01", "2025-12-31")

# Stage 2 & 3: Fit CCDC and reconstruct seasonal reflectance
model = CCDCModel.fit(monthly, params=CCDCParams.sentinel2(), profile=CCDCProfile.standard())
dry_2025 = model.synthetic(2025.65)
harm_2025 = model.harmonics(2025.50)
stable = model.stable_in_period(2020.0, 2025.99)
```

For full architecture notes, JS-to-Python migration mappings, and recipes, see [docs/PYTHON_API_GUIDE.md](../docs/PYTHON_API_GUIDE.md) and [docs/CCDC_TEMPORAL_SEGMENTATION.md](../docs/CCDC_TEMPORAL_SEGMENTATION.md).

## Testing & Code Quality

Offline unit tests run without GEE credentials:

```bash
cd python
pytest
ruff check src tests examples
```

To run live Google Earth Engine smoke tests against public datasets:

```bash
RUN_GEE_TESTS=1 pytest -m gee
```
