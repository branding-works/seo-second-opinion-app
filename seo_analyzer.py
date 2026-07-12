"""
SEO セカンドオピニオン Anthropic API ラッパー。

Mode A (サイト分析) / Mode B (施策レビュー) / Mode C (個別質問) の3モードに対応。
APP_MODE=mock の場合は実APIを呼ばずダミーデータを返す。
"""

import os
import json
import re
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from urllib.parse import urlparse
import requests
from anthropic import Anthropic
from agent_system_prompt import SYSTEM_PROMPT
from ahrefs_client import (
    get_site_metrics,
    get_top_keywords,
    get_top_pages,
    get_top_directories,
    get_brand_radar_citations,
    get_last_raw_responses,
    resolve_target_and_mode,
    reset_api_errors,
)

logger = logging.getLogger(__name__)


def get_client() -> Optional[Anthropic]:
    """Anthropic client を取得。APIキーが無い場合は None を返す。"""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or not api_key.startswith("sk-ant-"):
        return None
    return Anthropic(api_key=api_key)


def get_model() -> str:
    """使用モデル名 (デフォルト: Opus 4.7)。"""
    return os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7")


def is_mock_mode() -> bool:
    """APP_MODE が mock かどうか。"""
    return os.getenv("APP_MODE", "mock").lower() == "mock"


def _gather_ahrefs_data(url: str, url_match_mode: str = "ドメイン一致") -> dict:
    """Ahrefs クライアントから対象データを集める。url_match_mode で取得範囲を制御。

    Site Explorer 系 4 関数 + Brand Radar 1 関数 (内部で 7 platforms 並列) を
    全て並列実行。最終的に Site Explorer 7本 + Brand Radar 7本 = 計14本の
    HTTP リクエストが並列で走る (合計時間 = 一番遅い1本)。
    """
    domain = urlparse(url).netloc or url
    target, mode = resolve_target_and_mode(url, url_match_mode)

    # raw_responses / api_errors は分析開始時に1回だけクリア (各関数内では reset しない前提)
    reset_api_errors()

    with ThreadPoolExecutor(max_workers=5) as executor:
        f_metrics = executor.submit(get_site_metrics, target, mode)
        f_top_kw = executor.submit(get_top_keywords, target, mode)
        f_top_pg = executor.submit(get_top_pages, target, mode)
        f_top_dir = executor.submit(get_top_directories, target, mode)
        f_brand_radar = executor.submit(get_brand_radar_citations, target, mode)

        metrics = f_metrics.result()
        top_kw = f_top_kw.result()
        top_pg = f_top_pg.result()
        top_dir = f_top_dir.result()
        brand_radar = f_brand_radar.result()

    # 流入URL に最有力KWを紐付け
    # 優先順: top-pages が直接返す top_keyword/top_keyword_volume → organic-keywords とのURL照合
    # (top-pages が欠損したケース、または top_keyword フィールドが null のページ用にフォールバック)
    url_to_kw: dict[str, dict] = {}
    for kw in top_kw:
        kw_url = kw.get("url", "")
        if kw_url and kw_url not in url_to_kw:
            # top_kw は traffic 降順なので、最初に見つかった = 最有力
            url_to_kw[kw_url] = {
                "keyword": kw.get("keyword", ""),
                "volume": kw.get("volume", 0),
            }
    for pg in top_pg:
        # top-pages 自身の top_keyword が埋まっていればそれを採用
        if pg.get("top_keyword"):
            continue
        pg_url = pg.get("url", "")
        match = url_to_kw.get(pg_url)
        if match:
            pg["top_keyword"] = match["keyword"]
            pg["top_keyword_volume"] = match["volume"]
        else:
            pg["top_keyword"] = ""
            pg["top_keyword_volume"] = 0

    # ページ数を top-pages の bulk 取得結果から推定
    # (metrics エンドポイントは pages count を返さないため)
    raw = get_last_raw_responses()
    bulk_resp = raw.get("top-pages-bulk-for-directories")
    if isinstance(bulk_resp, dict):
        bulk_pages = (
            bulk_resp.get("pages")
            or bulk_resp.get("top_pages")
            or bulk_resp.get("data")
            or []
        )
        if bulk_pages and not metrics.get("organic_pages_count"):
            page_count = len(bulk_pages)
            # 500件取得した場合は「500+」扱い
            metrics["organic_pages_count"] = page_count
            metrics["organic_pages_count_display"] = (
                f"{page_count}+" if page_count >= 500 else str(page_count)
            )

    # 全エンドポイントの生レスポンスをmetricsに注入 (UI診断用)
    metrics["_raw_responses"] = get_last_raw_responses()
    return {
        "metrics": metrics,
        "top_keywords": top_kw,
        "top_pages": top_pg,
        "top_directories": top_dir,
        "brand_radar": brand_radar,
        "domain": domain,
    }


def _fetch_page_meta(url: str) -> dict:
    """対象URLのHTMLをfetchしてtitle/description/構造化データ等を抽出。"""
    try:
        resp = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (BWSecondOpinion/1.0)"},
        )
        resp.raise_for_status()
        html = resp.text

        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""

        desc_match = re.search(
            r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)["\']',
            html,
            re.IGNORECASE,
        )
        if not desc_match:
            desc_match = re.search(
                r'<meta\s+content=["\']([^"\']*)["\']\s+name=["\']description["\']',
                html,
                re.IGNORECASE,
            )
        meta_description = desc_match.group(1).strip() if desc_match else ""

        canonical_match = re.search(
            r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']*)["\']',
            html,
            re.IGNORECASE,
        )
        canonical = canonical_match.group(1).strip() if canonical_match else ""

        robots_match = re.search(
            r'<meta\s+name=["\']robots["\']\s+content=["\']([^"\']*)["\']',
            html,
            re.IGNORECASE,
        )
        robots = robots_match.group(1).strip() if robots_match else ""
        index_status = "登録済み" if "noindex" not in robots.lower() else "noindex"

        # 構造化データ schema 種類を抽出
        schemas = []
        for m in re.finditer(
            r'"@type"\s*:\s*"([^"]+)"', html
        ):
            schemas.append(m.group(1))
        # 重複除去・順序維持
        seen = set()
        unique_schemas = []
        for s in schemas:
            if s not in seen:
                seen.add(s)
                unique_schemas.append(s)

        return {
            "title": title[:160],
            "meta_description": meta_description[:240],
            "canonical": canonical or "self",
            "index_status": index_status,
            "structured_data": unique_schemas[:8],
            "fetched": True,
        }
    except Exception as e:
        logger.warning(f"_fetch_page_meta failed for {url}: {e}")
        return {
            "title": "",
            "meta_description": "",
            "canonical": "",
            "index_status": "",
            "structured_data": [],
            "fetched": False,
            "error": str(e)[:200],
        }


