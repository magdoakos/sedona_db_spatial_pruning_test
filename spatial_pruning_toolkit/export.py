"""Export row group bounding boxes to GeoJSON for visualization."""

import json
import pyarrow.parquet as pq
from pathlib import Path


def rowgroup_bboxes_to_geojson(
    parquet_path: str | Path,
    output_path: str | Path,
    geometry_column: str = "geometry",
):
    """Extract per-row-group bounding boxes and write them as GeoJSON polygons.

    Useful for visualizing how row groups cover geographic space — e.g. to
    confirm that Hilbert sorting produces spatially compact row groups.

    Args:
        parquet_path: Path to a GeoParquet file with GeospatialStatistics.
        output_path: Output GeoJSON file path.
        geometry_column: Name of the geometry column to read bbox stats from.
    """
    pf = pq.ParquetFile(str(parquet_path))
    md = pf.metadata
    geom_idx = pf.schema_arrow.get_field_index(geometry_column)

    features = []
    for rg_idx in range(md.num_row_groups):
        col = md.row_group(rg_idx).column(geom_idx)
        if not col.is_geo_stats_set:
            continue

        gs = col.geo_statistics.to_dict()
        try:
            xmin = float(gs["xmin"])
            ymin = float(gs["ymin"])
            xmax = float(gs["xmax"])
            ymax = float(gs["ymax"])
        except (KeyError, TypeError):
            continue

        polygon = [
            [xmin, ymin],
            [xmin, ymax],
            [xmax, ymax],
            [xmax, ymin],
            [xmin, ymin],
        ]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [polygon]},
            "properties": {"row_group": rg_idx},
        })

    geojson = {"type": "FeatureCollection", "features": features}

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, indent=2)

    print(f"Wrote {len(features)} row group bboxes to {output_path}")
