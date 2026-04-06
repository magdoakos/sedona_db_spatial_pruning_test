"""Hilbert-sort GeoParquet files and add Parquet 2.11 GeospatialStatistics."""

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import geoarrow.pyarrow as ga
from pathlib import Path


def hilbert_sort(
    input_path: str | Path,
    output_path: str | Path,
    row_group_size: int = 120_000,
):
    """Sort a GeoParquet file by Hilbert curve order using DuckDB.

    Hilbert sorting clusters spatially nearby geometries into the same row
    groups, which is a prerequisite for effective spatial row group pruning.

    Args:
        input_path: Input GeoParquet file.
        output_path: Output Hilbert-sorted GeoParquet file.
        row_group_size: Target row group size for the output file.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")

    con.execute(f"""
        CREATE OR REPLACE TABLE __src AS
        SELECT * FROM read_parquet('{input_path}');
    """)

    xmin, ymin, xmax, ymax = con.execute("""
        SELECT ST_XMin(ext), ST_YMin(ext), ST_XMax(ext), ST_YMax(ext)
        FROM (SELECT ST_Extent(geometry) AS ext FROM __src)
    """).fetchone()
    box_2d = f"{{'min_x': {xmin}, 'min_y': {ymin}, 'max_x': {xmax}, 'max_y': {ymax}}}"

    con.execute(f"""
        COPY (
            SELECT * FROM __src
            ORDER BY ST_Hilbert(geometry, {box_2d}::BOX_2D)
        ) TO '{output_path}'
        (FORMAT PARQUET, ROW_GROUP_SIZE {row_group_size}, PARQUET_VERSION V2);
    """)

    total_rows = con.execute(f"""
        SELECT count(*) FROM read_parquet('{output_path}')
    """).fetchone()[0]

    con.close()

    print(f"Hilbert-sorted GeoParquet saved to {output_path}")
    print(f"Row group size: {row_group_size}")
    print(f"Total rows: {total_rows}")
    print(f"Estimated row groups: {(total_rows // row_group_size) + 1}")


def add_geo_statistics(
    input_path: str | Path,
    output_path: str | Path,
    num_row_groups: int | None = None,
    row_group_size: int | None = None,
):
    """Re-write a GeoParquet file with PyArrow so that Parquet 2.11
    GeospatialStatistics (per-row-group bounding boxes) are embedded.

    This enables query engines (SedonaDB, DuckDB 1.5+) to skip entire row
    groups whose bounding boxes don't intersect a spatial query filter.

    Specify either ``num_row_groups`` or ``row_group_size`` to re-partition,
    or leave both as None to preserve the original row group boundaries.

    Args:
        input_path: Input GeoParquet file (typically Hilbert-sorted).
        output_path: Output GeoParquet file with GeospatialStatistics.
        num_row_groups: Desired number of row groups (mutually exclusive
            with row_group_size).
        row_group_size: Desired rows per row group (mutually exclusive
            with num_row_groups).
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if num_row_groups and row_group_size:
        raise ValueError("Specify num_row_groups or row_group_size, not both.")

    if num_row_groups or row_group_size:
        table = pq.read_table(str(input_path))
        total_rows = len(table)
        if num_row_groups:
            row_group_size = -(-total_rows // num_row_groups)

        geom_col = table.column("geometry")
        geom_wkb = ga.as_wkb(geom_col)
        idx = table.schema.get_field_index("geometry")
        table = table.set_column(idx, pa.field("geometry", geom_wkb.type), geom_wkb)

        writer = pq.ParquetWriter(str(output_path), table.schema, version="2.6")
        for offset in range(0, total_rows, row_group_size):
            writer.write_table(table.slice(offset, row_group_size))
        writer.close()
    else:
        pf_in = pq.ParquetFile(str(input_path))
        writer = None
        idx = None
        for rg_idx in range(pf_in.metadata.num_row_groups):
            table = pf_in.read_row_group(rg_idx)
            geom_col = table.column("geometry")
            geom_wkb = ga.as_wkb(geom_col)
            idx = table.schema.get_field_index("geometry")
            table = table.set_column(idx, pa.field("geometry", geom_wkb.type), geom_wkb)
            if writer is None:
                writer = pq.ParquetWriter(str(output_path), table.schema, version="2.6")
            writer.write_table(table)
        writer.close()

    # Verify and report
    pf = pq.ParquetFile(str(output_path))
    md = pf.metadata
    geom_idx = pf.schema_arrow.get_field_index("geometry")
    print(f"GeoParquet with GeospatialStatistics saved to {output_path}")
    print(f"Row groups: {md.num_row_groups}")
    for rg_idx in range(md.num_row_groups):
        col = md.row_group(rg_idx).column(geom_idx)
        if col.is_geo_stats_set:
            gs = col.geo_statistics.to_dict()
            print(f"  RG {rg_idx}: bbox=[{gs['xmin']:.6f}, {gs['ymin']:.6f}, {gs['xmax']:.6f}, {gs['ymax']:.6f}]")
