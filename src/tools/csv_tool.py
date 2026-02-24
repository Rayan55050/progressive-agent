"""
CSV/Excel Analyst tool — load spreadsheet, query data, build charts.

Dependencies: pandas, matplotlib, openpyxl (for .xlsx).
All heavy work runs in asyncio.to_thread() to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "csv_output"

try:
    import pandas as pd

    PANDAS_OK = True
except ImportError:
    pd = None  # type: ignore[assignment]
    PANDAS_OK = False
    logger.warning("pandas not installed — CSV/Excel analyst disabled. pip install pandas openpyxl")

try:
    import matplotlib

    matplotlib.use("Agg")  # non-interactive backend (no GUI)
    import matplotlib.pyplot as plt

    MATPLOTLIB_OK = True
except ImportError:
    plt = None  # type: ignore[assignment]
    MATPLOTLIB_OK = False
    logger.warning("matplotlib not installed — chart generation disabled. pip install matplotlib")


class CSVAnalystTool:
    """Analyse CSV/Excel files: info, head, stats, query, chart."""

    def __init__(self, pending_sends: list[Path] | None = None) -> None:
        self._pending_sends = pending_sends
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="csv_analyst",
            description=(
                "Анализ CSV/Excel файлов. Загрузи файл → задавай вопросы, считай статистику, строй графики. "
                "Actions: 'info' — колонки, типы, размер; "
                "'head' — первые N строк; "
                "'stats' — описательная статистика (mean, median, min, max); "
                "'query' — фильтрация данных по pandas-выражению (df.query()); "
                "'chart' — построить график (bar, line, pie, scatter, hist). "
                "Поддерживает: .csv, .tsv, .xlsx, .xls. "
                "Использовуй коли питають: 'проаналізуй таблицю', 'покажи графік', "
                "'відкрий Excel', 'статистика по файлу', 'побудуй діаграму'."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'info', 'head', 'stats', 'query', 'chart'",
                    required=True,
                    enum=["info", "head", "stats", "query", "chart"],
                ),
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Path to CSV/Excel file",
                    required=True,
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description=(
                        "For 'query': pandas query expression (e.g. 'age > 30 and city == \"Kyiv\"'). "
                        "For 'chart': not used."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="columns",
                    type="string",
                    description="Comma-separated column names to include (optional, all by default)",
                    required=False,
                ),
                ToolParameter(
                    name="chart_type",
                    type="string",
                    description="Chart type for 'chart' action: 'bar', 'line', 'pie', 'scatter', 'hist'",
                    required=False,
                ),
                ToolParameter(
                    name="x",
                    type="string",
                    description="X-axis column for 'chart' action",
                    required=False,
                ),
                ToolParameter(
                    name="y",
                    type="string",
                    description="Y-axis column(s) for 'chart' action (comma-separated for multiple)",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Number of rows to show (default 20, max 100)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not PANDAS_OK:
            return ToolResult(success=False, error="pandas not installed. Run: pip install pandas openpyxl")

        action = kwargs.get("action", "info")
        file_path = kwargs.get("file_path", "")

        if not file_path:
            return ToolResult(success=False, error="file_path is required")

        path = Path(file_path)
        if not path.exists():
            return ToolResult(success=False, error=f"File not found: {file_path}")

        suffix = path.suffix.lower()
        if suffix not in (".csv", ".tsv", ".xlsx", ".xls"):
            return ToolResult(success=False, error=f"Unsupported format: {suffix}. Use .csv, .tsv, .xlsx, .xls")

        try:
            df = await asyncio.to_thread(self._load_file, path)
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to load file: {e}")

        try:
            if action == "info":
                return await asyncio.to_thread(self._info, df, path)
            elif action == "head":
                limit = min(int(kwargs.get("limit", 20)), 100)
                cols = self._parse_columns(kwargs.get("columns"))
                return await asyncio.to_thread(self._head, df, limit, cols)
            elif action == "stats":
                cols = self._parse_columns(kwargs.get("columns"))
                return await asyncio.to_thread(self._stats, df, cols)
            elif action == "query":
                query_expr = kwargs.get("query", "")
                if not query_expr:
                    return ToolResult(success=False, error="query expression is required for 'query' action")
                limit = min(int(kwargs.get("limit", 20)), 100)
                cols = self._parse_columns(kwargs.get("columns"))
                return await asyncio.to_thread(self._query, df, query_expr, limit, cols)
            elif action == "chart":
                return await self._chart(df, kwargs)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.exception("CSV analyst error")
            return ToolResult(success=False, error=f"Analysis error: {e}")

    @staticmethod
    def _load_file(path: Path) -> "pd.DataFrame":
        """Load CSV or Excel into a DataFrame."""
        suffix = path.suffix.lower()
        if suffix in (".xlsx", ".xls"):
            return pd.read_excel(path, engine="openpyxl" if suffix == ".xlsx" else None)
        elif suffix == ".tsv":
            return pd.read_csv(path, sep="\t")
        else:
            return pd.read_csv(path)

    @staticmethod
    def _parse_columns(cols_str: str | None) -> list[str] | None:
        """Parse comma-separated column names."""
        if not cols_str:
            return None
        return [c.strip() for c in cols_str.split(",") if c.strip()]

    @staticmethod
    def _info(df: "pd.DataFrame", path: Path) -> ToolResult:
        """File overview: shape, columns, types, memory."""
        buf = io.StringIO()
        df.info(buf=buf)
        info_str = buf.getvalue()

        lines = [
            f"File: {path.name}",
            f"Rows: {len(df):,}  |  Columns: {len(df.columns)}",
            f"Memory: {df.memory_usage(deep=True).sum() / 1024:.0f} KB",
            "",
            "Columns:",
        ]
        for col in df.columns:
            dtype = df[col].dtype
            nulls = df[col].isnull().sum()
            uniq = df[col].nunique()
            null_str = f", {nulls} null" if nulls > 0 else ""
            lines.append(f"  {col} ({dtype}) — {uniq} unique{null_str}")

        return ToolResult(success=True, data={
            "answer": "\n".join(lines),
            "rows": len(df),
            "columns": len(df.columns),
        })

    @staticmethod
    def _head(df: "pd.DataFrame", limit: int, cols: list[str] | None) -> ToolResult:
        """Show first N rows."""
        if cols:
            missing = [c for c in cols if c not in df.columns]
            if missing:
                return ToolResult(success=False, error=f"Unknown columns: {missing}")
            subset = df[cols].head(limit)
        else:
            subset = df.head(limit)

        table_str = subset.to_string(index=True, max_colwidth=60)
        return ToolResult(success=True, data={
            "answer": f"First {len(subset)} rows:\n\n{table_str}",
            "rows_shown": len(subset),
        })

    @staticmethod
    def _stats(df: "pd.DataFrame", cols: list[str] | None) -> ToolResult:
        """Descriptive statistics."""
        if cols:
            missing = [c for c in cols if c not in df.columns]
            if missing:
                return ToolResult(success=False, error=f"Unknown columns: {missing}")
            subset = df[cols]
        else:
            subset = df

        desc = subset.describe(include="all")
        table_str = desc.to_string(max_colwidth=50)

        return ToolResult(success=True, data={
            "answer": f"Statistics:\n\n{table_str}",
        })

    @staticmethod
    def _query(df: "pd.DataFrame", query_expr: str, limit: int, cols: list[str] | None) -> ToolResult:
        """Filter DataFrame with pandas query()."""
        try:
            result = df.query(query_expr)
        except Exception as e:
            return ToolResult(success=False, error=f"Invalid query '{query_expr}': {e}")

        if cols:
            missing = [c for c in cols if c not in result.columns]
            if missing:
                return ToolResult(success=False, error=f"Unknown columns: {missing}")
            result = result[cols]

        total = len(result)
        shown = result.head(limit)
        table_str = shown.to_string(index=True, max_colwidth=60)

        return ToolResult(success=True, data={
            "answer": f"Query: {query_expr}\nFound: {total:,} rows (showing {len(shown)}):\n\n{table_str}",
            "total": total,
            "shown": len(shown),
        })

    async def _chart(self, df: "pd.DataFrame", kwargs: dict) -> ToolResult:
        """Build a chart and save as PNG."""
        if not MATPLOTLIB_OK:
            return ToolResult(success=False, error="matplotlib not installed. Run: pip install matplotlib")

        chart_type = kwargs.get("chart_type", "bar")
        x_col = kwargs.get("x", "")
        y_col = kwargs.get("y", "")
        query_expr = kwargs.get("query", "")

        if not x_col and chart_type != "hist":
            return ToolResult(success=False, error="x (column name) is required for chart")

        # Apply filter if given
        if query_expr:
            try:
                df = df.query(query_expr)
            except Exception as e:
                return ToolResult(success=False, error=f"Invalid query for chart: {e}")

        # Validate columns
        if x_col and x_col not in df.columns:
            return ToolResult(success=False, error=f"Column '{x_col}' not found. Available: {list(df.columns)}")

        y_cols = [c.strip() for c in y_col.split(",") if c.strip()] if y_col else []
        for c in y_cols:
            if c not in df.columns:
                return ToolResult(success=False, error=f"Column '{c}' not found. Available: {list(df.columns)}")

        output_path = DATA_DIR / f"chart_{os.getpid()}_{id(df)}.png"

        try:
            await asyncio.to_thread(
                self._build_chart, df, chart_type, x_col, y_cols, output_path
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Chart error: {e}")

        if self._pending_sends is not None:
            self._pending_sends.append(output_path)

        return ToolResult(success=True, data={
            "answer": f"Chart saved: {output_path.name} ({chart_type}, x={x_col}, y={y_col or 'auto'})",
            "file_path": str(output_path),
        })

    @staticmethod
    def _build_chart(
        df: "pd.DataFrame",
        chart_type: str,
        x_col: str,
        y_cols: list[str],
        output_path: Path,
    ) -> None:
        """Build matplotlib chart (runs in thread)."""
        fig, ax = plt.subplots(figsize=(10, 6))

        if chart_type == "hist":
            col = x_col or (y_cols[0] if y_cols else df.select_dtypes("number").columns[0])
            df[col].hist(ax=ax, bins=30, edgecolor="black")
            ax.set_xlabel(col)
            ax.set_ylabel("Count")
            ax.set_title(f"Histogram: {col}")

        elif chart_type == "pie":
            data = df[x_col].value_counts().head(15)
            data.plot.pie(ax=ax, autopct="%1.1f%%")
            ax.set_title(f"Distribution: {x_col}")
            ax.set_ylabel("")

        elif chart_type == "scatter":
            if len(y_cols) < 1:
                raise ValueError("scatter requires both x and y columns")
            df.plot.scatter(x=x_col, y=y_cols[0], ax=ax, alpha=0.6)
            ax.set_title(f"{x_col} vs {y_cols[0]}")

        elif chart_type == "line":
            if y_cols:
                df.plot(x=x_col, y=y_cols, ax=ax)
            else:
                df.set_index(x_col).plot(ax=ax)
            ax.set_title(f"Line chart: {x_col}")

        else:  # bar (default)
            if y_cols:
                df_plot = df[[x_col] + y_cols].head(30)
                df_plot.plot.bar(x=x_col, y=y_cols, ax=ax)
            else:
                data = df[x_col].value_counts().head(20)
                data.plot.bar(ax=ax)
            ax.set_title(f"Bar chart: {x_col}")

        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()
        fig.savefig(str(output_path), dpi=120, bbox_inches="tight")
        plt.close(fig)
