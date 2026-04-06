"""Inspect Parquet file metadata, row group statistics, and geospatial stats."""
from __future__ import annotations
import pyarrow.parquet as pq
from pathlib import Path


class ParquetAnalyzer:
    """Read-only inspector for Parquet file metadata and geospatial statistics.

    Args:
        path: Path to a Parquet file.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._pf = pq.ParquetFile(str(self.path))

    @property
    def metadata(self):
        return self._pf.metadata

    @property
    def schema(self):
        return self._pf.schema

    @property
    def arrow_schema(self):
        return self._pf.schema_arrow

    @property
    def num_row_groups(self) -> int:
        return self._pf.metadata.num_row_groups

    def print_metadata(self):
        """Print top-level Parquet file metadata."""
        print(self._pf.metadata)

    def print_schema(self):
        """Print the Parquet schema."""
        print(self._pf.schema)

    def print_kv_metadata(self):
        """Print Arrow key-value metadata (e.g. GeoParquet 'geo' key)."""
        print(self._pf.schema_arrow.metadata)

    def print_column_types(self):
        """Print Arrow and Parquet types for every column."""
        schema = self._pf.schema_arrow
        parquet_schema = self._pf.schema
        for i in range(len(schema)):
            field = schema.field(i)
            pcol = parquet_schema[i]
            print(
                f"  {field.name}: arrow_type={field.type}, "
                f"parquet_logical_type={pcol.logical_type}, "
                f"parquet_physical_type={pcol.physical_type}"
            )

    def print_row_group_metadata(self):
        """Print per-column statistics for every row group."""
        md = self._pf.metadata
        for rg_idx in range(md.num_row_groups):
            rg = md.row_group(rg_idx)
            print(f"\n--- Row Group {rg_idx} ({rg.num_rows} rows) ---")
            for col_idx in range(rg.num_columns):
                col = rg.column(col_idx)
                print(f"  Column: {col.path_in_schema}")
                print(f"    Encodings: {col.encodings}")
                print(f"    Compression: {col.compression}")
                print(f"    Total compressed size: {col.total_compressed_size}")
                if col.statistics and col.statistics.has_min_max:
                    print(f"    Min: {col.statistics.min}")
                    print(f"    Max: {col.statistics.max}")
                elif col.statistics:
                    print(f"    Stats: null_count={col.statistics.null_count}, num_values={col.statistics.num_values}")
                else:
                    print(f"    Stats: None")

    def print_geo_statistics(self, geometry_column: str = "geometry"):
        """Print Parquet 2.11 GeospatialStatistics (per-row-group bbox)
        for the given geometry column.

        Args:
            geometry_column: Name of the geometry column to inspect.
        """
        md = self._pf.metadata
        col_idx = self._pf.schema_arrow.get_field_index(geometry_column)

        has_any = False
        print(f"\nGeospatial Statistics for column '{geometry_column}':")
        for rg_idx in range(md.num_row_groups):
            col = md.row_group(rg_idx).column(col_idx)
            if col.is_geo_stats_set:
                has_any = True
                gs = col.geo_statistics.to_dict()
                print(
                    f"  RG {rg_idx}: bbox=["
                    f"{gs['xmin']:.6f}, {gs['ymin']:.6f}, "
                    f"{gs['xmax']:.6f}, {gs['ymax']:.6f}]"
                )
            else:
                print(f"  RG {rg_idx}: No GeospatialStatistics set")

        if not has_any:
            print("  (no GeospatialStatistics found in any row group)")

    def summary(self):
        """Print a concise overview of the file."""
        md = self._pf.metadata
        print(f"File: {self.path}")
        print(f"  Rows:       {md.num_rows:,}")
        print(f"  Row groups: {md.num_row_groups}")
        print(f"  Columns:    {md.num_columns}")
        print(f"  Format:     {md.format_version}")

        # Check for geo stats
        geom_idx = None
        for i in range(len(self._pf.schema_arrow)):
            if "geometry" in self._pf.schema_arrow.field(i).name.lower():
                geom_idx = i
                break
        if geom_idx is not None:
            col = md.row_group(0).column(geom_idx)
            print(f"  Geo stats:  {'yes' if col.is_geo_stats_set else 'no'}")
