from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
)


@dataclass(frozen=True)
class ColumnSummary:
    name: str
    parquet_type: str
    pandas_dtype: str
    null_count: int
    non_null_count: int
    unique_count: int
    minimum: str
    maximum: str
    samples: str


@dataclass(frozen=True)
class ParquetInspection:
    path: Path
    row_count: int
    column_count: int
    row_group_count: int
    created_by: str
    schema_metadata: dict[str, str]
    date_min: str | None
    date_max: str | None
    duplicate_date_count: int | None
    column_summaries: list[ColumnSummary]
    preview: pd.DataFrame
    full_data: pd.DataFrame


_PREFERRED_PREVIEW_COLUMNS = [
    "date",
    "news_sentiment_mean",
    "news_sentiment_std",
    "n_articles",
    "sentiment_status",
    "fng_value",
    "btc_log_return",
    "funding_rate",
    "full_hybrid_index",
    "core_hybrid_index",
    "is_outlier",
]


def _format_scalar(value: Any) -> str:
    if value is None or pd.isna(value):
        return "<NA>"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def _format_metadata(metadata: dict[bytes, bytes] | None) -> dict[str, str]:
    if not metadata:
        return {}

    formatted: dict[str, str] = {}
    for key_bytes, value_bytes in metadata.items():
        key = key_bytes.decode("utf-8", errors="replace")
        value = value_bytes.decode("utf-8", errors="replace")
        if key == "ARROW:schema":
            formatted[key] = f"<omitted binary schema: {len(value_bytes)} bytes>"
            continue
        if key == "pandas":
            pandas_metadata = json.loads(value)
            formatted[key] = json.dumps(pandas_metadata, ensure_ascii=True, sort_keys=True)
            continue
        formatted[key] = value
    return formatted


def _series_min_max(series: pd.Series) -> tuple[str, str]:
    non_null = series.dropna()
    if non_null.empty:
        return ("<NA>", "<NA>")
    if is_bool_dtype(series):
        values = sorted(bool(value) for value in non_null.tolist())
        return (_format_scalar(values[0]), _format_scalar(values[-1]))
    if is_numeric_dtype(series) or is_datetime64_any_dtype(series):
        return (_format_scalar(non_null.min()), _format_scalar(non_null.max()))

    text_values = sorted(_format_scalar(value) for value in non_null.tolist())
    return (text_values[0], text_values[-1])


def _series_samples(series: pd.Series, *, limit: int = 3) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return "<NA>"

    samples: list[str] = []
    for value in non_null.drop_duplicates().head(limit).tolist():
        samples.append(_format_scalar(value))
    return ", ".join(samples)


def _column_summary(df: pd.DataFrame, parquet_schema: pq.ParquetSchema) -> list[ColumnSummary]:
    summaries: list[ColumnSummary] = []
    for index, column in enumerate(df.columns):
        series = df[column]
        null_count = int(series.isna().sum())
        non_null_count = int(series.notna().sum())
        unique_count = int(series.nunique(dropna=True))
        minimum, maximum = _series_min_max(series)
        summaries.append(
            ColumnSummary(
                name=column,
                parquet_type=str(parquet_schema.column(index).physical_type),
                pandas_dtype=str(series.dtype),
                null_count=null_count,
                non_null_count=non_null_count,
                unique_count=unique_count,
                minimum=minimum,
                maximum=maximum,
                samples=_series_samples(series),
            )
        )
    return summaries


def inspect_parquet(path: Path) -> ParquetInspection:
    metadata = pq.read_metadata(path)
    table = pq.read_table(path)
    df = table.to_pandas()

    date_min: str | None = None
    date_max: str | None = None
    duplicate_date_count: int | None = None
    if "date" in df.columns:
        date_series = df["date"].dropna()
        if not date_series.empty:
            normalized = date_series.astype(str)
            date_min = normalized.min()
            date_max = normalized.max()
            duplicate_date_count = int(normalized.duplicated().sum())
        else:
            duplicate_date_count = 0

    preview = df if len(df) <= 20 else pd.concat([df.head(10), df.tail(10)], axis=0)

    return ParquetInspection(
        path=path,
        row_count=metadata.num_rows,
        column_count=len(df.columns),
        row_group_count=metadata.num_row_groups,
        created_by=metadata.created_by or "<unknown>",
        schema_metadata=_format_metadata(metadata.metadata),
        date_min=date_min,
        date_max=date_max,
        duplicate_date_count=duplicate_date_count,
        column_summaries=_column_summary(df, metadata.schema),
        preview=preview,
        full_data=df,
    )


def _render_column_summaries(summaries: list[ColumnSummary]) -> str:
    rendered = pd.DataFrame(
        [
            {
                "column": summary.name,
                "parquet_type": summary.parquet_type,
                "pandas_dtype": summary.pandas_dtype,
                "nulls": summary.null_count,
                "non_nulls": summary.non_null_count,
                "unique": summary.unique_count,
                "min": summary.minimum,
                "max": summary.maximum,
                "samples": summary.samples,
            }
            for summary in summaries
        ]
    )
    return rendered.to_string(index=False)


