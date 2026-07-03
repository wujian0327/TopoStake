#!/usr/bin/env python3
"""Small dependency-free SVG plotting helpers for paper figures."""

from __future__ import annotations

import csv
import html
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "results" / "processed"
FIGURES = ROOT / "figures"
COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#4c4c4c"]


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def to_float(value: Any, default: float = math.nan) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def mean_ci(values: Iterable[float]) -> Tuple[float, float, int]:
    clean = [value for value in values if not math.isnan(value)]
    if not clean:
        return math.nan, 0.0, 0
    if len(clean) == 1:
        return clean[0], 0.0, 1
    return statistics.mean(clean), 1.96 * statistics.stdev(clean) / math.sqrt(len(clean)), len(clean)


def grouped_series(
    rows: List[Dict[str, str]],
    experiment: str,
    x_field: str,
    y_field: str,
    series_field: str = "protocol_label",
    filters: Dict[str, str] | None = None,
) -> Dict[str, List[Tuple[Any, float, float]]]:
    filters = filters or {}
    buckets: Dict[Tuple[str, Any], List[float]] = defaultdict(list)
    for row in rows:
        if row.get("experiment") != experiment or row.get("status") != "ok":
            continue
        if any(str(row.get(key, "")) != str(value) for key, value in filters.items()):
            continue
        x = row.get(x_field, "")
        series = row.get(series_field, "")
        buckets[(series, x)].append(to_float(row.get(y_field)))

    out: Dict[str, List[Tuple[Any, float, float]]] = defaultdict(list)
    for (series, x), values in buckets.items():
        avg, ci, n = mean_ci(values)
        if n:
            out[series].append((coerce_x(x), avg, ci))
    for points in out.values():
        points.sort(key=lambda item: item[0])
    return dict(out)


def coerce_x(value: Any) -> Any:
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def no_data_svg(path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="760" height="420" viewBox="0 0 760 420">
  <rect width="760" height="420" fill="white"/>
  <text x="380" y="210" text-anchor="middle" font-family="Arial" font-size="15" fill="#666">No raw data available</text>
</svg>
"""
    )


def write_line_svg(
    path: Path,
    title: str,
    xlabel: str,
    ylabel: str,
    series: Dict[str, List[Tuple[Any, float, float]]],
    include_zero: bool = True,
) -> None:
    series = {name: pts for name, pts in series.items() if pts}
    if not series:
        no_data_svg(path, title)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 820, 500
    left, right, top, bottom = 82, 32, 58, 76
    plot_w = width - left - right
    plot_h = height - top - bottom
    all_x = [point[0] for points in series.values() for point in points]
    all_y = [point[1] for points in series.values() for point in points]
    all_ci = [point[2] for points in series.values() for point in points]

    numeric_x = all(isinstance(x, (int, float)) for x in all_x)
    if numeric_x:
        x_min, x_max = min(all_x), max(all_x)
        if x_min == x_max:
            x_min -= 1
            x_max += 1
        x_labels = sorted(set(all_x))

        def x_pos(x: Any) -> float:
            return left + (float(x) - x_min) / (x_max - x_min) * plot_w

        def x_label(x: Any) -> str:
            return f"{x:g}"

    else:
        labels = sorted({str(x) for x in all_x})
        index = {label: idx for idx, label in enumerate(labels)}

        def x_pos(x: Any) -> float:
            denom = max(1, len(labels) - 1)
            return left + index[str(x)] / denom * plot_w

        def x_label(x: Any) -> str:
            return str(x)

        x_labels = labels

    y_min = min(y - ci for y, ci in zip(all_y, all_ci))
    y_max = max(y + ci for y, ci in zip(all_y, all_ci))
    if include_zero:
        y_min = min(0.0, y_min)
        y_max = max(0.0, y_max)
    if y_min == y_max:
        y_min -= 1.0
        y_max += 1.0
    margin = (y_max - y_min) * 0.08
    y_min -= margin
    y_max += margin

    def y_pos(y: float) -> float:
        return top + (y_max - y) / (y_max - y_min) * plot_h

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="#222"/>',
        f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#222"/>',
    ]

    for i in range(5):
        value = y_min + (y_max - y_min) * i / 4
        y = y_pos(value)
        lines.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left+plot_w}" y2="{y:.2f}" stroke="#e8e8e8"/>')
        lines.append(
            f'<text x="{left-10}" y="{y+4:.2f}" text-anchor="end" font-family="Arial" font-size="11">{value:.3g}</text>'
        )

    for x in x_labels:
        xp = x_pos(x)
        lines.append(f'<line x1="{xp:.2f}" y1="{top+plot_h}" x2="{xp:.2f}" y2="{top+plot_h+5}" stroke="#222"/>')
        lines.append(
            f'<text x="{xp:.2f}" y="{top+plot_h+22}" text-anchor="middle" font-family="Arial" font-size="11">{html.escape(x_label(x))}</text>'
        )

    for idx, (name, points) in enumerate(sorted(series.items())):
        color = COLORS[idx % len(COLORS)]
        path_points = " ".join(f"{x_pos(x):.2f},{y_pos(y):.2f}" for x, y, _ in points)
        lines.append(f'<polyline points="{path_points}" fill="none" stroke="{color}" stroke-width="2.2"/>')
        for x, y, ci in points:
            xp, yp = x_pos(x), y_pos(y)
            y_hi, y_lo = y_pos(y + ci), y_pos(y - ci)
            lines.append(f'<line x1="{xp:.2f}" y1="{y_hi:.2f}" x2="{xp:.2f}" y2="{y_lo:.2f}" stroke="{color}"/>')
            lines.append(f'<circle cx="{xp:.2f}" cy="{yp:.2f}" r="4" fill="{color}"/>')
        legend_y = top + 20 + idx * 20
        lines.append(f'<rect x="{left+plot_w-130}" y="{legend_y-10}" width="12" height="12" fill="{color}"/>')
        lines.append(
            f'<text x="{left+plot_w-112}" y="{legend_y}" font-family="Arial" font-size="12">{html.escape(name)}</text>'
        )

    lines.append(
        f'<text x="{left+plot_w/2}" y="{height-22}" text-anchor="middle" font-family="Arial" font-size="14">{html.escape(xlabel)}</text>'
    )
    lines.append(
        f'<text transform="translate(22 {top+plot_h/2}) rotate(-90)" text-anchor="middle" font-family="Arial" font-size="14">{html.escape(ylabel)}</text>'
    )
    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n")


def criterion_estimates() -> Dict[str, float]:
    estimates: Dict[str, float] = {}
    for path in (ROOT / "target" / "criterion").glob("**/estimates.json"):
        try:
            data = json.loads(path.read_text())
            mean = data.get("mean", {}).get("point_estimate")
            if mean is None:
                continue
            label = str(path.parent.relative_to(ROOT / "target" / "criterion"))
            estimates[label] = float(mean) / 1_000_000.0
        except (OSError, ValueError):
            continue
    return estimates
