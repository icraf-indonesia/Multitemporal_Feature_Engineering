"""Shared pytest fixtures and an offline recording fake Earth Engine module.

Non-``gee`` tests automatically receive a deterministic fake ``ee`` module
bound onto all ``ccdc_segment`` submodules so every call graph, mapped
callback, parameter dictionary, and export task is verified offline without
GEE authentication.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from ccdc_segment import config as config_mod
from ccdc_segment import export as export_mod
from ccdc_segment.ccdc import fit as fit_mod
from ccdc_segment.ccdc import model as model_mod
from ccdc_segment.ccdc import reconstruct as reconstruct_mod
from ccdc_segment.ccdc import specs as specs_mod
from ccdc_segment.ccdc import stability as stability_mod
from ccdc_segment.inputs import composite as composite_mod
from ccdc_segment.inputs import landsat as landsat_mod
from ccdc_segment.inputs import s2 as s2_mod

_EE_MODULES = (
    config_mod,
    export_mod,
    fit_mod,
    model_mod,
    reconstruct_mod,
    specs_mod,
    stability_mod,
    composite_mod,
    landsat_mod,
    s2_mod,
)


class FakeEEException(Exception):
    """Offline stand-in for ``ee.EEException``."""


class FakeNode:
    """Generic chainable Earth Engine expression recorder."""

    def __init__(
        self,
        kind: str,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        *,
        parent: FakeNode | None = None,
        log: list[tuple[str, tuple[Any, ...], dict[str, Any]]] | None = None,
    ) -> None:
        self.kind = kind
        self.args = args
        self.kwargs = kwargs or {}
        self.parent = parent
        self._log = log if log is not None else []

    def _record(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self._log.append((name, args, kwargs))

    def _spawn(
        self,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> FakeNode:
        obj = object.__new__(self.__class__)
        FakeNode.__init__(obj, name, args, kwargs, parent=self, log=self._log)
        return obj

    def __getattr__(self, name: str) -> Callable[..., FakeNode]:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)

        def _method(*args: Any, **kwargs: Any) -> FakeNode:
            self._record(name, args, kwargs)
            return self._spawn(name, args, kwargs)

        return _method

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.kind!r}, args={self.args!r}, kwargs={self.kwargs!r})"


class FakeImage(FakeNode):
    """Fake ``ee.Image`` supporting static constructors and chaining."""


class FakeNumber(FakeNode):
    """Fake ``ee.Number``."""


class FakeDate(FakeNode):
    """Fake ``ee.Date``."""


class FakeGeometry(FakeNode):
    """Fake ``ee.Geometry`` with optional bbox coordinates for ``getInfo()``."""

    def __init__(
        self,
        kind: str,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        *,
        parent: FakeNode | None = None,
        log: list[tuple[str, tuple[Any, ...], dict[str, Any]]] | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> None:
        super().__init__(kind, args, kwargs, parent=parent, log=log)
        self.bbox = bbox

    def bounds(self, *args: Any, **kwargs: Any) -> FakeGeometry:
        self._record("bounds", args, kwargs)
        return FakeGeometry("bounds", args, kwargs, parent=self, log=self._log, bbox=self.bbox)

    def coordinates(self) -> FakeNode:
        self._record("coordinates", (), {})
        bbox = self.bbox or (0.0, 0.0, 1.0, 1.0)
        x0, y0, x1, y1 = bbox
        ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]

        class _Coords(FakeNode):
            def getInfo(self_inner) -> list[list[list[float]]]:
                return [ring]

        return _Coords("coordinates", parent=self, log=self._log)


class FakeFeature(FakeNode):
    """Fake ``ee.Feature`` holding geometry and properties."""

    def __init__(
        self,
        geom: Any,
        props: dict[str, Any] | None = None,
        *,
        log: list[tuple[str, tuple[Any, ...], dict[str, Any]]] | None = None,
    ) -> None:
        super().__init__("Feature", (geom, props), {}, log=log)
        self.geom = geom
        self.props = props or {}


class FakeImageCollection(FakeNode):
    """Fake ``ee.ImageCollection`` that executes ``.map(fn)`` callbacks immediately."""

    def map(self, fn: Callable[[FakeImage], Any]) -> FakeImageCollection:
        self._record("map", (fn,), {})
        mapped_result = fn(FakeImage("mapped_image", log=self._log))
        node = FakeImageCollection(
            "map", (mapped_result,), {}, parent=self, log=self._log
        )
        node.mapped_result = mapped_result
        return node

    def mosaic(self) -> FakeImage:
        self._record("mosaic", (), {})
        return FakeImage("mosaic", parent=self, log=self._log)

    def median(self) -> FakeImage:
        self._record("median", (), {})
        return FakeImage("median", parent=self, log=self._log)

    def mean(self) -> FakeImage:
        self._record("mean", (), {})
        return FakeImage("mean", parent=self, log=self._log)

    def reduce(self, reducer: Any) -> FakeImage:
        self._record("reduce", (reducer,), {})
        return FakeImage("reduce", (reducer,), parent=self, log=self._log)


class FakeList(FakeNode):
    """Fake ``ee.List`` that executes ``.map(fn)`` callbacks immediately."""

    def map(self, fn: Callable[[FakeNumber], Any]) -> FakeList:
        self._record("map", (fn,), {})
        mapped_result = fn(FakeNumber("mapped_elem", log=self._log))
        node = FakeList("map", (mapped_result,), {}, parent=self, log=self._log)
        node.mapped_result = mapped_result
        return node


class FakeFeatureCollection(FakeNode):
    """Fake ``ee.FeatureCollection`` supporting tile filtering and ``aggregate_array``."""

    def __init__(
        self,
        source: Any,
        *,
        log: list[tuple[str, tuple[Any, ...], dict[str, Any]]] | None = None,
        intersecting_names: set[str] | None = None,
    ) -> None:
        super().__init__("FeatureCollection", (source,), {}, log=log)
        self.source = source
        self.intersecting_names = intersecting_names

    def geometry(self) -> FakeGeometry:
        self._record("geometry", (), {})
        return FakeGeometry("geometry", parent=self, log=self._log)

    def filterBounds(self, aoi: Any) -> FakeFeatureCollection:
        self._record("filterBounds", (aoi,), {})
        if isinstance(self.source, list) and self.intersecting_names is not None:
            filtered = [
                f
                for f in self.source
                if isinstance(f, FakeFeature)
                and f.props.get("tile_name") in self.intersecting_names
            ]
            return FakeFeatureCollection(
                filtered, log=self._log, intersecting_names=self.intersecting_names
            )
        return FakeFeatureCollection(
            self.source, log=self._log, intersecting_names=self.intersecting_names
        )

    def filter(self, flt: Any) -> FakeFeatureCollection:
        self._record("filter", (flt,), {})
        return FakeFeatureCollection(
            self.source, log=self._log, intersecting_names=self.intersecting_names
        )

    def aggregate_array(self, prop: str) -> FakeNode:
        self._record("aggregate_array", (prop,), {})
        values: list[Any] = []
        if isinstance(self.source, list):
            for feat in self.source:
                if isinstance(feat, FakeFeature) and prop in feat.props:
                    values.append(feat.props[prop])

        class _Agg(FakeNode):
            def getInfo(self_inner) -> list[Any]:
                return list(values)

        return _Agg("aggregate_array", (prop,), parent=self, log=self._log)


class FakeTask:
    """Fake ``ee.batch.Task`` tracking creation kwargs and ``start()`` calls."""

    def __init__(self, kind: str, kwargs: dict[str, Any]) -> None:
        self.kind = kind
        self.kwargs = kwargs
        self.started = False

    def start(self) -> None:
        self.started = True


class FakeEE:
    """Self-contained fake ``ee`` namespace recording all graph and batch calls."""

    EEException = FakeEEException

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.existing_assets: set[str] = set()
        self.tasks: list[FakeTask] = []
        self.ccdc_calls: list[dict[str, Any]] = []
        self.intersecting_tile_names: set[str] | None = None

        outer = self

        class _Image(FakeImage):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                outer.calls.append(("ee.Image", args, kwargs))
                super().__init__("ee.Image", args, kwargs, log=outer.calls)

            @staticmethod
            def constant(value: Any) -> FakeImage:
                outer.calls.append(("ee.Image.constant", (value,), {}))
                return FakeImage("ee.Image.constant", (value,), log=outer.calls)

            @staticmethod
            def cat(images: Any) -> FakeImage:
                outer.calls.append(("ee.Image.cat", (images,), {}))
                return FakeImage("ee.Image.cat", (images,), log=outer.calls)

        class _ImageCollection(FakeImageCollection):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                outer.calls.append(("ee.ImageCollection", args, kwargs))
                super().__init__("ee.ImageCollection", args, kwargs, log=outer.calls)

            @staticmethod
            def fromImages(images: Any) -> FakeImageCollection:
                outer.calls.append(("ee.ImageCollection.fromImages", (images,), {}))
                return FakeImageCollection(
                    "ee.ImageCollection.fromImages", (images,), log=outer.calls
                )

        class _FeatureCollection(FakeFeatureCollection):
            def __init__(self, source: Any) -> None:
                outer.calls.append(("ee.FeatureCollection", (source,), {}))
                super().__init__(
                    source,
                    log=outer.calls,
                    intersecting_names=outer.intersecting_tile_names,
                )

        class _Geometry(FakeGeometry):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                outer.calls.append(("ee.Geometry", args, kwargs))
                super().__init__("ee.Geometry", args, kwargs, log=outer.calls)

            @staticmethod
            def Rectangle(coords: Any, **kwargs: Any) -> FakeGeometry:
                outer.calls.append(("ee.Geometry.Rectangle", (coords,), kwargs))
                bbox = (coords[0], coords[1], coords[2], coords[3])
                return FakeGeometry(
                    "ee.Geometry.Rectangle", (coords,), kwargs, log=outer.calls, bbox=bbox
                )

        class _Date(FakeDate):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                outer.calls.append(("ee.Date", args, kwargs))
                super().__init__("ee.Date", args, kwargs, log=outer.calls)

            @staticmethod
            def fromYMD(year: int, month: int, day: int) -> FakeDate:
                if not (1 <= month <= 12):
                    raise ValueError(f"Invalid month: {month}")
                outer.calls.append(("ee.Date.fromYMD", (year, month, day), {}))
                return FakeDate("ee.Date.fromYMD", (year, month, day), log=outer.calls)

        class _Number(FakeNumber):
            def __init__(self, val: Any) -> None:
                outer.calls.append(("ee.Number", (val,), {}))
                super().__init__("ee.Number", (val,), log=outer.calls)

        class _List(FakeList):
            @staticmethod
            def sequence(start: Any, end: Any) -> FakeList:
                outer.calls.append(("ee.List.sequence", (start, end), {}))
                return FakeList("ee.List.sequence", (start, end), log=outer.calls)

        class _Filter:
            @staticmethod
            def gt(name: str, value: Any) -> FakeNode:
                outer.calls.append(("ee.Filter.gt", (name, value), {}))
                return FakeNode("ee.Filter.gt", (name, value), log=outer.calls)

            @staticmethod
            def eq(name: str, value: Any) -> FakeNode:
                outer.calls.append(("ee.Filter.eq", (name, value), {}))
                return FakeNode("ee.Filter.eq", (name, value), log=outer.calls)

            @staticmethod
            def calendarRange(start: int, end: int, field: str) -> FakeNode:
                outer.calls.append(("ee.Filter.calendarRange", (start, end, field), {}))
                return FakeNode("ee.Filter.calendarRange", (start, end, field), log=outer.calls)

        class _Reducer:
            @staticmethod
            def min() -> FakeNode:
                outer.calls.append(("ee.Reducer.min", (), {}))
                return FakeNode("ee.Reducer.min", log=outer.calls)

            @staticmethod
            def max() -> FakeNode:
                outer.calls.append(("ee.Reducer.max", (), {}))
                return FakeNode("ee.Reducer.max", log=outer.calls)

            @staticmethod
            def sum() -> FakeNode:
                outer.calls.append(("ee.Reducer.sum", (), {}))
                return FakeNode("ee.Reducer.sum", log=outer.calls)

            @staticmethod
            def percentile(percentiles: list[Any]) -> FakeNode:
                outer.calls.append(("ee.Reducer.percentile", (percentiles,), {}))
                return FakeNode("ee.Reducer.percentile", (percentiles,), log=outer.calls)

        class _Kernel:
            @staticmethod
            def square(radius: int) -> FakeNode:
                outer.calls.append(("ee.Kernel.square", (radius,), {}))
                return FakeNode("ee.Kernel.square", (radius,), log=outer.calls)

        class _Feature(FakeFeature):
            def __new__(cls, geom: Any, props: dict[str, Any] | None = None) -> FakeFeature:
                outer.calls.append(("ee.Feature", (geom, props), {}))
                return FakeFeature(geom, props, log=outer.calls)

        class _TemporalSegmentation:
            @staticmethod
            def Ccdc(**kwargs: Any) -> FakeImage:
                outer.ccdc_calls.append(kwargs)
                outer.calls.append(("ee.Algorithms.TemporalSegmentation.Ccdc", (), kwargs))
                return FakeImage(
                    "ee.Algorithms.TemporalSegmentation.Ccdc", (), kwargs, log=outer.calls
                )

        class _Algorithms:
            TemporalSegmentation = _TemporalSegmentation

        class _Data:
            @staticmethod
            def getAsset(asset_id: str) -> dict[str, Any]:
                outer.calls.append(("ee.data.getAsset", (asset_id,), {}))
                if asset_id in outer.existing_assets:
                    return {"id": asset_id, "type": "IMAGE"}
                raise FakeEEException(f"Asset {asset_id!r} not found.")

        class _ExportImage:
            @staticmethod
            def toAsset(**kwargs: Any) -> FakeTask:
                outer.calls.append(("ee.batch.Export.image.toAsset", (), kwargs))
                task = FakeTask("toAsset", kwargs)
                outer.tasks.append(task)
                return task

            @staticmethod
            def toDrive(**kwargs: Any) -> FakeTask:
                outer.calls.append(("ee.batch.Export.image.toDrive", (), kwargs))
                task = FakeTask("toDrive", kwargs)
                outer.tasks.append(task)
                return task

        class _Export:
            image = _ExportImage

        class _Batch:
            Export = _Export
            Task = FakeTask

        self.Image = _Image
        self.ImageCollection = _ImageCollection
        self.FeatureCollection = _FeatureCollection
        self.Geometry = _Geometry
        self.Date = _Date
        self.Number = _Number
        self.List = _List
        self.Filter = _Filter
        self.Reducer = _Reducer
        self.Kernel = _Kernel
        self.Feature = _Feature
        self.Algorithms = _Algorithms
        self.data = _Data
        self.batch = _Batch


@pytest.fixture(autouse=True)
def fake_ee(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> FakeEE | None:
    """Bind ``FakeEE`` onto all ``ccdc_segment`` modules for offline unit tests."""
    if request.node.get_closest_marker("gee") is not None:
        return None
    fake = FakeEE()
    for mod in _EE_MODULES:
        monkeypatch.setattr(mod, "ee", fake)
    return fake