_AXIS_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "observation": {"type": "string"},
                    "observation_sub": {"type": "string"},
                    "action": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "url": {"type": "string"},
                                "text": {"type": "string"},
                            },
                            "required": ["label", "url"],
                        },
                    },
                    "check_url": {"type": "string"},
                    "priority": {"type": "string", "enum": ["高", "中", "低"]},
                },
                "required": ["observation", "action", "evidence", "priority"],
            },
        },
        "passed": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "unverifiable": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "reason": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    "required": ["issues", "passed"],
}

# ─── 並列分割版 (Mode A 高速化) で使う tool 定義 ────────────────────────
# analyze_site_structured を 6 並列 (5軸 + サマリー) に分割実行するための
# 軽量 tool spec。各 call の出力トークンが小さくなるため Sonnet 4.6 で
# 60-90秒に収まる。

def _make_axis_tool(axis_key: str, axis_name: str) -> dict:
    """1軸分の評価提出 tool。"""
    return {
        "name": f"submit_axis_{axis_key}",
        "description": (
            f"{axis_name} 軸の SEO 評価を提出する。"
            "issues (指摘事項) と passed (通過項目) を構造化して返す。"
        ),
        "input_schema": _AXIS_SCHEMA,
    }


SUMMARY_TOOL = {
    "name": "submit_summary",
    "description": (
        "全体サマリー (強み / 懸念 / 施策案) と 5軸スコア配列、"
        "contradictions (公式 vs 実態) / donts (やってはいけない施策) / "
        "sources (出典リスト) を提出する。各軸の issues/passed は別 call で集計済み。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "object",
                "properties": {
                    "total_score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "axes": {
                        "type": "array",
                        "minItems": 5,
                        "maxItems": 5,
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string", "enum": ["internal_seo", "external_seo", "content_seo", "eeat", "ai_exposure"]},
                                "name": {"type": "string"},
                                "score": {"type": "integer", "minimum": 0, "maximum": 20},
                                "issues": {"type": "integer", "minimum": 0},
                                "total": {"type": "integer"},
                            },
                            "required": ["key", "name", "score", "issues", "total"],
                        },
                    },
                    "strengths": {"type": "string"},
                    "concerns": {"type": "string"},
                    "priority_action": {"type": "string"},
                },
                "required": ["total_score", "axes", "strengths", "concerns", "priority_action"],
            },
            "contradictions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "public": {"type": "string"},
                        "internal": {"type": "string"},
                        "source_label": {"type": "string"},
                        "source_url": {"type": "string"},
                    },
                    "required": ["public", "internal", "source_label", "source_url"],
                },
            },
            "donts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "reason": {"type": "string"},
                        "evidence_label": {"type": "string"},
                        "evidence_url": {"type": "string"},
                    },
                    "required": ["name", "reason", "evidence_label", "evidence_url"],
                },
            },
            "sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "url": {"type": "string"},
                        "label": {"type": "string"},
                    },
                    "required": ["text", "url", "label"],
                },
            },
        },
        "required": ["summary", "contradictions", "donts", "sources"],
    },
}


# 5軸の (key, 表示名, total) — サマリースコア計算とエラー時のフォールバックで共有
_AXIS_META = [
    {"key": "internal_seo", "name": "内部SEO・テクニカル", "total": 17, "needs_ahrefs": False},
    {"key": "external_seo", "name": "外部SEO・サイテーション", "total": 7, "needs_ahrefs": True},
    {"key": "content_seo", "name": "コンテンツSEO・記事", "total": 21, "needs_ahrefs": True},
    {"key": "eeat", "name": "EEAT・広報", "total": 14, "needs_ahrefs": True},
    {"key": "ai_exposure", "name": "AI露出 (LLMO・AI引用)", "total": 8, "needs_ahrefs": False},
]


def extract_scores_for_log(data) -> tuple[dict, Optional[int]]:
    """分析結果 dict から DB ログ用の (axis_scores, total_score) を取り出す。

    axis_scores は {軸名: score} の dict。summary が壊れている場合は ({}, None)。
    """
    if not isinstance(data, dict):
        return {}, None
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return {}, None
    axes = summary.get("axes")
    if not isinstance(axes, list):
        return {}, None
    axis_scores = {
        a.get("name", "?"): a.get("score", 0)
        for a in axes if isinstance(a, dict)
    }
    total = summary.get("total_score")
    return axis_scores, total if isinstance(total, int) else None