def _render_full_data(df: pd.DataFrame) -> str:
    if df.empty:
        return "<empty>"
    return df.to_string(index=False)


def _truncate(value: str, *, limit: int = 96) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _select_preview_columns(df: pd.DataFrame, *, limit: int = 10) -> list[str]:
    preferred = [column for column in _PREFERRED_PREVIEW_COLUMNS if column in df.columns]
    if len(preferred) >= limit:
        return preferred[:limit]

    remaining = [column for column in df.columns if column not in preferred]
    return (preferred + remaining)[:limit]


def _extract_stats_summary(metadata: dict[str, str]) -> dict[str, str]:
    raw = metadata.get("sentiment_join_stats")
    if not raw:
        return {}

    stats = json.loads(raw)
    hybrid_indices = stats.get("hybrid_indices") or {}
    summary: dict[str, str] = {
        "run_id": str(stats.get("run_id", "<missing>")),
        "granger_executed": str(stats.get("granger_executed", "<missing>")),
        "granger_result_count": str(len(stats.get("granger_results", []))),
        "outlier_filtered_count": str(stats.get("outlier_filtered_count", "<missing>")),
        "outlier_filtered_ratio": str(stats.get("outlier_filtered_ratio", "<missing>")),
    }
    for name in ("full", "core"):
        entry = hybrid_indices.get(name) if isinstance(hybrid_indices, dict) else None
        if not isinstance(entry, dict):
            continue
        pca = entry.get("pca_summary") or {}
        coverage = entry.get("coverage") or {}
        summary[f"{name}_signal_label"] = str(entry.get("signal_label", "<missing>"))
        summary[f"{name}_pca_status"] = str(pca.get("status", "<missing>"))
        summary[f"{name}_explained_variance"] = str(pca.get("explained_variance", "<missing>"))
        summary[f"{name}_coverage_ratio"] = str(coverage.get("ratio", "<missing>"))
    return summary


def _render_compare_section(inspections: list[ParquetInspection]) -> str:
    if len(inspections) < 2:
        return ""

    first, second = inspections[0], inspections[1]
    first_columns = set(first.full_data.columns)
    second_columns = set(second.full_data.columns)
    only_first = sorted(first_columns - second_columns)
    only_second = sorted(second_columns - first_columns)

    lines = [
        "=== FILE COMPARISON ===",
        f"left_file: {first.path.name}",
        f"right_file: {second.path.name}",
        f"left_only_columns: {only_first or '<none>'}",
        f"right_only_columns: {only_second or '<none>'}",
    ]

    if "date" in first.full_data.columns and "date" in second.full_data.columns:
        common_columns = sorted(first_columns & second_columns)
        merged = first.full_data.merge(
            second.full_data,
            on="date",
            how="outer",
            suffixes=("_left", "_right"),
            indicator=True,
        )
        lines.append(f"matched_dates: {int((merged['_merge'] == 'both').sum())}")
        lines.append(f"left_only_dates: {int((merged['_merge'] == 'left_only').sum())}")
        lines.append(f"right_only_dates: {int((merged['_merge'] == 'right_only').sum())}")

        value_diffs: list[dict[str, str]] = []
        matched = merged[merged["_merge"] == "both"]
        for _, row in matched.iterrows():
            for column in common_columns:
                if column == "date":
                    continue
                left_value = row[f"{column}_left"]
                right_value = row[f"{column}_right"]
                if pd.isna(left_value) and pd.isna(right_value):
                    continue
                if _format_scalar(left_value) != _format_scalar(right_value):
                    value_diffs.append(
                        {
                            "date": _format_scalar(row["date"]),
                            "column": column,
                            "left": _format_scalar(left_value),
                            "right": _format_scalar(right_value),
                        }
                    )

        lines.append("value_differences:")
        if value_diffs:
            lines.append(pd.DataFrame(value_diffs).to_string(index=False))
        else:
            lines.append("<none>")

    return "\n".join(lines)


def render_report(inspections: list[ParquetInspection]) -> str:
    sections: list[str] = []
    for inspection in inspections:
        sections.extend(
            [
                "=" * 80,
                f"FILE: {inspection.path}",
                f"rows={inspection.row_count} columns={inspection.column_count} "
                f"row_groups={inspection.row_group_count}",
                f"created_by={inspection.created_by}",
                f"date_range={inspection.date_min or '<missing>'} -> "
                f"{inspection.date_max or '<missing>'}",
                f"duplicate_dates={inspection.duplicate_date_count if inspection.duplicate_date_count is not None else '<no date column>'}",
                f"schema_metadata={json.dumps(inspection.schema_metadata, ensure_ascii=True, sort_keys=True)}",
                "",
                "[column_summary]",
                _render_column_summaries(inspection.column_summaries),
                "",
                "[full_data]" if len(inspection.full_data) <= 20 else "[preview_data]",
                _render_full_data(inspection.preview),
            ]
        )

    compare_section = _render_compare_section(inspections)
    if compare_section:
        sections.extend(["", compare_section])

    return "\n".join(sections) + "\n"


