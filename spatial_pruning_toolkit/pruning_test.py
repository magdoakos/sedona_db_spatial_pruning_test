"""Benchmark spatial row group pruning with SedonaDB.

Requires ``sedona-db`` to be installed (optional dependency).
"""

import time
import re
import pyarrow.parquet as pq
from pathlib import Path
from shapely import wkt, box


class SpatialPruningTest:
    """Run spatial ST_Intersects queries against one or more Parquet files
    and report which row groups were pruned via GeospatialStatistics.

    Args:
        parquet_files: List of ``(path, label)`` tuples identifying files
            to benchmark.
        query_wkt: WKT polygon string for the spatial filter region.
        srid: Spatial reference ID (default 4326).

    Example::

        test = SpatialPruningTest(
            parquet_files=[
                ("data/unsorted.parquet", "Unsorted"),
                ("data/hilbert_geostats.parquet", "Hilbert + GeoStats"),
            ],
            query_wkt="POLYGON ((3.6 51.49, 3.64 51.49, 3.64 51.51, 3.6 51.51, 3.6 51.49))",
        )
        results = test.run()
    """

    def __init__(
        self,
        parquet_files: list[tuple[str | Path, str]],
        query_wkt: str,
        srid: int = 4326,
    ):
        self.parquet_files = [(str(p), label) for p, label in parquet_files]
        self.query_wkt = query_wkt
        self.srid = srid

        try:
            import sedona.db
        except ImportError as e:
            raise ImportError(
                "sedona-db is required for SpatialPruningTest. "
                "Install it with: pip install sedona-db"
            ) from e
        self._sd = sedona.db.connect()

    def _build_query_df(self, parquet_path: str):
        pois = self._sd.read_parquet(parquet_path)
        pois.to_view("test_data", overwrite=True)
        query = f"""
            SELECT * FROM test_data
            WHERE ST_Intersects(
                geometry,
                ST_SetSRID(
                    ST_GeomFromText('{self.query_wkt}'),
                    {self.srid}
                )
            )
        """
        return self._sd.sql(query)

    @staticmethod
    def _parse_explain_metrics(plan_text: str) -> dict:
        metrics = {}

        m = re.search(r'row_groups_pruned_statistics=(\d+) total', plan_text)
        metrics['rg_total'] = int(m.group(1)) if m else 0

        m = re.search(r'row_groups_spatial_pruned=(\d+) total .+ (\d+) matched', plan_text)
        if m:
            metrics['rg_spatial_total'] = int(m.group(1))
            metrics['rg_spatial_matched'] = int(m.group(2))
        else:
            metrics['rg_spatial_total'] = 0
            metrics['rg_spatial_matched'] = 0

        m = re.search(r'DataSourceExec:.*?output_rows=(\d+)', plan_text, re.DOTALL)
        metrics['rows_scanned'] = int(m.group(1)) if m else 0

        m = re.search(r'bytes_scanned=(\d+)', plan_text)
        metrics['bytes_scanned'] = int(m.group(1)) if m else 0

        m = re.search(r'FilterExec:.*?elapsed_compute=([\d.]+)(µs|ms|s)', plan_text)
        if m:
            val = float(m.group(1))
            unit = m.group(2)
            if unit == 'µs':
                metrics['filter_compute_ms'] = val / 1000
            elif unit == 'ms':
                metrics['filter_compute_ms'] = val
            else:
                metrics['filter_compute_ms'] = val * 1000
        else:
            metrics['filter_compute_ms'] = 0

        return metrics

    def _get_scanned_row_groups(self, parquet_path: str) -> tuple[list[int], list[int]]:
        """Return (scanned, skipped) row group indices based on geo stats bbox."""
        pf = pq.ParquetFile(parquet_path)
        md = pf.metadata
        query_geom = wkt.loads(self.query_wkt)
        geom_idx = pf.schema_arrow.get_field_index("geometry")

        scanned, skipped = [], []
        has_geo_stats = False

        for rg_idx in range(md.num_row_groups):
            col = md.row_group(rg_idx).column(geom_idx)
            if col.is_geo_stats_set:
                has_geo_stats = True
                gs = col.geo_statistics.to_dict()
                rg_bbox = box(gs['xmin'], gs['ymin'], gs['xmax'], gs['ymax'])
                if rg_bbox.intersects(query_geom):
                    scanned.append(rg_idx)
                else:
                    skipped.append(rg_idx)
            else:
                scanned.append(rg_idx)

        if not has_geo_stats:
            scanned = list(range(md.num_row_groups))
            skipped = []

        return scanned, skipped

    def _run_single(self, parquet_path: str, label: str) -> dict:
        print("=" * 70)
        print(f"  {label}")
        print("=" * 70)
        print(f"  File:      {parquet_path}")
        print(f"  Query WKT: {self.query_wkt}")
        print(f"  SRID:      {self.srid}")
        print()

        total = self._sd.read_parquet(parquet_path).count()
        file_rg_count = pq.ParquetFile(parquet_path).metadata.num_row_groups
        print(f"  Total rows in file: {total}")
        print(f"  Row groups in file: {file_rg_count}")

        df = self._build_query_df(parquet_path)

        # Warm-up
        df.count()

        # Timed run
        start = time.perf_counter()
        matched = df.count()
        elapsed = time.perf_counter() - start

        print(f"  Matched rows:       {matched}")
        print(f"  Query time:         {elapsed * 1000:.2f} ms")
        print()

        # EXPLAIN ANALYZE
        print("-" * 70)
        print("  EXPLAIN ANALYZE")
        print("-" * 70)
        explain_table = df.explain(type="analyze").to_arrow_table()
        plan_text = ""
        for row_idx in range(explain_table.num_rows):
            plan_type = explain_table.column("plan_type")[row_idx].as_py()
            plan_row = explain_table.column("plan")[row_idx].as_py()
            plan_text += plan_row + "\n"
            print(f"\n  [{plan_type}]")
            for line in plan_row.split("\n"):
                print(f"    {line}")

        metrics = self._parse_explain_metrics(plan_text)

        # Standard plan
        print()
        print("-" * 70)
        print("  EXPLAIN (standard)")
        print("-" * 70)
        std_table = df.explain(type="standard").to_arrow_table()
        for row_idx in range(std_table.num_rows):
            plan_type = std_table.column("plan_type")[row_idx].as_py()
            plan_row = std_table.column("plan")[row_idx].as_py()
            print(f"\n  [{plan_type}]")
            for line in plan_row.split("\n"):
                print(f"    {line}")

        self._sd.drop_view("test_data")

        scanned_rgs, skipped_rgs = self._get_scanned_row_groups(parquet_path)

        print()
        return {
            "total_rows": total,
            "matched_rows": matched,
            "elapsed_ms": elapsed * 1000,
            "file_rg_count": file_rg_count,
            "scanned_rgs": scanned_rgs,
            "skipped_rgs": skipped_rgs,
            **metrics,
        }

    @staticmethod
    def _print_comparison_table(results: dict):
        labels = list(results.keys())
        if not labels:
            return

        rows = []
        rows.append(("Total rows", [f"{r['total_rows']:,}" for r in results.values()]))
        rows.append(("Total row groups", [f"{r['file_rg_count']:,}" for r in results.values()]))
        rows.append(("RG stats evaluated", [f"{r['rg_total']:,}" for r in results.values()]))

        sp_vals = []
        for r in results.values():
            total = r['rg_spatial_total']
            matched = r['rg_spatial_matched']
            if total == 0:
                sp_vals.append("none (0 \u2192 0)")
            else:
                skipped_pct = (total - matched) / total * 100
                sp_vals.append(f"{total} \u2192 {matched} ({skipped_pct:.0f}% skipped)")
        rows.append(("Spatial pruning", sp_vals))

        rs_vals = []
        for r in results.values():
            scanned = r['rows_scanned']
            total = r['total_rows']
            pct = scanned / total * 100 if total > 0 else 0
            rs_vals.append(f"{scanned:,} ({pct:.0f}%)")
        rows.append(("Rows scanned", rs_vals))

        rows.append(("Bytes scanned", [
            f"{r['bytes_scanned'] / (1024 * 1024):.0f} MB" for r in results.values()
        ]))
        rows.append(("Filter compute", [
            f"{r['filter_compute_ms']:.0f} ms" for r in results.values()
        ]))
        rows.append(("Query time", [
            f"{r['elapsed_ms']:.0f} ms" for r in results.values()
        ]))

        metric_width = max(len(name) for name, _ in rows)
        col_widths = [
            max(len(label), max(len(vals[i]) for _, vals in rows))
            for i, label in enumerate(labels)
        ]

        print()
        print("=" * 70)
        print("  HEAD-TO-HEAD COMPARISON")
        print("=" * 70)

        header = f"  {'Metric':<{metric_width}}"
        for label, w in zip(labels, col_widths):
            header += f"  | {label:>{w}}"
        print(header)
        print("  " + "-" * (len(header) - 2))

        for name, vals in rows:
            line = f"  {name:<{metric_width}}"
            for val, w in zip(vals, col_widths):
                line += f"  | {val:>{w}}"
            print(line)

        print()

    def run(self) -> dict:
        """Execute the pruning benchmark across all files and print results.

        Returns:
            Dict mapping each label to its result metrics.
        """
        results = {}
        for parquet_path, label in self.parquet_files:
            if not Path(parquet_path).exists():
                print(f"\n  SKIPPED: {parquet_path} (file not found)\n")
                continue
            results[label] = self._run_single(parquet_path, label)

        if results:
            print("=" * 70)
            print("  SUMMARY")
            print("=" * 70)
            for label, r in results.items():
                print(f"  {label}: {r['matched_rows']} matches in {r['elapsed_ms']:.2f} ms")
            if len(results) >= 2:
                times = {k: v["elapsed_ms"] for k, v in results.items()}
                fastest = min(times, key=times.get)
                slowest = max(times, key=times.get)
                speedup = times[slowest] / times[fastest] if times[fastest] > 0 else 0
                print(f"\n  Fastest: {fastest} ({times[fastest]:.2f} ms)")
                print(f"  Slowest: {slowest} ({times[slowest]:.2f} ms)")
                print(f"  Speedup: {speedup:.1f}x")

            self._print_comparison_table(results)

            # Row groups scanned per file
            print("=" * 70)
            print("  ROW GROUPS SCANNED PER FILE")
            print("=" * 70)
            for label, r in results.items():
                scanned = r['scanned_rgs']
                skipped = r['skipped_rgs']
                total = r['file_rg_count']
                print(f"\n  {label} ({len(scanned)}/{total} scanned)")
                print(f"    Scanned: {scanned}")
                print(f"    Skipped: {skipped}")
            print()

        return results
