"""
CSV / ZIP エクスポートヘルパー。

分析実行時に既に取得済みのデータ (result dict) を CSV 形式に整形して
ダウンロード可能にする。**追加の API call は行わない**ため Anthropic
トークンも Ahrefs units も消費ゼロ。

UTF-8 BOM 付きで出力し、Excel / Googleスプレッドシート両方で日本語が
文字化けせず開けるようにする。
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timezone
from typing import Iterable, Optional

import pandas as pd


# ─── 基本ユーティリティ ────────────────────────────────

def _to_csv_bytes(rows: Iterable[dict], columns: Optional[list[str]] = None) -> bytes:
    """list[dict] を CSV (UTF-8 BOM 付き) のバイト列に変換。

    columns で出力カラム順を固定する。指定なしなら入力 dict のキーをそのまま使う。
    """
    df = pd.DataFrame(list(rows))
    if columns is not None:
        # 存在しないカラムは空欄を入れて並びを保つ
        for c in columns:
            if c not in df.columns:
                df[c] = ""
        df = df[columns]
    buf = io.StringIO()
    df.to_csv(buf, index=False)  # StringIO 相手の encoding 引数は無効なので渡さない
    return ("﻿" + buf.getvalue()).encode("utf-8")  # ﻿ = UTF-8 BOM (Excel 文字化け対策)


def _slugify_domain(domain: str) -> str:
    """ファイル名安全なドメイン文字列に。ドットは保持して可読性確保。"""
    if not domain:
        return "site"
    d = domain.replace("https://", "").replace("http://", "").rstrip("/")
    # 安全でない文字を _ に
    d = re.sub(r"[^a-zA-Z0-9._-]+", "_", d)
    return d or "site"


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def make_filename(domain: str, dataset: str) -> str:
    """例: n-works.link_top_keywords_2026-04-30.csv"""
    return f"{_slugify_domain(domain)}_{dataset}_{_today_iso()}.csv"


# ─── 各データセットの整形関数 ───────────────────────────

def kpis_csv(metrics: dict) -> bytes:
    """Ahrefs サイト指標 KPI 4枚 + 補助情報。"""
    rows = [
        {"指標": "Domain Rating", "値": metrics.get("domain_rating", 0), "補足": "/100"},
        {"指標": "月間自然検索セッション", "値": metrics.get("monthly_organic_sessions", 0), "補足": "直近30日"},
        {"指標": "被リンク元ドメイン (全体)", "値": metrics.get("referring_domains_total", 0), "補足": "RD 全カウント"},
        {"指標": "被リンク元ドメイン (価値あり)", "値": metrics.get("referring_domains_quality", 0), "補足": "dofollow / 非スパム"},
        {"指標": "自然検索流入ページ数", "値": metrics.get("organic_pages_count_display") or metrics.get("organic_pages_count", 0), "補足": "Ahrefs 上位ページ"},
    ]
    return _to_csv_bytes(rows, ["指標", "値", "補足"])


def brand_radar_csv(brand_radar: dict) -> bytes:
    """AI露出 (合計 + 7プラットフォーム)。"""
    if not isinstance(brand_radar, dict):
        return _to_csv_bytes([], ["プラットフォーム", "引用回数", "ステータス"])
    platforms = brand_radar.get("platforms", {})
    rows = [{"プラットフォーム": "合計", "引用回数": brand_radar.get("total", 0), "ステータス": "ok"}]
    ordered_keys = [
        "google_ai_overviews", "google_ai_mode", "chatgpt",
        "gemini", "perplexity", "copilot", "grok",
    ]
    for key in ordered_keys:
        p = platforms.get(key, {})
        if isinstance(p, dict):
            rows.append({
                "プラットフォーム": p.get("label", key),
                "引用回数": p.get("responses", 0),
                "ステータス": p.get("status", ""),
            })
    return _to_csv_bytes(rows, ["プラットフォーム", "引用回数", "ステータス"])


def top_keywords_csv(top_keywords: list[dict]) -> bytes:
    """流入貢献KW (画面表示順)。"""
    rows = []
    for k in top_keywords or []:
        if not isinstance(k, dict):
            continue
        rows.append({
            "KW": k.get("keyword", ""),
            "月間検索ボリューム": k.get("volume", 0),
            "順位": k.get("position", 0),
            "獲得URL": k.get("url", ""),
        })
    return _to_csv_bytes(rows, ["KW", "月間検索ボリューム", "順位", "獲得URL"])


def top_pages_csv(top_pages: list[dict]) -> bytes:
    """流入URL (画面表示順)。"""
    rows = []
    for p in top_pages or []:
        if not isinstance(p, dict):
            continue
        rows.append({
            "URL": p.get("url", ""),
            "流入貢献KW": p.get("top_keyword", ""),
            "検索ボリューム": p.get("top_keyword_volume", 0),
            "推定セッション/月": p.get("estimated_sessions", 0),
        })
    return _to_csv_bytes(rows, ["URL", "流入貢献KW", "検索ボリューム", "推定セッション/月"])


def top_directories_csv(top_directories: list[dict]) -> bytes:
    """流入上位ディレクトリ。"""
    rows = []
    for d in top_directories or []:
        if not isinstance(d, dict):
            continue
        rows.append({
            "ディレクトリ": d.get("directory", ""),
            "ページ数": d.get("pages", 0),
            "月間流入": d.get("monthly_sessions", 0),
            "シェア(%)": d.get("share_pct", 0),
        })
    return _to_csv_bytes(rows, ["ディレクトリ", "ページ数", "月間流入", "シェア(%)"])


def url_meta_csv(url_meta: dict, target_url: str = "") -> bytes:
    """調査URLメタ情報。"""
    if not isinstance(url_meta, dict):
        url_meta = {}
    rows = [
        {"項目": "対象URL", "値": target_url},
        {"項目": "Title", "値": url_meta.get("title", "")},
        {"項目": "Meta-description", "値": url_meta.get("meta_description", "")},
        {"項目": "インデックス状態", "値": url_meta.get("index_status", "")},
        {"項目": "canonical", "値": url_meta.get("canonical", "")},
        {"項目": "構造化データ (種類)", "値": ", ".join(url_meta.get("structured_data", []) or [])},
    ]
    return _to_csv_bytes(rows, ["項目", "値"])


def axis_scores_csv(summary: dict) -> bytes:
    """5軸スコア(サマリー)。"""
    if not isinstance(summary, dict):
        summary = {}
    axes = summary.get("axes", []) or []
    rows = []
    for a in axes:
        if not isinstance(a, dict):
            continue
        rows.append({
            "軸key": a.get("key", ""),
            "軸名": a.get("name", ""),
            "スコア": a.get("score", 0),
            "満点": 20,
            "課題件数": a.get("issues", 0),
            "総チェック項目数": a.get("total", 0),
        })
    rows.append({
        "軸key": "TOTAL",
        "軸名": "総合スコア",
        "スコア": summary.get("total_score", 0),
        "満点": 100,
        "課題件数": "",
        "総チェック項目数": "",
    })
    return _to_csv_bytes(rows, ["軸key", "軸名", "スコア", "満点", "課題件数", "総チェック項目数"])


def axis_issues_csv(axis_data: dict, axis_name: str = "") -> bytes:
    """1軸の指摘事項 (issues)。"""
    if not isinstance(axis_data, dict):
        axis_data = {}
    rows = []
    for it in axis_data.get("issues", []) or []:
        if not isinstance(it, dict):
            rows.append({"軸": axis_name, "観点": str(it), "観点補足": "", "施策": "", "エビデンス": "", "確認URL": "", "優先度": ""})
            continue
        ev_parts = []
        for e in it.get("evidence", []) or []:
            if isinstance(e, dict):
                ev_parts.append(f"{e.get('label','')}: {e.get('url','')}")
            else:
                ev_parts.append(str(e))
        rows.append({
            "軸": axis_name,
            "観点": it.get("observation", ""),
            "観点補足": it.get("observation_sub", ""),
            "施策": it.get("action", ""),
            "エビデンス": " | ".join(ev_parts),
            "確認URL": it.get("check_url", ""),
            "優先度": it.get("priority", ""),
        })
    return _to_csv_bytes(rows, ["軸", "観点", "観点補足", "施策", "エビデンス", "確認URL", "優先度"])


def axis_passed_csv(axis_data: dict, axis_name: str = "") -> bytes:
    """1軸の通過項目 (passed)。"""
    if not isinstance(axis_data, dict):
        axis_data = {}
    rows = []
    for p in axis_data.get("passed", []) or []:
        if not isinstance(p, dict):
            rows.append({"軸": axis_name, "項目名": str(p), "URL": ""})
            continue
        rows.append({"軸": axis_name, "項目名": p.get("name", ""), "URL": p.get("url", "")})
    return _to_csv_bytes(rows, ["軸", "項目名", "URL"])


def axis_unverifiable_csv(axis_data: dict, axis_name: str = "") -> bytes:
    """1軸の確認不可 (unverifiable)。"""
    if not isinstance(axis_data, dict):
        axis_data = {}
    rows = []
    for u in axis_data.get("unverifiable", []) or []:
        if not isinstance(u, dict):
            rows.append({"軸": axis_name, "項目名": str(u), "理由": "", "URL": ""})
            continue
        rows.append({
            "軸": axis_name,
            "項目名": u.get("name", ""),
            "理由": u.get("reason", ""),
            "URL": u.get("url", ""),
        })
    return _to_csv_bytes(rows, ["軸", "項目名", "理由", "URL"])


def all_axes_combined_csv(axes: dict, score_axes: list[dict]) -> bytes:
    """全5軸の issues / passed / unverifiable を1ファイルにまとめる(課題サマリ全体)。"""
    if not isinstance(axes, dict):
        axes = {}
    name_map = {a.get("key"): a.get("name", "") for a in (score_axes or []) if isinstance(a, dict)}
    rows = []
    for axis_key, axis_data in axes.items():
        if not isinstance(axis_data, dict):
            continue
        axis_name = name_map.get(axis_key, axis_key)
        for it in axis_data.get("issues", []) or []:
            if not isinstance(it, dict):
                continue
            ev_parts = [
                f"{e.get('label','')}: {e.get('url','')}"
                for e in (it.get("evidence", []) or [])
                if isinstance(e, dict)
            ]
            rows.append({
                "軸": axis_name,
                "分類": "issues (指摘事項)",
                "観点/項目名": f"{it.get('observation', '')}{(' (' + it.get('observation_sub', '') + ')') if it.get('observation_sub') else ''}",
                "詳細": it.get("action", ""),
                "URL": it.get("check_url", ""),
                "優先度/理由": it.get("priority", ""),
                "エビデンス": " | ".join(ev_parts),
            })
        for p in axis_data.get("passed", []) or []:
            if not isinstance(p, dict):
                continue
            rows.append({
                "軸": axis_name,
                "分類": "passed (通過)",
                "観点/項目名": p.get("name", ""),
                "詳細": "",
                "URL": p.get("url", ""),
                "優先度/理由": "",
                "エビデンス": "",
            })
        for u in axis_data.get("unverifiable", []) or []:
            if not isinstance(u, dict):
                continue
            rows.append({
                "軸": axis_name,
                "分類": "unverifiable (確認不可)",
                "観点/項目名": u.get("name", ""),
                "詳細": "",
                "URL": u.get("url", ""),
                "優先度/理由": u.get("reason", ""),
                "エビデンス": "",
            })
    return _to_csv_bytes(rows, ["軸", "分類", "観点/項目名", "詳細", "URL", "優先度/理由", "エビデンス"])


def contradictions_csv(contradictions: list) -> bytes:
    rows = []
    for c in contradictions or []:
        if not isinstance(c, dict):
            rows.append({"Googleの公式メッセージ": str(c), "内部実装の事実": "", "裏付けラベル": "", "裏付けURL": ""})
            continue
        rows.append({
            "Googleの公式メッセージ": c.get("public", ""),
            "内部実装の事実": c.get("internal", ""),
            "裏付けラベル": c.get("source_label", ""),
            "裏付けURL": c.get("source_url", ""),
        })
    return _to_csv_bytes(rows, ["Googleの公式メッセージ", "内部実装の事実", "裏付けラベル", "裏付けURL"])


def sources_csv(sources: list) -> bytes:
    rows = []
    for s in sources or []:
        if not isinstance(s, dict):
            rows.append({"出典": str(s), "URL": "", "ラベル": ""})
            continue
        rows.append({
            "出典": s.get("text", ""),
            "URL": s.get("url", ""),
            "ラベル": s.get("label", ""),
        })
    return _to_csv_bytes(rows, ["出典", "URL", "ラベル"])


def donts_csv(donts: list) -> bytes:
    rows = []
    for d in donts or []:
        if not isinstance(d, dict):
            rows.append({"施策名": str(d), "理由": "", "エビデンスラベル": "", "エビデンスURL": ""})
            continue
        rows.append({
            "施策名": d.get("name", ""),
            "理由": d.get("reason", ""),
            "エビデンスラベル": d.get("evidence_label", ""),
            "エビデンスURL": d.get("evidence_url", ""),
        })
    return _to_csv_bytes(rows, ["施策名", "理由", "エビデンスラベル", "エビデンスURL"])


# ─── 一括 ZIP バンドル ────────────────────────────────

def build_full_zip(data: dict) -> bytes:
    """分析結果 dict を全 CSV にして1つの ZIP にまとめる。

    `data` は analyze_site_structured() の戻り値構造を想定。
    """
    domain = (data.get("ahrefs", {}) or {}).get("domain", "") or ""
    target_url = data.get("target_url", "") or ""
    metrics = (data.get("ahrefs", {}) or {}).get("metrics", {}) or {}
    brand_radar = (data.get("ahrefs", {}) or {}).get("brand_radar", {}) or {}
    top_keywords = (data.get("ahrefs", {}) or {}).get("top_keywords", []) or []
    top_pages = (data.get("ahrefs", {}) or {}).get("top_pages", []) or []
    top_directories = (data.get("ahrefs", {}) or {}).get("top_directories", []) or []
    url_meta = data.get("url_meta", {}) or {}
    summary = data.get("summary", {}) or {}
    axes = data.get("axes", {}) or {}
    contradictions = data.get("contradictions", []) or []
    sources = data.get("sources", []) or []
    donts = data.get("donts", []) or []

    files: dict[str, bytes] = {
        make_filename(domain, "kpi"): kpis_csv(metrics),
        make_filename(domain, "ai_exposure"): brand_radar_csv(brand_radar),
        make_filename(domain, "top_keywords"): top_keywords_csv(top_keywords),
        make_filename(domain, "top_pages"): top_pages_csv(top_pages),
        make_filename(domain, "top_directories"): top_directories_csv(top_directories),
        make_filename(domain, "url_meta"): url_meta_csv(url_meta, target_url),
        make_filename(domain, "axis_scores"): axis_scores_csv(summary),
        make_filename(domain, "axes_combined"): all_axes_combined_csv(axes, summary.get("axes", []) if isinstance(summary, dict) else []),
        make_filename(domain, "contradictions"): contradictions_csv(contradictions),
        make_filename(domain, "sources"): sources_csv(sources),
        make_filename(domain, "donts"): donts_csv(donts),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()