def _build_summary_table(inspection: ParquetInspection):
    from rich.table import Table

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold cyan", width=18)
    table.add_column()
    table.add_row("file", str(inspection.path))
    table.add_row("rows", str(inspection.row_count))
    table.add_row("columns", str(inspection.column_count))
    table.add_row("row_groups", str(inspection.row_group_count))
    table.add_row("created_by", inspection.created_by)
    table.add_row(
        "date_range",
        f"{inspection.date_min or '<missing>'} -> {inspection.date_max or '<missing>'}",
    )
    table.add_row(
        "duplicate_dates",
        (
            str(inspection.duplicate_date_count)
            if inspection.duplicate_date_count is not None
            else "<no date column>"
        ),
    )
    return table


def _build_key_metadata_table(inspection: ParquetInspection):
    from rich.table import Table

    stats_summary = _extract_stats_summary(inspection.schema_metadata)
    table = Table(title="Metadata", expand=True)
    table.add_column("Key", style="bold cyan", no_wrap=True)
    table.add_column("Value")

    keys = ["btc_source", "ffill_days"]
    for key in keys:
        if key in inspection.schema_metadata:
            table.add_row(key, _truncate(inspection.schema_metadata[key]))

    for key, value in stats_summary.items():
        table.add_row(key, _truncate(value))

    if table.row_count == 0:
        table.add_row("<none>", "<none>")
    return table


def _build_column_summary_table(summaries: list[ColumnSummary]):
    from rich.table import Table

    table = Table(title="Column Summary", expand=True)
    table.add_column("Column", style="bold")
    table.add_column("Parquet")
    table.add_column("Pandas")
    table.add_column("Nulls", justify="right")
    table.add_column("Unique", justify="right")
    table.add_column("Min")
    table.add_column("Max")

    for summary in summaries:
        table.add_row(
            summary.name,
            summary.parquet_type,
            summary.pandas_dtype,
            str(summary.null_count),
            str(summary.unique_count),
            _truncate(summary.minimum, limit=24),
            _truncate(summary.maximum, limit=24),
        )
    return table


def _build_preview_table(df: pd.DataFrame):
    from rich.table import Table

    if df.empty:
        table = Table(title="Preview")
        table.add_column("Value")
        table.add_row("<empty>")
        return table

    preview_columns = _select_preview_columns(df)
    table = Table(title="Preview", expand=True)
    for column in preview_columns:
        table.add_column(column, overflow="fold")

    for _, row in df[preview_columns].iterrows():
        table.add_row(
            *[_truncate(_format_scalar(row[column]), limit=32) for column in preview_columns]
        )
    return table


def _build_compare_table(inspections: list[ParquetInspection]):
    from rich.table import Table

    if len(inspections) < 2:
        return None

    first, second = inspections[0], inspections[1]
    table = Table(title="Comparison", expand=True)
    table.add_column("Metric", style="bold cyan")
    table.add_column(first.path.name)
    table.add_column(second.path.name)

    table.add_row("rows", str(first.row_count), str(second.row_count))
    table.add_row("columns", str(first.column_count), str(second.column_count))
    table.add_row(
        "date_range",
        f"{first.date_min or '<missing>'} -> {first.date_max or '<missing>'}",
        f"{second.date_min or '<missing>'} -> {second.date_max or '<missing>'}",
    )

    first_columns = set(first.full_data.columns)
    second_columns = set(second.full_data.columns)
    table.add_row(
        "left_only_columns",
        ", ".join(sorted(first_columns - second_columns)) or "<none>",
        "",
    )
    table.add_row(
        "right_only_columns",
        "",
        ", ".join(sorted(second_columns - first_columns)) or "<none>",
    )
    return table


def print_rich_report(inspections: list[ParquetInspection], console=None) -> None:
    from rich.console import Console, Group
    from rich.panel import Panel

    console = console or Console()
    renderables: list[object] = []
    for inspection in inspections:
        renderables.extend(
            [
                Panel(
                    _build_summary_table(inspection),
                    title=f"[bold green]{inspection.path.name}[/bold green]",
                    border_style="green",
                ),
                _build_key_metadata_table(inspection),
                _build_column_summary_table(inspection.column_summaries),
                _build_preview_table(inspection.preview),
            ]
        )

    compare_table = _build_compare_table(inspections)
    if compare_table is not None:
        renderables.append(compare_table)

    console.print(Group(*renderables))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect sentiment join parquet files with schema, stats, and comparison output."
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="rich 출력 대신 기존 텍스트 리포트를 사용합니다.",
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Parquet files to inspect")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    inspections = [inspect_parquet(path) for path in args.paths]
    if args.plain:
        print(render_report(inspections), end="")
        return 0

    try:
        print_rich_report(inspections)
    except ImportError:
        print(render_report(inspections), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "inspect_parquet",
    "main",
    "parse_args",
    "print_rich_report",
    "render_report",
]
