"""SQLite 日报历史存储。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StoredReport:
    id: int
    report_date: date
    team_name: str
    markdown: str
    html: str
    generated_at: datetime


class ReportStorage:
    """用 sqlite3 封装日报的创建、写入与查询。"""

    def __init__(self, db_path: str | Path = "daily_reports.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_date TEXT NOT NULL,
                    team_name TEXT NOT NULL,
                    markdown TEXT NOT NULL,
                    html TEXT NOT NULL,
                    generated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_reports_date_team
                ON daily_reports (report_date, team_name)
                """
            )
            conn.commit()

    def save_report(
        self,
        report_date: date,
        team_name: str,
        markdown: str,
        html: str,
        generated_at: datetime | None = None,
    ) -> int:
        generated = generated_at or datetime.now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO daily_reports (report_date, team_name, markdown, html, generated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(report_date, team_name) DO UPDATE SET
                    markdown = excluded.markdown,
                    html = excluded.html,
                    generated_at = excluded.generated_at
                """,
                (
                    report_date.isoformat(),
                    team_name,
                    markdown,
                    html,
                    generated.isoformat(),
                ),
            )
            conn.commit()
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            row = conn.execute(
                """
                SELECT id FROM daily_reports
                WHERE report_date = ? AND team_name = ?
                """,
                (report_date.isoformat(), team_name),
            ).fetchone()
            return int(row["id"])

    def get_report(self, report_date: date, team_name: str | None = None) -> StoredReport | None:
        sql = "SELECT * FROM daily_reports WHERE report_date = ?"
        params: tuple[Any, ...] = (report_date.isoformat(),)
        if team_name is not None:
            sql += " AND team_name = ?"
            params = (report_date.isoformat(), team_name)
        sql += " ORDER BY id DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return self._row_to_report(row) if row else None

    def list_reports(self) -> list[StoredReport]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM daily_reports ORDER BY report_date DESC, id DESC"
            ).fetchall()
        return [self._row_to_report(row) for row in rows]

    @staticmethod
    def _row_to_report(row: sqlite3.Row) -> StoredReport:
        return StoredReport(
            id=int(row["id"]),
            report_date=date.fromisoformat(row["report_date"]),
            team_name=row["team_name"],
            markdown=row["markdown"],
            html=row["html"],
            generated_at=datetime.fromisoformat(row["generated_at"]),
        )
