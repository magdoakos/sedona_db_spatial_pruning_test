"""Pull data from Overture Maps via DuckDB + S3."""
from __future__ import annotations
import duckdb
from pathlib import Path


def pull_overture(
    output_path: str | Path,
    theme: str = "places",
    otype: str = "place",
    bbox: tuple[float, float, float, float] = (2.19727, 48.04871, 15.04193, 55.09916),
    release: str = "2026-03-18.0",
    row_group_size: int = 10000,
):
    """Download an Overture Maps extract filtered by bounding box.

    Args:
        output_path: Destination Parquet file path.
        theme: Overture theme (e.g. "places", "buildings").
        otype: Overture type within the theme (e.g. "place").
        bbox: (xmin, ymin, xmax, ymax) bounding box in EPSG:4326.
        release: Overture Maps release version string.
        row_group_size: Row group size for the output Parquet file.
    """
    xmin, ymin, xmax, ymax = bbox
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("INSTALL aws; LOAD aws;")
    con.execute("INSTALL spatial; INSTALL httpfs;")
    con.execute("LOAD spatial; LOAD httpfs;")
    con.execute("SET s3_region = 'us-west-2';")

    s3_path = f"s3://overturemaps-us-west-2/release/{release}/theme={theme}/type={otype}/*"

    con.execute(f"""
        COPY (
            SELECT *
            FROM read_parquet(
                '{s3_path}',
                filename=true, hive_partitioning=1
            )
            WHERE
                bbox.xmin BETWEEN {xmin} AND {xmax}
                AND bbox.ymin BETWEEN {ymin} AND {ymax}
        ) TO '{output_path}' (FORMAT PARQUET, ROW_GROUP_SIZE {row_group_size});
    """)

    print(f"Saved to {output_path}")
    con.close()
