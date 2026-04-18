from __future__ import annotations

from pathlib import Path

import pandas as pd
from rich.console import Console

from morning_brief.analysis.sentiment_join.inspect import (
    inspect_parquet,
    main,
    print_rich_report,
    render_report,
)
from morning_brief.analysis.sentiment_join.storage import save_parquet


def test_inspect_parquet_reports_schema_and_date_range(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "date": ["2026-04-10", "2026-04-11"],
            "news_sentiment_mean": [0.1, 0.2],
            "n_articles": pd.array([3, None], dtype="Int64"),
            "is_outlier": [False, False],
        }
    )
    path = save_parquet(df, tmp_path, "20260411")

    inspection = inspect_parquet(path)

    assert inspection.row_count == 2
    assert inspection.column_count == 4
    assert inspection.date_min == "2026-04-10"
    assert inspection.date_max == "2026-04-11"
    assert inspection.duplicate_date_count == 0
    assert inspection.schema_metadata["ffill_days"] == "0"

    column_names = [summary.name for summary in inspection.column_summaries]
    assert column_names == ["date", "news_sentiment_mean", "n_articles", "is_outlier"]


def test_render_report_includes_column_and_value_differences(tmp_path: Path) -> None:
    first = pd.DataFrame(
        {
            "date": ["2026-04-10"],
            "news_sentiment_mean": [0.1],
            "n_articles": pd.array([3], dtype="Int64"),
        }
    )
    second = pd.DataFrame(
        {
            "date": ["2026-04-10"],
            "news_sentiment_mean": [0.2],
            "n_articles": pd.array([3], dtype="Int64"),
            "signal_sentiment_mean": [0.6],
        }
    )
    first_path = save_parquet(first, tmp_path, "20260410")
    second_path = save_parquet(second, tmp_path, "20260411")

    report = render_report([inspect_parquet(first_path), inspect_parquet(second_path)])

    assert "left_only_columns: <none>" in report
    assert "right_only_columns: ['signal_sentiment_mean']" in report
    assert "news_sentiment_mean" in report
    assert "0.1" in report
    assert "0.2" in report


def test_main_prints_report(tmp_path: Path, capsys) -> None:
    df = pd.DataFrame(
        {
            "date": ["2026-04-10"],
            "news_sentiment_mean": [0.1],
            "n_articles": pd.array([3], dtype="Int64"),
            "is_outlier": [False],
        }
    )
    path = save_parquet(df, tmp_path, "20260410")

    exit_code = main([str(path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Metadata" in captured.out
    assert path.name in captured.out


def test_print_rich_report_includes_filename_and_metadata(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "date": ["2026-04-10"],
            "news_sentiment_mean": [0.1],
            "n_articles": pd.array([3], dtype="Int64"),
            "is_outlier": [False],
        }
    )
    path = save_parquet(df, tmp_path, "20260410")
    inspection = inspect_parquet(path)

    console = Console(record=True, force_terminal=False, width=120)
    print_rich_report([inspection], console=console)

    output = console.export_text()
    assert path.name in output
    assert "Metadata" in output
    assert "Column Summary" in output
