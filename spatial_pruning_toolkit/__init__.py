"""spatial_pruning_toolkit — tools for testing spatial row group pruning in GeoParquet.

Modules
-------
ingest     — Pull data from Overture Maps via DuckDB + S3.
optimize   — Hilbert-sort and add Parquet 2.11 GeospatialStatistics.
analyze    — Inspect Parquet metadata, schemas, and geo stats.
export     — Export row group bounding boxes to GeoJSON.
pruning_test — Benchmark spatial pruning with SedonaDB.

Quick start::

    from spatial_pruning_toolkit import (
        pull_overture,
        hilbert_sort,
        add_geo_statistics,
        ParquetAnalyzer,
        rowgroup_bboxes_to_geojson,
        SpatialPruningTest,
    )
"""

from spatial_pruning_toolkit.ingest import pull_overture
from spatial_pruning_toolkit.optimize import hilbert_sort, add_geo_statistics
from spatial_pruning_toolkit.analyze import ParquetAnalyzer
from spatial_pruning_toolkit.export import rowgroup_bboxes_to_geojson

# SpatialPruningTest requires optional sedona-db; lazy import to avoid
# hard dependency at package level.


def __getattr__(name):
    if name == "SpatialPruningTest":
        from spatial_pruning_toolkit.pruning_test import SpatialPruningTest
        return SpatialPruningTest
    raise AttributeError(f"module 'spatial_pruning_toolkit' has no attribute {name!r}")


__all__ = [
    "pull_overture",
    "hilbert_sort",
    "add_geo_statistics",
    "ParquetAnalyzer",
    "rowgroup_bboxes_to_geojson",
    "SpatialPruningTest",
]
