"""生成层：将采集数据整理为结构化日报（Markdown / HTML）。"""

from generator.formatter import DailyReport, MemberReport, generate

__all__ = ["DailyReport", "MemberReport", "generate"]
