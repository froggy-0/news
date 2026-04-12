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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect sentiment join parquet files with schema, stats, and comparison output."
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Parquet files to inspect")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    inspections = [inspect_parquet(path) for path in args.paths]
    print(render_report(inspections), end="")
    return 0


__all__ = ["inspect_parquet", "main", "parse_args", "render_report"]
