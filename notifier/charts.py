"""Render compact PNG charts for inline use in daily-report email."""

from __future__ import annotations

import math
import re
import struct
import zlib
from datetime import date


COLORS = ("#4F6BED", "#8B5CF6", "#14B8A6")
LABELS = ("代码提交", "任务更新", "飞书讨论")


class _Canvas:
    def __init__(self, width: int, height: int, background: str = "#FFFFFF") -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(_rgb(background) * (width * height))

    def pixel(self, x: int, y: int, color: str) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = (y * self.width + x) * 3
            self.pixels[offset:offset + 3] = bytes(_rgb(color))

    def line(self, x0: int, y0: int, x1: int, y1: int, color: str, width: int = 1) -> None:
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        error = dx - dy
        radius = max(0, width // 2)
        while True:
            for oy in range(-radius, radius + 1):
                for ox in range(-radius, radius + 1):
                    self.pixel(x0 + ox, y0 + oy, color)
            if x0 == x1 and y0 == y1:
                break
            twice = 2 * error
            if twice > -dy:
                error -= dy
                x0 += sx
            if twice < dx:
                error += dx
                y0 += sy

    def ring(self, center_x: int, center_y: int, outer: int, inner: int, values: list[int]) -> None:
        total = sum(values)
        if not total:
            self._ring_sector(center_x, center_y, outer, inner, 0, 360, "#E8EDF5")
            return
        start = 0.0
        for value, color in zip(values, COLORS):
            if value:
                end = start + value * 360.0 / total
                self._ring_sector(center_x, center_y, outer, inner, start, end, color)
                start = end

    def _ring_sector(self, cx: int, cy: int, outer: int, inner: int, start: float, end: float, color: str) -> None:
        for y in range(max(0, cy - outer), min(self.height, cy + outer + 1)):
            for x in range(max(0, cx - outer), min(self.width, cx + outer + 1)):
                dx, dy = x - cx, y - cy
                if inner * inner <= dx * dx + dy * dy <= outer * outer:
                    angle = (math.degrees(math.atan2(dy, dx)) + 90.0) % 360.0
                    if (angle - start) % 360.0 < (end - start) % 360.0 or end - start >= 360.0:
                        self.pixel(x, y, color)

    def png(self) -> bytes:
        raw = b"".join(b"\x00" + bytes(self.pixels[y * self.width * 3:(y + 1) * self.width * 3]) for y in range(self.height))
        return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)) + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b"")


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))


def render_email_charts(analytics: dict, report_html: str) -> tuple[dict[str, bytes], str]:
    """Return two PNGs and report HTML that references them by Content-ID."""
    today = analytics.get("today", {})
    week = list(analytics.get("week", []))[-7:]
    values = [max(0, int(today.get(key, 0) or 0)) for key in ("commits", "tasks", "messages")]
    charts = {"daily-activity": _donut(values), "weekly-intensity": _line_chart(week)}
    section = _html_section(values, week)
    # Put the overview and summary before the charts, so readers see today's
    # key numbers before the visual breakdown.
    html, count = re.subn(
        r"(<div\b[^>]*class=[\"'][^\"']*\bsummary-box\b[^\"']*[\"'][^>]*>.*?</div>)",
        lambda match: match.group(1) + section,
        report_html,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not count:
        html, count = re.subn(r"(<h1\b[^>]*>.*?</h1>)", lambda match: match.group(1) + section, report_html, count=1, flags=re.IGNORECASE | re.DOTALL)
        if not count:
            html = section + report_html
    return charts, html


def _donut(values: list[int]) -> bytes:
    canvas = _Canvas(560, 300)
    canvas.ring(156, 166, 112, 57, values)
    return canvas.png()


def _line_chart(week: list[dict]) -> bytes:
    canvas = _Canvas(720, 340)
    rows = week or [{"date": "", "commits": 0, "tasks": 0, "messages": 0}]
    left, top, width, height = 54, 38, 638, 250
    bottom = top + height
    max_value = max(1, *(int(row.get(key, 0) or 0) for row in rows for key in ("commits", "tasks", "messages")))
    for tick in range(5):
        y = top + height * tick // 4
        canvas.line(left, y, left + width, y, "#E8EDF5")
    canvas.line(left, top, left, bottom, "#94A3B8")
    canvas.line(left, bottom, left + width, bottom, "#94A3B8")
    denominator = max(1, len(rows) - 1)
    for key, color in zip(("commits", "tasks", "messages"), COLORS):
        points = []
        for index, row in enumerate(rows):
            x = left + width * index // denominator
            value = max(0, int(row.get(key, 0) or 0))
            y = bottom - height * value // max_value
            points.append((x, y))
        for first, second in zip(points, points[1:]):
            canvas.line(first[0], first[1], second[0], second[1], color, width=4)
        for x, y in points:
            for oy in range(-4, 5):
                for ox in range(-4, 5):
                    if ox * ox + oy * oy <= 16:
                        canvas.pixel(x + ox, y + oy, color)
    return canvas.png()


def _html_section(values: list[int], week: list[dict]) -> str:
    legends = "".join(
        f'<span style="display:inline-block;margin:0 16px 8px 0;color:#334155;">'
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{color};margin-right:6px;"></span>'
        f'{label}：{value}</span>'
        for label, value, color in zip(LABELS, values, COLORS)
    )
    dates = "".join(
        f'<span style="display:block;flex:1;text-align:center;white-space:nowrap;color:#64748b;'
        f'text-decoration:none;">{str(row.get("date", ""))[-5:].replace("-", "/")}</span>'
        for row in week
    )
    weekday_names = "一二三四五六日"
    if week:
        start = date.fromisoformat(str(week[0].get("date", "")))
        end = date.fromisoformat(str(week[-1].get("date", "")))
        week_range = (
            f"（{start.month}/{start.day} 周{weekday_names[start.weekday()]}—"
            f"{end.month}/{end.day} 周{weekday_names[end.weekday()]}）"
        )
    else:
        week_range = ""
    return (
        '<section style="margin:20px 0 28px;padding:0;background:transparent;border:0;">'
        '<h3 style="color:#57606a;margin:24px 0 6px;font-size:16px;font-weight:600;'
        'padding-bottom:6px;border-bottom:1px solid #d0d7de;">📈 工作数据图表</h3>'
        '<h3 style="margin:14px 0 6px;color:#475569;font-size:15px;">今日工作内容分布</h3>'
        '<img src="cid:daily-activity" alt="今日工作内容环状图" width="560" '
        'style="display:block;max-width:100%;height:auto;border:0;">'
        f'<div style="margin:8px 0 18px;">{legends}</div>'
        f'<h3 style="margin:14px 0 6px;color:#475569;font-size:15px;">近七日工作强度{week_range}</h3>'
        '<div style="color:#64748b;font-size:13px;margin:0 0 6px;">蓝色：代码提交　紫色：任务更新　绿色：飞书讨论</div>'
        '<img src="cid:weekly-intensity" alt="近七日工作强度折线图" width="720" '
        'style="display:block;max-width:100%;height:auto;border:0;">'
        f'<div aria-label="日期：{"、".join(str(row.get("date", "")) for row in week)}" '
        f'style="display:flex;justify-content:space-between;gap:2px;margin:0 2% 8px 7%;font-size:11px;line-height:1.4;">{dates}</div>'
        '</section>'
    )