def _build_empty_structured(url: str, ahrefs_data: dict, page_meta: dict, error: str = "") -> dict:
    """LLM 失敗時に返す空のスケルトン (スコア 0、空配列)。

    エラー時は Ahrefs データも空にする (分析失敗とのUX一貫性のため)。
    """
    # エラー時は ahrefs も空にする (KPI・KW・URL・ディレクトリ全て表示しない)
    empty_ahrefs = {
        "metrics": {},
        "top_keywords": [],
        "top_pages": [],
        "top_directories": [],
        "brand_radar": {"platforms": {}, "total": 0, "fetched_at": "", "country": ""},
        "domain": ahrefs_data.get("domain", "") if isinstance(ahrefs_data, dict) else "",
    }
    return {
        "target_url": url,
        "summary": {
            "total_score": 0,
            "axes": [
                {"key": "internal_seo", "name": "内部SEO・テクニカル", "score": 0, "issues": 0, "total": 17},
                {"key": "external_seo", "name": "外部SEO・サイテーション", "score": 0, "issues": 0, "total": 7},
                {"key": "content_seo", "name": "コンテンツSEO・記事", "score": 0, "issues": 0, "total": 21},
                {"key": "eeat", "name": "EEAT・広報", "score": 0, "issues": 0, "total": 14},
                {"key": "ai_exposure", "name": "AI露出 (LLMO・AI引用)", "score": 0, "issues": 0, "total": 8},
            ],
            "strengths": "",
            "concerns": "",
            "priority_action": "",
        },
        "url_meta": page_meta,
        "axes": {
            "internal_seo": {"issues": [], "passed": [], "unverifiable": []},
            "external_seo": {"issues": [], "passed": [], "unverifiable": []},
            "content_seo": {"issues": [], "passed": [], "unverifiable": []},
            "eeat": {"issues": [], "passed": [], "unverifiable": []},
            "ai_exposure": {"issues": [], "passed": [], "unverifiable": []},
        },
        "ahrefs": empty_ahrefs,
        "contradictions": [],
        "donts": [],
        "sources": [],
        "error": error,
    }


