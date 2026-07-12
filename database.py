"""
分析ログ保存用のデータベース層。
Neon Postgres (DATABASE_URL) があればそれを使用、なければ SQLite フォールバック。
"""
from __future__ import annotations

import json
import os
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False

import sqlite3


import tempfile

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_PATH = os.getenv("SQLITE_PATH", os.path.join(tempfile.gettempdir(), "seo_logs.db"))


def _is_postgres() -> bool:
    return bool(DATABASE_URL) and HAS_PSYCOPG


def _sqlite_since_str(days: int) -> str:
    """SQLite の日付フィルタ用しきい値文字列。

    SQLite の CURRENT_TIMESTAMP は UTC の 'YYYY-MM-DD HH:MM:SS' 形式で保存される。
    ローカル時刻の isoformat() ('YYYY-MM-DDTHH:MM:SS') と文字列比較すると、
    日付部分が同じ日に区切り文字 (' ' < 'T') の比較で全行が除外されるため、
    同じタイムゾーン (UTC)・同じ書式に揃えて比較する。"""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _connect():
    if _is_postgres():
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """テーブル作成(初回のみ)。"""
    conn = _connect()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute("""
                CREATE TABLE IF NOT EXISTS analyses (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    mode VARCHAR(32) NOT NULL,
                    target_url TEXT,
                    url_match_mode VARCHAR(32),
                    query_text TEXT,
                    total_score INTEGER,
                    axis_scores JSONB,
                    full_result JSONB,
                    user_hash VARCHAR(16)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at DESC)")
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    mode TEXT NOT NULL,
                    target_url TEXT,
                    url_match_mode TEXT,
                    query_text TEXT,
                    total_score INTEGER,
                    axis_scores TEXT,
                    full_result TEXT,
                    user_hash TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at DESC)")
        conn.commit()
    finally:
        conn.close()


def save_analysis(
    mode: str,
    target_url: str | None,
    url_match_mode: str | None,
    query_text: str | None,
    total_score: int | None,
    axis_scores: dict | None,
    full_result: dict,
    user_identifier: str = "",
) -> int:
    """分析結果を保存。user_identifier はプライバシー保護のためハッシュ化。"""
    user_hash = hashlib.sha256(user_identifier.encode()).hexdigest()[:16] if user_identifier else ""
    axis_json = json.dumps(axis_scores or {}, ensure_ascii=False)
    full_json = json.dumps(full_result, ensure_ascii=False)

    conn = _connect()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute("""
                INSERT INTO analyses (mode, target_url, url_match_mode, query_text,
                                     total_score, axis_scores, full_result, user_hash)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                RETURNING id
            """, (mode, target_url, url_match_mode, query_text,
                  total_score, axis_json, full_json, user_hash))
            new_id = cur.fetchone()["id"]
        else:
            cur.execute("""
                INSERT INTO analyses (mode, target_url, url_match_mode, query_text,
                                     total_score, axis_scores, full_result, user_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (mode, target_url, url_match_mode, query_text,
                  total_score, axis_json, full_json, user_hash))
            new_id = cur.lastrowid
        conn.commit()
        return new_id
    finally:
        conn.close()


def list_analyses(
    days: int = 30,
    mode_filter: str | None = None,
    url_search: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """分析ログ一覧を取得。新しい順。"""
    since = datetime.now() - timedelta(days=days)
    conn = _connect()
    try:
        cur = conn.cursor()
        if _is_postgres():
            sql = "SELECT * FROM analyses WHERE created_at >= %s"
            params: list = [since]
            if mode_filter and mode_filter != "すべて":
                sql += " AND mode = %s"
                params.append(mode_filter)
            if url_search:
                sql += " AND (target_url ILIKE %s OR query_text ILIKE %s)"
                params.extend([f"%{url_search}%", f"%{url_search}%"])
            sql += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        else:
            sql = "SELECT * FROM analyses WHERE created_at >= ?"
            params = [_sqlite_since_str(days)]
            if mode_filter and mode_filter != "すべて":
                sql += " AND mode = ?"
                params.append(mode_filter)
            if url_search:
                sql += " AND (target_url LIKE ? OR query_text LIKE ?)"
                params.extend([f"%{url_search}%", f"%{url_search}%"])
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cur.execute(sql, params)
            rows = cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["axis_scores"] = json.loads(d["axis_scores"]) if d["axis_scores"] else {}
                d["full_result"] = json.loads(d["full_result"]) if d["full_result"] else {}
                result.append(d)
            return result
    finally:
        conn.close()


def get_analysis(analysis_id: int) -> dict | None:
    """ID指定で1件取得(詳細表示用)。"""
    conn = _connect()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute("SELECT * FROM analyses WHERE id = %s", (analysis_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        else:
            cur.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["axis_scores"] = json.loads(d["axis_scores"]) if d["axis_scores"] else {}
            d["full_result"] = json.loads(d["full_result"]) if d["full_result"] else {}
            return d
    finally:
        conn.close()


def get_summary_stats(days: int = 30) -> dict:
    """ダッシュボード上部のサマリ用の集計値。"""
    since = datetime.now() - timedelta(days=days)
    conn = _connect()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute("""
                SELECT COUNT(*) AS total,
                       COUNT(DISTINCT target_url) AS unique_urls,
                       AVG(total_score) AS avg_score
                FROM analyses
                WHERE created_at >= %s
            """, (since,))
            stats = dict(cur.fetchone())
            cur.execute("""
                SELECT mode, COUNT(*) AS cnt FROM analyses
                WHERE created_at >= %s
                GROUP BY mode ORDER BY cnt DESC LIMIT 1
            """, (since,))
            top = cur.fetchone()
        else:
            since_str = _sqlite_since_str(days)
            cur.execute("""
                SELECT COUNT(*) AS total,
                       COUNT(DISTINCT target_url) AS unique_urls,
                       AVG(total_score) AS avg_score
                FROM analyses
                WHERE created_at >= ?
            """, (since_str,))
            stats = dict(cur.fetchone())
            cur.execute("""
                SELECT mode, COUNT(*) AS cnt FROM analyses
                WHERE created_at >= ?
                GROUP BY mode ORDER BY cnt DESC LIMIT 1
            """, (since_str,))
            top = cur.fetchone()
        stats["top_mode"] = dict(top)["mode"] if top else "—"
        stats["avg_score"] = round(float(stats["avg_score"] or 0), 1)
        return stats
    finally:
        conn.close()
