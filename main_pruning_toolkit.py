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
    bbox=(3.18604,51.08282,7.42676,53.18629),
    row_group_size=50000
)

hilbert_sort(
    input_path="data/places.parquet",
    output_path="data/places_hilbert_sorted.parquet",
    row_group_size=50_000,
)

add_geo_statistics(
    input_path="data/places_hilbert_sorted.parquet",
    output_path="data/places_hilbert_sorted_geostats.parquet",
    row_group_size=50000,
)

analyzer = ParquetAnalyzer("data/places_hilbert_sorted_geostats.parquet")
analyzer.summary()
analyzer.print_geo_statistics()

rowgroup_bboxes_to_geojson(
    parquet_path="data/places_hilbert_sorted_geostats.parquet",
    output_path="data/bboxes.geojson",
)

test = SpatialPruningTest(
    parquet_files=[
        ("data/places_hilbert_sorted.parquet", "Sorted No GeoStats"),
        ("data/places_hilbert_sorted_geostats.parquet", "Sorted With GeoStats"),
    ],
    query_wkt="POLYGON ((5.474067 51.440808, 5.485868 51.440808, 5.485868 51.445983, 5.474067 51.445983, 5.474067 51.440808))",
)
results = test.run()