def _call_axis(
    client: Anthropic,
    url: str,
    axis_key: str,
    axis_name: str,
    axis_total: int,
    page_meta: dict,
    ahrefs_data: Optional[dict],
) -> dict:
    """1軸だけ評価する LLM call。{issues: [...], passed: [...]} を返す。

    ahrefs_data が None の場合は Ahrefs を使わない軸 (内部SEO / AI露出) として
    扱い、Ahrefs 取得を待たずに先行起動するために使う。
    axis_total はこの軸のチェック項目総数 (例: 内部SEO=17)。passed は
    `axis_total - issues件数` を埋め切る指示に使う。"""
    tool = _make_axis_tool(axis_key, axis_name)
    ahrefs_block = (
        f"\n\nAhrefs データ (Site Explorer):\n{json.dumps(ahrefs_data, ensure_ascii=False, indent=2)}"
        if ahrefs_data is not None
        else "\n\n(この軸では Ahrefs データを参照しません。HTML / メタ情報のみで判定してください)"
    )
    user_message = f"""モード: A (軸別分析: {axis_name})
対象URL: {url}
この軸の総チェック項目数: {axis_total}

ページメタ情報 (HTML から自動抽出):
{json.dumps(page_meta, ensure_ascii=False, indent=2)}{ahrefs_block}

要求:
- **{axis_name} 軸のみ**を評価する。他の軸の指摘は出さない。
- 各チェック項目は **issues / passed / unverifiable のいずれか1つ**に分類する。3つの合計が概ね {axis_total} になるのが目安。
- **issues (実害ある課題)**: 与えられた HTML / メタ情報 / Ahrefs データから「問題あり」と確認できたものだけ入れる。**推測や未検証の項目は入れない**。
- **passed (通過項目)**: 与えられたデータから「問題なし」と確認できたもの。`name` (チェックした観点・項目名、例: "canonical タグの自己参照", "OGP og:image 設定") と `url` (実際にチェックした対象ドメイン配下の URL) の dict で返す。
- **unverifiable (確認不可)**: HTML や提供データだけでは合否判定できない項目はここに入れる。例: GSC 連携、サーバ Core Web Vitals 実測、内部リンクグラフ全体、第三者サイテーション、被リンク先の品質詳細など。`name` (項目名) と `reason` (なぜ確認できないか、簡潔に) と `url` (対象ドメイン配下の代表 URL) の dict で返す。
- **passed と unverifiable は必ず埋める**。「課題なし = passed 空配列」ではない。`issues + passed + unverifiable の件数 ≒ {axis_total}` になるよう、軸内のチェック項目を取りこぼさず分類する。
- evidence (issues のみ) は最低1件、url 必須。ラベルは「公式」「QRG」「リーク」「訴訟」「VRP」「特許」「二次解説」「Googler発言」のいずれか
- check_url (issues のみ) は対象ドメイン配下の実在 URL
- 各 issue は priority を "高" / "中" / "低" のいずれかにする

提出は submit_axis_{axis_key} ツールを使うこと (必須)。"""

    try:
        response = client.messages.create(
            model=get_model(),
            max_tokens=5000,  # passed を最大 21項目 (content_seo) 埋める余裕を確保
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        logger.error(f"Axis call failed ({axis_key}): {e}")
        return {"issues": [], "passed": [], "unverifiable": [], "_error": f"{axis_name}: {str(e)[:200]}"}

    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            input_data = block.input
            if isinstance(input_data, dict):
                return input_data
    logger.warning(f"Axis {axis_key}: tool_use block missing")
    return {"issues": [], "passed": [], "unverifiable": [], "_error": f"{axis_name}: ツール呼び出しなし"}


def _call_summary(
    client: Anthropic,
    url: str,
    page_meta: dict,
    ahrefs_data: dict,
) -> dict:
    """サマリー + contradictions/donts/sources を取得する LLM call。"""
    user_message = f"""モード: A (サマリー / 公式 vs 実態 / NG施策 / 出典)
対象URL: {url}

ページメタ情報 (HTML から自動抽出):
{json.dumps(page_meta, ensure_ascii=False, indent=2)}

Ahrefs データ (Site Explorer):
{json.dumps(ahrefs_data, ensure_ascii=False, indent=2)}

要求:
- summary: 全体の強み (strengths) / 懸念 (concerns) / 優先施策 (priority_action) を 2-3文ずつ。total_score は 0-100 整数、axes は5軸ぶんのスコア配列(各 score は 0-20 整数)。
- 各軸の score は (total - 想定 issues 件数) / total * 20 で四捨五入したもの。axes 配列の total 値はそれぞれ 17 / 7 / 21 / 14 / 8。
- contradictions は対象サイトに関連するもの 2-3 件 (Google公式メッセージ vs 内部実装 / リーク / 訴訟資料での実態)
- donts は対象サイトに該当しそうな都市伝説的施策 3-5 件
- sources は出典リスト 6-10 件 (公式 / QRG / リーク / 訴訟 / VRP / 特許 / Googler発言)

提出は submit_summary ツールを使うこと (必須)。"""

    try:
        response = client.messages.create(
            model=get_model(),
            max_tokens=6000,  # サマリー + メタ系は重め
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=[SUMMARY_TOOL],
            tool_choice={"type": "tool", "name": "submit_summary"},
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        logger.error(f"Summary call failed: {e}")
        return {"summary": {}, "contradictions": [], "donts": [], "sources": [], "_error": f"サマリー: {str(e)[:200]}"}

    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            input_data = block.input
            if isinstance(input_data, dict):
                return input_data
    logger.warning("Summary call: tool_use block missing")
    return {"summary": {}, "contradictions": [], "donts": [], "sources": [], "_error": "サマリー: ツール呼び出しなし"}


def _normalize_axis(axis_data) -> dict:
    """軸 call の戻り値を {issues, passed, unverifiable} に正規化。"""
    if not isinstance(axis_data, dict):
        return {"issues": [], "passed": [], "unverifiable": []}
    issues = axis_data.get("issues", [])
    passed = axis_data.get("passed", [])
    unverifiable = axis_data.get("unverifiable", [])
    return {
        "issues": issues if isinstance(issues, list) else [],
        "passed": passed if isinstance(passed, list) else [],
        "unverifiable": unverifiable if isinstance(unverifiable, list) else [],
    }


def analyze_site_structured(
    url: str,
    url_match_mode: str = "完全一致",
) -> dict:
    """Mode A の構造化版。サマリー + 5軸を 6 並列で実行する。

    Ahrefs を待たずに「内部SEO」「AI露出」軸を先行起動 (page_meta だけで判定可)。
    残り 4 call (サマリー / 外部SEO / コンテンツ / EEAT) は Ahrefs 完了後に開始。
    実時間 ≈ max(各 call の所要時間) ≈ 60-90秒。"""
    if is_mock_mode():
        return _build_mock_structured(url)

    client = get_client()
    if client is None:
        return _build_empty_structured(url, {}, {}, error="ANTHROPIC_API_KEY 未設定")

    # Step 1: Ahrefs と page_meta を並列取得
    fetcher_pool = ThreadPoolExecutor(max_workers=2)
    f_ahrefs = fetcher_pool.submit(_gather_ahrefs_data, url, url_match_mode)
    f_meta = fetcher_pool.submit(_fetch_page_meta, url)

    page_meta = f_meta.result()  # 通常 1-3 秒で完了

    # Step 2: page_meta だけで判定可能な軸 (Ahrefs不要) を先行起動
    llm_pool = ThreadPoolExecutor(max_workers=6)
    axis_futures: dict = {}
    for meta in _AXIS_META:
        if not meta["needs_ahrefs"]:
            axis_futures[meta["key"]] = llm_pool.submit(
                _call_axis, client, url, meta["key"], meta["name"], meta["total"], page_meta, None
            )

    # Step 3: Ahrefs 完了を待ち、残りの軸 + サマリーを起動
    ahrefs_data = f_ahrefs.result()
    fetcher_pool.shutdown(wait=False)

    for meta in _AXIS_META:
        if meta["needs_ahrefs"]:
            axis_futures[meta["key"]] = llm_pool.submit(
                _call_axis, client, url, meta["key"], meta["name"], meta["total"], page_meta, ahrefs_data
            )
    f_summary = llm_pool.submit(_call_summary, client, url, page_meta, ahrefs_data)

    # Step 4: 全 call の結果を取得 (各 call は独立に失敗しうる)
    axes_result: dict = {}
    axis_errors: list = []
    for meta in _AXIS_META:
        future = axis_futures[meta["key"]]
        try:
            data = future.result(timeout=240)
        except Exception as e:
            data = {"issues": [], "passed": [], "unverifiable": [], "_error": f"{meta['name']}: {str(e)[:200]}"}
        axes_result[meta["key"]] = _normalize_axis(data)
        if isinstance(data, dict) and data.get("_error"):
            axis_errors.append(data["_error"])

    try:
        summary_data = f_summary.result(timeout=240)
    except Exception as e:
        summary_data = {"summary": {}, "contradictions": [], "donts": [], "sources": [], "_error": f"サマリー: {str(e)[:200]}"}
    if isinstance(summary_data, dict) and summary_data.get("_error"):
        axis_errors.append(summary_data["_error"])

    llm_pool.shutdown(wait=False)

    # Step 5: マージ + スコア再計算 (実 issues 件数ベース、LLM の自己申告は信用しない)
    summary = summary_data.get("summary", {}) if isinstance(summary_data, dict) else {}
    if not isinstance(summary, dict):
        summary = {}

    summary_axes = []
    total_score = 0
    for meta in _AXIS_META:
        issues_n = len(axes_result[meta["key"]].get("issues", []))
        score = round(((meta["total"] - issues_n) / meta["total"]) * 20) if meta["total"] > 0 else 0
        score = max(0, min(20, score))
        total_score += score
        summary_axes.append({
            "key": meta["key"],
            "name": meta["name"],
            "score": score,
            "issues": issues_n,
            "total": meta["total"],
        })
    summary["axes"] = summary_axes
    summary["total_score"] = total_score
    summary.setdefault("strengths", "")
    summary.setdefault("concerns", "")
    summary.setdefault("priority_action", "")

    result = {
        "target_url": url,
        "summary": summary,
        "url_meta": page_meta,
        "axes": axes_result,
        "ahrefs": ahrefs_data,
        "contradictions": summary_data.get("contradictions", []) if isinstance(summary_data, dict) else [],
        "donts": summary_data.get("donts", []) if isinstance(summary_data, dict) else [],
        "sources": summary_data.get("sources", []) if isinstance(summary_data, dict) else [],
    }
    if axis_errors:
        # 一部 call が失敗した場合: アプリは動かしつつ警告だけ残す
        result["_warnings"] = axis_errors
    return result


def review_strategy(strategy_text: str, related_url: str = "") -> str:
    """Mode B: 施策レビュー。"""
    if is_mock_mode():
        return _mock_review_response()

    client = get_client()
    if client is None:
        return "❌ ANTHROPIC_API_KEY が設定されていません。"

    user_message = f"""モード: B (施策レビュー)
{f'関連URL: {related_url}' if related_url else ''}

レビュー対象の施策案:
{strategy_text}

要求:
- 各案を「施策推奨 / 要協議 / 懸念」のいずれかでラベリング
- 各案にエビデンス (バッジ + ソースURL) を添える
- 懸念ラベルの場合は代替案を必ず提示
- 総括で「N案中 X件は懸念、Y件は要協議、Z件は施策推奨」を明示

施策レビューを実行してください。"""

    response = client.messages.create(
        model=get_model(),
        max_tokens=4000,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def answer_question(question: str) -> str:
    """Mode C: 個別質問。"""
    if is_mock_mode():
        return _mock_question_response()

    client = get_client()
    if client is None:
        return "❌ ANTHROPIC_API_KEY が設定されていません。"

    user_message = f"""モード: C (個別質問)

質問:
{question}

要求:
- 出力構造は「結論 / 公式メッセージ側 / 内部実装側 / 整合的な解釈 / 社内議論で使える結論」の5部構成
- エビデンスに必ずクリック可能なソースURLを添える
- 質問の前提自体が誤っているなら、誤りを指摘してから答える

質問に回答してください。"""

    response = client.messages.create(
        model=get_model(),
        max_tokens=4000,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


# ─── Structured mock data (UI binding 用) ────────────────────

def _static_mock_ahrefs(domain: str) -> dict:
    """API呼び出しなしの純粋な静的モックデータ (初期表示用)。"""
    return {
        "metrics": {
            "domain_rating": 42,
            "monthly_organic_sessions": 12500,
            "referring_domains_total": 287,
            "referring_domains_quality": 152,
            "organic_pages_count": 248,
            "organic_pages_count_display": "248",
            "domain": domain,
            "fetched_at": "mock",
            "api_status": "mock",
        },
        "top_keywords": [
            {"keyword": "SEO 内部対策", "volume": 2300, "position": 3, "url": f"https://{domain}/blog/seo-guide", "traffic": 480},
            {"keyword": "Core Web Vitals 改善", "volume": 1800, "position": 5, "url": f"https://{domain}/blog/core-web-vitals", "traffic": 320},
            {"keyword": "canonical URL 設定", "volume": 1200, "position": 4, "url": f"https://{domain}/blog/canonical-url", "traffic": 240},
            {"keyword": "構造化データ JSON-LD", "volume": 980, "position": 7, "url": f"https://{domain}/blog/structured-data", "traffic": 140},
            {"keyword": "robots.txt 書き方", "volume": 850, "position": 6, "url": f"https://{domain}/blog/robots-txt", "traffic": 130},
        ],
        "top_pages": [
            {"url": f"https://{domain}/blog/seo-guide", "estimated_sessions": 3200, "top_keyword": "SEO 内部対策", "top_keyword_volume": 2300},
            {"url": f"https://{domain}/blog/core-web-vitals", "estimated_sessions": 2100, "top_keyword": "Core Web Vitals 改善", "top_keyword_volume": 1800},
            {"url": f"https://{domain}/blog/canonical-url", "estimated_sessions": 1800, "top_keyword": "canonical URL 設定", "top_keyword_volume": 1200},
        ],
        "top_directories": [
            {"directory": "/blog/", "pages": 142, "monthly_sessions": 8250, "share_pct": 66.0},
            {"directory": "/service/", "pages": 18, "monthly_sessions": 1840, "share_pct": 14.7},
            {"directory": "/case/", "pages": 32, "monthly_sessions": 1200, "share_pct": 9.6},
        ],
        "domain": domain,
    }


def _build_mock_structured(url: str) -> dict:
    """サイト分析の構造化モックデータ。app.py の _DEFAULT_DATA と同期する。"""
    HEXDOCS = "https://hexdocs.pm/google_api_content_warehouse/0.4.0/api-reference.html"
    QRG_URL = "https://services.google.com/fh/files/misc/hsw-sqrg.pdf"
    DOJ_URL = "https://www.justice.gov/atr/case/us-and-plaintiff-states-v-google-llc-search"
    SEARCH_CENTRAL = "https://developers.google.com/search/docs?hl=ja"

    domain = urlparse(url).netloc or "example.co.jp"
    base = f"https://{domain}" if not url.startswith("http") else url.split("/", 3)[0] + "//" + domain

    return {
        "target_url": url,
        "summary": {
            "total_score": 71,
            "axes": [
                {"key": "internal_seo", "name": "内部SEO・テクニカル", "score": 16, "issues": 3, "total": 17},
                {"key": "external_seo", "name": "外部SEO・サイテーション", "score": 14, "issues": 2, "total": 7},
                {"key": "content_seo", "name": "コンテンツSEO・記事", "score": 15, "issues": 5, "total": 21},
                {"key": "eeat", "name": "EEAT・広報", "score": 11, "issues": 6, "total": 14},
                {"key": "ai_exposure", "name": "AI露出 (LLMO・AI引用)", "score": 15, "issues": 2, "total": 8},
            ],
            "strengths": "独自の現場データに基づく記述が部分的に存在 / 内部リンク設計はトピックハブを形成しつつある",
            "concerns": "著者プロフィール欠落により `siteAuthority` の伸びが阻害 / `OriginalContentScore` を押し下げる重複コンテンツが3記事",
            "priority_action": "著者プロフィールの構造化と組織情報の整備 (EEAT軸 / 優先度 高)",
        },
        "url_meta": {
            "title": "SEO 内部対策の完全ガイド | example.co.jp",
            "meta_description": "SEO 内部対策のベストプラクティスを、Google公式情報とリーク資料を踏まえて解説",
            "canonical": "self",
            "index_status": "登録済み",
            "structured_data": ["Article", "BreadcrumbList", "Organization"],
            "fetched": False,
        },
        "axes": {
            "internal_seo": {
                "issues": [
                    {"observation": "ページ表示速度", "observation_sub": "PageSpeed Insights: モバイル 48点", "action": "画像のWebP化、render-blocking JS の defer 化、LCP 画像のプリロード設定", "evidence": [{"label": "公式", "url": "https://web.dev/articles/vitals", "text": "Core Web Vitals"}, {"label": "リーク", "url": HEXDOCS, "text": "chromeInTotal"}], "check_url": f"{base}/blog/seo-guide", "priority": "高"},
                    {"observation": "パンくずリスト未設置", "observation_sub": "記事ディレクトリで未実装", "action": "BreadcrumbList schema を全記事に実装", "evidence": [{"label": "公式", "url": "https://developers.google.com/search/docs/appearance/structured-data/breadcrumb", "text": "Search Central Breadcrumb"}], "check_url": f"{base}/blog/seo-guide", "priority": "中"},
                    {"observation": "alt属性の不備", "observation_sub": "画像の30%が未設定", "action": "CMS 側で alt 必須バリデーション", "evidence": [{"label": "公式", "url": "https://developers.google.com/search/docs/appearance/google-images", "text": "image SEO best practices"}], "check_url": f"{base}/blog/structured-data", "priority": "中"},
                ],
                "passed": [
                    {"name": "URL正規化 (HTTPS対応済み)", "url": f"{base}/"},
                    {"name": "リンク切れなし", "url": f"{base}/blog/"},
                    {"name": "sitemap.xml 設置・送信済み", "url": f"{base}/sitemap.xml"},
                    {"name": "robots.txt 適切", "url": f"{base}/robots.txt"},
                    {"name": "内部リンク 絶対パス記載", "url": f"{base}/"},
                    {"name": "主要ページからの導線設置", "url": f"{base}/"},
                    {"name": "CSS-Positioning なし", "url": f"{base}/"},
                    {"name": "モバイル ユーザビリティOK", "url": f"{base}/blog/seo-guide"},
                    {"name": "モバイルアノテーション設定", "url": f"{base}/"},
                    {"name": "MFI 対応", "url": f"{base}/"},
                    {"name": "カスタム404 設置", "url": f"{base}/404-test"},
                    {"name": "サイトマップページ", "url": f"{base}/sitemap/"},
                    {"name": "Search Console 登録", "url": ""},
                    {"name": "GA4 設定", "url": ""},
                ],
            },
            "external_seo": {
                "issues": [
                    {"observation": "外部ドメインへの発リンクの関連性", "observation_sub": "関連性の薄いリンク 5件検出", "action": "関連性の低いリンクには rel=\"nofollow\" を付加", "evidence": [{"label": "QRG", "url": QRG_URL, "text": "QRG Link Quality"}, {"label": "リーク", "url": HEXDOCS, "text": "AnchorMismatchDemotion"}], "check_url": f"{base}/blog/inp-optimization", "priority": "中"},
                    {"observation": "Google ビジネスプロフィール", "observation_sub": "未設定", "action": "GBP登録、NAP情報整備", "evidence": [{"label": "公式", "url": "https://support.google.com/business/", "text": "Google Business Profile"}], "check_url": "https://www.google.com/maps", "priority": "低"},
                ],
                "passed": [
                    {"name": "アンカーテキスト最適化", "url": f"{base}/blog/seo-guide"},
                    {"name": "中古ドメイン使用なし", "url": f"{base}/"},
                    {"name": "サイトレピュテーション健全", "url": f"{base}/"},
                    {"name": "外部リンクのアンカー多様性", "url": ""},
                    {"name": "サイテーション / ブランド言及あり", "url": ""},
                ],
            },
            "content_seo": {
                "issues": [
                    {"observation": "<title>タグの対策KW不足", "observation_sub": "主要10ページで対策KW未含有", "action": "title に「対策KW + サービス名」", "evidence": [{"label": "リーク", "url": HEXDOCS, "text": "titleMatchScore"}, {"label": "公式", "url": "https://developers.google.com/search/docs/appearance/title-link", "text": "title best practices"}], "check_url": f"{base}/service/", "priority": "高"},
                    {"observation": "メインコンテンツ情報不足", "observation_sub": "5ページがインデックス除外 (クロール済 - 未登録)", "action": "独自視点・一次情報を追加", "evidence": [{"label": "リーク", "url": HEXDOCS, "text": "OriginalContentScore"}, {"label": "QRG", "url": QRG_URL, "text": "Helpful Content"}], "check_url": f"{base}/blog/sitemap-xml", "priority": "高"},
                    {"observation": "重複コンテンツ", "observation_sub": "類似度高い記事 3件", "action": "canonical設定 or 統合", "evidence": [{"label": "リーク", "url": HEXDOCS, "text": "OriginalContentScore"}], "check_url": f"{base}/blog/inp-optimization", "priority": "中"},
                    {"observation": "<h1>タグ不適切", "observation_sub": "同一ページ内に複数h1 (4ページ)", "action": "h1を1ページ1つに統一", "evidence": [{"label": "公式", "url": "https://developers.google.com/style/headings", "text": "heading guidelines"}], "check_url": f"{base}/about/", "priority": "中"},
                    {"observation": "meta-description重複", "observation_sub": "8ページで重複", "action": "各ページ独自の description 作成", "evidence": [{"label": "公式", "url": "https://developers.google.com/search/docs/appearance/snippet", "text": "meta description guidelines"}], "check_url": f"{base}/blog/structured-data", "priority": "低"},
                ],
                "passed": [
                    {"name": "title重複なし", "url": f"{base}/blog/seo-guide"},
                    {"name": "hx階層適切", "url": f"{base}/blog/seo-guide"},
                    {"name": "コンテンツボリューム適正", "url": f"{base}/blog/seo-guide"},
                    {"name": "自動生成テキストなし", "url": f"{base}/blog/seo-guide"},
                    {"name": "コピーテキストなし", "url": f"{base}/blog/seo-guide"},
                    {"name": "大量定型文なし", "url": f"{base}/blog/"},
                    {"name": "類似コンテンツなし", "url": f"{base}/blog/"},
                    {"name": "重複URLなし", "url": ""},
                    {"name": "ナビゲーションリンク整備", "url": f"{base}/"},
                    {"name": "サブコンテンツ適正", "url": f"{base}/blog/"},
                    {"name": "視認困難テキストなし", "url": f"{base}/"},
                    {"name": "title属性 過剰使用なし", "url": f"{base}/"},
                    {"name": "meta-keywords 適正", "url": f"{base}/"},
                    {"name": "大規模コンテンツ問題なし", "url": f"{base}/blog/"},
                    {"name": "コンテンツ追加余地あり (継続施策)", "url": f"{base}/blog/"},
                    {"name": "関連ページ網羅", "url": f"{base}/blog/"},
                ],
            },
            "eeat": {
                "issues": [
                    {"observation": "著者プロフィール", "observation_sub": "記事ごとの著者明示なし", "action": "記事末尾に Person schema 付きで配置", "evidence": [{"label": "QRG", "url": QRG_URL, "text": "QRG Experience"}, {"label": "リーク", "url": HEXDOCS, "text": "siteAuthority/pageEntityAuthor"}], "check_url": f"{base}/blog/seo-guide", "priority": "高"},
                    {"observation": "組織情報", "observation_sub": "会社概要が薄手", "action": "Organization schema追加", "evidence": [{"label": "QRG", "url": QRG_URL, "text": "QRG About Us"}, {"label": "公式", "url": "https://blog.google/products/search/about-search-results/", "text": "About this result"}], "check_url": f"{base}/about/", "priority": "高"},
                    {"observation": "ブランド指名検索", "observation_sub": "月間200 → 目標1,000+", "action": "展示会・PR配信で社名露出", "evidence": [{"label": "VRP", "url": "https://www.candour.co.uk/blog/google-search-leak/", "text": "VRP siteAuthority"}, {"label": "リーク", "url": HEXDOCS, "text": "siteAuthority"}], "check_url": f"{base}/", "priority": "高"},
                    {"observation": "第三者言及", "observation_sub": "権威媒体露出ゼロ", "action": "業界トップ3媒体に寄稿/取材獲得", "evidence": [{"label": "QRG", "url": QRG_URL, "text": "Reputation Research"}, {"label": "訴訟", "url": DOJ_URL, "text": "Pandu Nayak証言"}], "check_url": f"{base}/", "priority": "中"},
                    {"observation": "Wikipedia/Wikidata", "observation_sub": "エントリ未作成", "action": "Wikidata エンティティ作成", "evidence": [{"label": "特許", "url": "https://patents.google.com/patent/US8396865B1", "text": "US8396865B1"}], "check_url": "https://www.wikidata.org/", "priority": "中"},
                    {"observation": "受賞・認証", "observation_sub": "記載なし", "action": "受賞・認証あれば組織ページに明示", "evidence": [{"label": "QRG", "url": QRG_URL, "text": "Reputation of Website"}], "check_url": f"{base}/about/", "priority": "低"},
                ],
                "passed": [
                    {"name": "HTTPS / SSL 証明書", "url": f"{base}/"},
                    {"name": "プライバシーポリシー記載", "url": f"{base}/privacy/"},
                    {"name": "運営会社情報の整備", "url": f"{base}/about/"},
                    {"name": "お問い合わせフォーム設置", "url": f"{base}/contact/"},
                    {"name": "著者ページの存在", "url": f"{base}/author/"},
                    {"name": "引用・出典記載", "url": f"{base}/blog/seo-guide"},
                    {"name": "記事更新日の記載", "url": f"{base}/blog/"},
                    {"name": "専門用語の用語集", "url": f"{base}/glossary/"},
                ],
            },
            "ai_exposure": {
                "issues": [
                    {"observation": "llms.txt 未設置", "observation_sub": "AIクローラーへのコンテンツ指針なし", "action": "サイトルートに llms.txt 配置", "evidence": [{"label": "二次解説", "url": "https://llmstxt.org/", "text": "llmstxt.org"}], "check_url": f"{base}/llms.txt", "priority": "低"},
                    {"observation": "AI Overviews への引用ゼロ", "observation_sub": "主要KW検索でのAI回答内引用なし", "action": "パッセージ最適化、Q&A形式の見出し", "evidence": [{"label": "公式", "url": "https://blog.google/products/search/ai-overviews-update-may-2024/", "text": "AI Overviews"}, {"label": "二次解説", "url": "https://ipullrank.com/the-rank-revolution-by-mike-king", "text": "Rank Revolution"}], "check_url": "https://www.google.com/search?q=SEO%20%E5%86%85%E9%83%A8%E5%AF%BE%E7%AD%96&udm=14", "priority": "中"},
                ],
                "passed": [
                    {"name": "Article schema 設置", "url": f"{base}/blog/seo-guide"},
                    {"name": "robots.txt AIクローラー許可", "url": f"{base}/robots.txt"},
                    {"name": "パッセージ構造良好", "url": f"{base}/blog/seo-guide"},
                    {"name": "一次情報・独自データ記載", "url": f"{base}/blog/inp-optimization"},
                    {"name": "質問形式の見出し使用", "url": f"{base}/blog/"},
                    {"name": "用語集・FAQ整備", "url": f"{base}/glossary/"},
                ],
            },
        },
        "ahrefs": _static_mock_ahrefs(domain),  # API呼ばずに静的モック
        "contradictions": [
            {"public": "Gary Illyes「ドメイン全体の権威スコアは存在しない」", "internal": "siteAuthority 属性が存在", "source_label": "リーク", "source_url": HEXDOCS},
            {"public": "Gary Illyes「クリックは直接ランキングに使わない」", "internal": "NavBoost が13ヶ月のクリックデータを使用", "source_label": "訴訟", "source_url": DOJ_URL},
            {"public": "公式「EMD に特別な扱いはない」", "internal": "ExactMatchDomainDemotion 属性が存在", "source_label": "リーク", "source_url": HEXDOCS},
        ],
        "donts": [
            {"name": "架空の著者プロフィールを生成", "reason": "QRGは実体験を重視。Lowest 品質判定の対象", "evidence_label": "QRG", "evidence_url": QRG_URL},
            {"name": "EMD (完全一致ドメイン) を新規取得", "reason": "ExactMatchDomainDemotion 属性が存在", "evidence_label": "リーク", "evidence_url": HEXDOCS},
            {"name": "FAQスキーマを通常コンテンツに追加", "reason": "2023-08以降、政府・医療以外ではリッチリザルトに表示されない", "evidence_label": "公式", "evidence_url": "https://developers.google.com/search/blog/2023/08/howto-faq-changes"},
            {"name": "記事の更新日のみ書き換える", "reason": "bylineDate と semanticDate を比較する仕組みあり、内容を変えない更新は逆効果", "evidence_label": "リーク", "evidence_url": HEXDOCS},
            {"name": "HowToスキーマの追加", "reason": "2023-09に大半のクエリで廃止済み", "evidence_label": "公式", "evidence_url": "https://developers.google.com/search/blog/2023/08/howto-faq-changes"},
        ],
        "sources": [
            {"text": "品質評価ガイドライン (QRG) 2023-11版 p.26-33", "url": QRG_URL, "label": "QRG"},
            {"text": "Content Warehouse API leak (2024-05)", "url": HEXDOCS, "label": "リーク"},
            {"text": "US v. Google LLC (Case 1:20-cv-03010)", "url": DOJ_URL, "label": "訴訟資料"},
            {"text": "Mark Williams-Cook via Google VRP (2024-12)", "url": "https://www.candour.co.uk/blog/google-search-leak/", "label": "VRP"},
            {"text": "US8396865B1 — Sharing user-submitted data", "url": "https://patents.google.com/patent/US8396865B1", "label": "特許"},
            {"text": "US9031929 — Site quality score", "url": "https://patents.google.com/patent/US9031929", "label": "特許"},
            {"text": "Google Search Central docs (公式ドキュメント)", "url": SEARCH_CENTRAL, "label": "公式"},
            {"text": "Mike King (iPullRank) 2024-05-28", "url": "https://ipullrank.com/google-algo-leak", "label": "二次解説"},
        ],
    }


# ─── Mock responses (APP_MODE=mock 時) ────────────────────

def _mock_review_response() -> str:
    return """# 施策レビュー (mockデータ)

頂いた4案を順に評価します。

## [懸念] 1. FAQPage schema 全ページ展開
2023-08以降、Googleはリッチリザルトでの FAQPage 表示を政府/医療機関を除き廃止済みです。
**エビデンス**: [公式] https://developers.google.com/search/blog/2023/08/howto-faq-changes
**代替案**: 実質的な疑問が多いページに限定して残す。

## [要協議] 2. 月20本の新規記事投入
量産自体はNGではないが、独自視点・一次データの欠如した量産は逆効果になる可能性が高い。
**エビデンス**: [リーク] OriginalContentScore / [公式] Helpful Content Update
**条件付き推奨**: 最低5本は自社の現場データを含む記事に。

⚠️ APP_MODE=mock のダミー表示です。
"""


def _mock_question_response() -> str:
    return """# 質問への回答 (mockデータ)

**結論**: 公式メッセージと内部実装にギャップがあります。「ドメインオーソリティ」という名前のシグナルは存在しないが、それに相当する **サイト全体の権威スコア** は実装されています。

**公式メッセージ側**
Gary Illyes は「Google にドメインオーソリティはない」と繰り返し発言。 [Googler発言]

**内部実装側**
2024-05 リーク資料に siteAuthority 属性が存在。 [リーク]
DOJ訴訟で NavBoost が13ヶ月のクリックデータをサイト単位で使うことが判明。 [訴訟資料]

**整合的な解釈**
- Moz の DA のような単一指標は存在しない (公式発言は技術的にこの意味で正しい)
- ただしサイト権威性を表す内部スコアは実在する (siteAuthority)

**社内議論で使える結論**
公式が否定しているのは外部ツールの DA 指標。サイト権威性自体は実在するので、指名検索・品質被リンク・ブランドメンションの増加は **すべて有効**です。

⚠️ APP_MODE=mock のダミー表示です。
"""
