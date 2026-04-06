from __future__ import annotations
from spatial_pruning_toolkit import (
    pull_overture,
    hilbert_sort,
    add_geo_statistics,
    ParquetAnalyzer,
    rowgroup_bboxes_to_geojson,
    SpatialPruningTest,
)

pull_overture(
    output_path="data/places.parquet",
    bbox=(1.796265, 48.42191, 3.312378, 49.378797),
)

hilbert_sort(
    input_path="data/places.parquet",
    output_path="data/places_hilbert.parquet",
    row_group_size=120_000,
)

add_geo_statistics(
    input_path="data/places_hilbert.parquet",
    output_path="data/places_hilbert_geostats.parquet",
    row_group_size=120000,
)

analyzer = ParquetAnalyzer("data/places_hilbert_geostats.parquet")
analyzer.summary()
analyzer.print_geo_statistics()

rowgroup_bboxes_to_geojson(
    parquet_path="data/places_hilbert_geostats.parquet",
    output_path="data/bboxes.geojson",
)

test = SpatialPruningTest(
    parquet_files=[
        ("data/places_hilbert.parquet", "No GeoStats"),
        ("data/places_hilbert_geostats.parquet", "Hilbert + GeoStats"),
    ],
    query_wkt="POLYGON ((1.826906 48.464328, 1.848021 48.464328, 1.848021 48.47992, 1.826906 48.47992, 1.826906 48.464328))",
)
results = test.run()