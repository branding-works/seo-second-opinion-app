"""
Ahrefs API v3 クライアント。

AHREFS_API_TOKEN 環境変数が設定されている場合は実 API を呼び出し、
未設定の場合は mock データを返す。

API ドキュメント: https://docs.ahrefs.com/docs/api/reference/
認証: Bearer Token (Advanced プラン以上で利用可能)
"""

import os
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.ahrefs.com/v3"
DEFAULT_TIMEOUT = 30
DEFAULT_COUNTRY = "jp"


# ─── 共通ユーティリティ ────────────────────────────────

def has_ahrefs_token() -> bool:
    """API トークンが設定されているか。"""
    return bool(os.getenv("AHREFS_API_TOKEN"))


def _get_headers() -> dict:
    token = os.getenv("AHREFS_API_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


# 直近のAPIエラー / 生レスポンスを保持 (UI 診断表示用)
# 並列化のため Lock で保護する。
_LAST_API_ERRORS: list[str] = []
_LAST_RAW_RESPONSES: dict = {}
_STATE_LOCK = threading.Lock()


def get_last_api_errors() -> list[str]:
    """直近の API エラーリスト (UI 表示用)。"""
    with _STATE_LOCK:
        return list(_LAST_API_ERRORS)


def get_last_raw_responses() -> dict:
    """直近の生レスポンス (UI 診断表示用)。"""
    with _STATE_LOCK:
        return dict(_LAST_RAW_RESPONSES)


def reset_api_errors() -> None:
    with _STATE_LOCK:
        _LAST_API_ERRORS.clear()
        _LAST_RAW_RESPONSES.clear()


def _record_error(msg: str) -> None:
    with _STATE_LOCK:
        _LAST_API_ERRORS.append(msg)
        if len(_LAST_API_ERRORS) > 20:
            del _LAST_API_ERRORS[:10]


def _record_raw(endpoint: str, response: Optional[dict]) -> None:
    with _STATE_LOCK:
        _LAST_RAW_RESPONSES[endpoint] = response


def _api_get(path: str, params: dict, timeout: int = DEFAULT_TIMEOUT, max_retries: int = 2) -> Optional[dict]:
    """Ahrefs API に GET リクエスト。

    一過性エラー (5xx / 429 / read timeout / ネットワークエラー) は最大
    `max_retries` 回まで自動リトライ。1秒, 2秒の exponential backoff。
    永続エラー (401/403/4xx) はリトライせず即 None。
    全リトライ失敗時のみ _record_error にエラーを残す。
    """
    url = f"{API_BASE}/{path.lstrip('/')}"
    last_err: Optional[str] = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(
                url, headers=_get_headers(), params=params, timeout=timeout
            )
            # 永続エラー: リトライしない
            if response.status_code == 401:
                err = f"401 認証エラー (Ahrefs token無効/期限切れ): {path}"
                logger.error(err)
                _record_error(err)
                return None
            if response.status_code == 403:
                err = f"403 アクセス権限なし (プラン不足の可能性): {path}"
                logger.error(err)
                _record_error(err)
                return None
            # 一過性エラー: 5xx と 429 (rate limit) はリトライ
            if response.status_code >= 500 or response.status_code == 429:
                body = response.text[:200].replace("\n", " ")
                last_err = f"{response.status_code}: {body} ({path})"
                logger.warning(f"Ahrefs API transient error (attempt {attempt + 1}/{max_retries + 1}): {last_err}")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)  # 1秒, 2秒, ...
                    continue
                _record_error(last_err)
                return None
            # その他 4xx: リトライしない (パラメータエラーなど)
            if response.status_code >= 400:
                body = response.text[:200].replace("\n", " ")
                err = f"{response.status_code}: {body} ({path})"
                logger.warning(f"Ahrefs API error: {err}")
                _record_error(err)
                return None
            return response.json()
        except requests.Timeout:
            last_err = f"タイムアウト ({timeout}秒): {path}"
            logger.warning(f"Ahrefs API timeout (attempt {attempt + 1}/{max_retries + 1}): {path}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            _record_error(last_err)
            return None
        except requests.RequestException as e:
            last_err = f"ネットワークエラー: {str(e)[:200]} ({path})"
            logger.warning(f"Ahrefs API network error (attempt {attempt + 1}/{max_retries + 1}): {last_err}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            _record_error(last_err)
            return None
    return None


def _normalize_domain(domain: str) -> str:
    """ドメインから protocol / path を除去。"""
    d = domain.strip()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    d = d.split("/")[0]
    return d


def _safe_get(d: Optional[dict], *keys: str, default: Any = None) -> Any:
    """ネストした辞書から安全に値を取り出す。"""
    if d is None:
        return default
    cur = d
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


def resolve_target_and_mode(url: str, ui_mode: str) -> tuple[str, str]:
    """UI上の一致モードを Ahrefs API の (target, mode) に変換する。

    ui_mode:
      - 完全一致 → exact (target = フルURL、末尾スラッシュ含めて保持)
      - 部分一致 → prefix (target = フルURL)
      - ドメイン一致 → domain (target = ドメイン)
      - サブドメイン含む → subdomains (target = ドメイン)

    注意: 完全一致時に末尾スラッシュを削ると Ahrefs Web UI と URL が
    別物扱いされ集計値がズレるため、入力 URL をそのまま渡す。
    """
    if ui_mode == "完全一致":
        return (url, "exact")
    if ui_mode == "部分一致":
        return (url, "prefix")
    if ui_mode == "サブドメイン含む":
        return (_normalize_domain(url), "subdomains")
    # ドメイン一致 (デフォルト)
    return (_normalize_domain(url), "domain")


# ─── 公開関数 ──────────────────────────────────────────

def _count_dofollow_refdomains(target: str, mode: str = "domain", page_size: int = 1000, max_pages: int = 10) -> Optional[int]:
    """非スパム & dofollow リンクのある refdomain 数を取得。

    正しいエンドポイントは `/site-explorer/refdomains` (Ahrefs API v3)。
    `referring-domains` は 404 を返す古い別名。

    target/mode は呼び出し側のユーザー選択を尊重する (例: 「完全一致」UI なら
    target=https://example.com, mode=exact)。Ahrefs Web UI の「Referring
    domains」表示と整合させるため history=live で現存 refdomains に限定する。
    all_time だと過去に lost した分まで含み実数の数倍になる (例: live=90 vs
    all_time=427 で約4.7倍)。

    `backlinks-stats` には dofollow 内訳がないので、`refdomains` を
    `dofollow_links > 0 AND is_spam = false` でフィルタして件数を数える。

    Pagination 戦略 — Cursor (seek key) 方式:
    `/site-explorer/refdomains` は `offset` パラメータを **持たない**
    (input schema 上に存在せず、渡すと 400: "The 'offset' parameter is not
    supported." が返る)。さらにユーザープランで 1リクエスト最大 500 行程度に
    打ち切られるため、`first_seen` を seek key として `where` 句に
    `first_seen >= 直前ページ末尾の first_seen` を追加し、
    `order_by=first_seen:asc` で安定ソートしながら全件を集計する。
    境界で同一 first_seen の重複が起こりうるので set で domain dedup する。

    Returns: 件数(整数)。API 失敗時 None。
    """
    base_filters = [
        {"field": "dofollow_links", "is": ["gt", 0]},
        {"field": "is_spam", "is": ["eq", False]},
    ]

    seen_domains: set = set()
    last_resp = None
    last_first_seen: Optional[str] = None
    for page in range(max_pages):
        if last_first_seen:
            filters = base_filters + [
                {"field": "first_seen", "is": ["gte", last_first_seen]}
            ]
        else:
            filters = base_filters
        resp = _api_get(
            "site-explorer/refdomains",
            {
                "target": target,
                "mode": mode,
                "protocol": "both",
                "history": "live",
                "select": "domain,first_seen",
                "where": json.dumps({"and": filters}),
                "limit": page_size,
                "order_by": "first_seen:asc",
            },
            timeout=60,
        )
        if not resp:
            # 1ページ目で失敗 → None。途中失敗ならそれまでの合計を返す
            if page == 0:
                _record_raw("refdomains-dofollow", None)
                return None
            break
        last_resp = resp
        rows = _safe_get(resp, "refdomains", default=None) or _safe_get(resp, "data", default=None)
        if not rows:
            break

        added_this_page = 0
        max_first_seen = last_first_seen
        for r in rows:
            if not isinstance(r, dict):
                continue
            domain = r.get("domain")
            if domain and domain not in seen_domains:
                seen_domains.add(domain)
                added_this_page += 1
            fs = r.get("first_seen")
            if fs and (max_first_seen is None or fs > max_first_seen):
                max_first_seen = fs

        # seek key が前進しなかった (= 同一 first_seen のデータが page_size 以上ある)
        # → 1ページに収まらないので break してそれまでの集計を返す
        if max_first_seen == last_first_seen:
            break
        # 全件 dedup で消えた = 既に取得済みのデータ → 終了
        if added_this_page == 0:
            break
        last_first_seen = max_first_seen

    _record_raw("refdomains-dofollow", last_resp)
    return len(seen_domains)


def get_site_metrics(target: str, mode: str = "domain") -> dict:
    """サイト指標 (DR / 被リンク / 月間セッション)。

    target: フルURL or ドメイン (mode に応じる)
    mode: domain / exact / prefix / subdomains

    内部の 4 API 呼び出しは ThreadPoolExecutor で並列実行する (直列だと
    dofollow refdomains が 60秒近くかかるためトータルが極端に重くなる)。
    """
    if not has_ahrefs_token():
        result = _mock_metrics(target)
        result["api_status"] = "AHREFS_API_TOKEN 未設定 (Render環境変数を確認)"
        return result

    today_iso = datetime.utcnow().strftime("%Y-%m-%d")
    common = {"target": target, "mode": mode, "protocol": "both"}

    # ─── DR だけはドメイン単位の指標 ───
    # DR は「ドメインの強さ」指標で URL 固有値ではないため、ユーザーが exact を
    # 選んでも domain モードでドメイン名から取得する (URL を渡すと値が取れない)。
    domain_target = _normalize_domain(target)
    domain_common = {"target": domain_target, "mode": "domain", "protocol": "both"}

    # ─── backlinks / refdomains の取得モード調整 ───
    # ユーザーが「部分一致 (prefix)」を選んでも、target がドメインルート
    # (path が "/" or 空) の場合は実質ドメイン全体を見たい意図。Ahrefs API
    # は prefix を厳密に解釈し target=https://example.com/ を「ルート1URL」
    # に絞ってしまい backlinks-stats が metrics: null を返す。
    # → ドメインルート + prefix の場合のみ自動で domain モードにフォールバック。
    # サブパス (/blog/ 等) を渡された場合はユーザー意図通り prefix のままにする。
    def _is_domain_root(t: str) -> bool:
        try:
            p = urlparse(t if t.startswith(("http://", "https://")) else "https://" + t)
            path = (p.path or "/").rstrip("/")
            return path == "" and not p.query and not p.fragment
        except Exception:
            return False

    if mode == "prefix" and _is_domain_root(target):
        bl_target, bl_mode = domain_target, "domain"
    else:
        bl_target, bl_mode = target, mode
    bl_common = {"target": bl_target, "mode": bl_mode, "protocol": "both"}

    def _fetch_dr() -> Optional[dict]:
        resp = _api_get("site-explorer/domain-rating", {**domain_common, "date": today_iso})
        _record_raw("domain-rating", resp)
        return resp

    def _fetch_traffic() -> Optional[dict]:
        resp = _api_get(
            "site-explorer/metrics",
            {
                **common,
                "country": DEFAULT_COUNTRY,
                "volume_mode": "monthly",
                "date": today_iso,
            },
        )
        _record_raw("metrics", resp)
        return resp

    def _fetch_backlinks() -> Optional[dict]:
        resp = _api_get("site-explorer/backlinks-stats", {**bl_common, "date": today_iso})
        _record_raw("backlinks-stats", resp)
        return resp

    # 4つの API を並列呼び出し (合計時間 = 一番遅い1本に律速される)
    with ThreadPoolExecutor(max_workers=4) as executor:
        f_dr = executor.submit(_fetch_dr)
        f_traffic = executor.submit(_fetch_traffic)
        f_backlinks = executor.submit(_fetch_backlinks)
        # dofollow refdomains は backlinks と同じ (target, mode) で取得
        f_dofollow = executor.submit(_count_dofollow_refdomains, bl_target, bl_mode)

        dr_resp = f_dr.result()
        metrics_resp = f_traffic.result()
        rd_resp = f_backlinks.result()
        rd_dofollow = f_dofollow.result()

    dr = (
        _safe_get(dr_resp, "domain_rating", "domain_rating", default=None)
        or _safe_get(dr_resp, "domain_rating", default=None)
    )
    sessions = (
        _safe_get(metrics_resp, "metrics", "org_traffic", default=None)
        or _safe_get(metrics_resp, "org_traffic", default=None)
    )
    pages_count = (
        _safe_get(metrics_resp, "metrics", "pages", default=None)
        or _safe_get(metrics_resp, "metrics", "org_pages", default=None)
        or _safe_get(metrics_resp, "metrics", "indexed_pages", default=None)
        or _safe_get(metrics_resp, "pages", default=None)
    )
    # Ahrefs Web UI の「Referring domains (全体)」は実測値ベースで
    # live_refdomains に近い (例: spc-jpn.co.jp で UI=98 vs API live=90)。
    # all_time_refdomains は過去の lost を含み数倍になるため使わない。
    rd_total = (
        _safe_get(rd_resp, "metrics", "live_refdomains", default=None)
        or _safe_get(rd_resp, "metrics", "refdomains", default=None)
        or _safe_get(rd_resp, "metrics", "all_time_refdomains", default=None)
        or _safe_get(rd_resp, "live_refdomains", default=None)
        or _safe_get(rd_resp, "refdomains", default=None)
        or _safe_get(rd_resp, "backlinks_stats", "refdomains", default=None)
    )

    # Fallback to mock if API failed for the main fields
    if dr is None and sessions is None:
        logger.warning("Ahrefs API: 主要メトリクス取得失敗、mock fallback")
        result = _mock_metrics(target)
        result["api_status"] = "API失敗 → mockデータで表示"
        result["api_errors"] = get_last_api_errors()
        return result

    return {
        "domain_rating": dr if dr is not None else 0,
        "monthly_organic_sessions": sessions if sessions is not None else 0,
        "referring_domains_total": rd_total if rd_total is not None else 0,
        "referring_domains_quality": rd_dofollow if rd_dofollow is not None else 0,
        "organic_pages_count": pages_count if pages_count is not None else 0,
        "domain": target,
        "fetched_at": "Ahrefs API v3 (live)",
        "api_status": "live",
        # 部分的な API 失敗(refdomains-dofollow など個別エンドポイント)を診断するため、
        # live ステータス時もエラーリストは返しておく
        "api_errors": get_last_api_errors(),
    }


def get_top_keywords(target: str, mode: str = "domain", limit: int = 10) -> list[dict]:
    """流入貢献KW 上位N件。target/mode は Ahrefs API パラメータ。"""
    if not has_ahrefs_token():
        return _mock_top_keywords()

    today_iso = datetime.utcnow().strftime("%Y-%m-%d")
    # 複数フィールド名を順次試す (Ahrefs API v3 の正しい組み合わせを探す)
    field_attempts = [
        ("keyword,volume,best_position,sum_traffic,best_position_url", "sum_traffic:desc"),
        ("keyword,volume,current_position,sum_traffic,best_position_url", "sum_traffic:desc"),
        ("keyword,volume,best_position", None),  # 最小限・order_by なし
        ("keyword,volume", None),  # 究極の最小
    ]
    keywords = None
    for select, order_by in field_attempts:
        params = {
            "target": target,
            "mode": mode,
            "country": DEFAULT_COUNTRY,
            "limit": limit,
            "date": today_iso,
            "select": select,
        }
        if order_by:
            params["order_by"] = order_by
        resp = _api_get("site-explorer/organic-keywords", params)
        _record_raw("organic-keywords", resp)
        keywords = (
            _safe_get(resp, "keywords", default=None)
            or _safe_get(resp, "organic_keywords", default=None)
            or _safe_get(resp, "data", default=None)
        )
        if keywords:
            logger.info(f"organic-keywords: select='{select}' で成功")
            break

    if not keywords:
        logger.warning("Ahrefs API: 上位KW取得失敗、mock fallback")
        return _mock_top_keywords()

    result = []
    for k in keywords[:limit]:
        url_full = k.get("best_position_url") or k.get("url", "")
        # position は best_position / current_position / position の順で取得
        position = (
            k.get("best_position")
            or k.get("current_position")
            or k.get("position")
            or 0
        )
        # traffic は sum_traffic / traffic の順
        traffic = k.get("sum_traffic", k.get("traffic", 0))
        result.append({
            "keyword": k.get("keyword", ""),
            "volume": k.get("volume", 0),
            "position": position,
            "url": url_full,  # フルURL のまま保持
            "traffic": traffic,
        })
    return result


def get_top_pages(target: str, mode: str = "domain", limit: int = 10) -> list[dict]:
    """流入URL 上位N件。target/mode は Ahrefs API パラメータ。

    `top_keyword` と `top_keyword_volume` も同時取得することで、各ページの
    代表 KW を 1 リクエストで埋める (organic-keywords の上位 N 件と URL が
    一致しないページでも空欄にならない)。"""
    if not has_ahrefs_token():
        return _mock_top_pages()

    today_iso = datetime.utcnow().strftime("%Y-%m-%d")
    resp = _api_get(
        "site-explorer/top-pages",
        {
            "target": target,
            "mode": mode,
            "country": DEFAULT_COUNTRY,
            "limit": limit,
            "date": today_iso,
            "order_by": "sum_traffic:desc",
            "select": "url,sum_traffic,top_keyword,top_keyword_volume",
        },
    )
    _record_raw("top-pages", resp)
    pages = (
        _safe_get(resp, "pages", default=None)
        or _safe_get(resp, "top_pages", default=None)
        or _safe_get(resp, "data", default=None)
    )
    if not pages:
        logger.warning("Ahrefs API: 上位ページ取得失敗、mock fallback")
        return _mock_top_pages()

    result = []
    for p in pages[:limit]:
        url_full = p.get("url", "")
        result.append({
            "url": url_full,  # フルURL のまま保持
            "estimated_sessions": p.get("sum_traffic", p.get("traffic", 0)),
            # 各ページの代表 KW を top-pages から直接取得 (空なら organic-keywords 紐付けに任せる)
            "top_keyword": p.get("top_keyword") or "",
            "top_keyword_volume": p.get("top_keyword_volume") or 0,
        })
    return result


def get_top_directories(target: str, mode: str = "domain", limit: int = 10) -> list[dict]:
    """サイト構成 上位ディレクトリ。

    top-pages の結果からディレクトリ単位に集計する (大量ページ取得→集計)。
    target/mode は Ahrefs API パラメータ。
    """
    if not has_ahrefs_token():
        return _mock_top_directories()

    today_iso = datetime.utcnow().strftime("%Y-%m-%d")
    # 大量取得してディレクトリ単位に集計
    resp = _api_get(
        "site-explorer/top-pages",
        {
            "target": target,
            "mode": mode,
            "country": DEFAULT_COUNTRY,
            "limit": 500,  # ディレクトリ集計のため広めに取得
            "date": today_iso,
            "order_by": "sum_traffic:desc",
            "select": "url,sum_traffic",
        },
    )
    _record_raw("top-pages-bulk-for-directories", resp)
    pages = (
        _safe_get(resp, "pages", default=None)
        or _safe_get(resp, "top_pages", default=None)
        or _safe_get(resp, "data", default=None)
    )
    if not pages:
        logger.warning("Ahrefs API: ディレクトリ集計用ページ取得失敗、mock fallback")
        return _mock_top_directories()

    # ディレクトリ集計
    dir_aggr: dict[str, dict[str, int]] = {}
    total_traffic = 0
    for p in pages:
        url_full = p.get("url", "")
        traffic = p.get("sum_traffic", p.get("traffic", 0))
        total_traffic += traffic
        # 第一階層のディレクトリを取得
        if url_full.startswith("http"):
            parts = url_full.split("/", 4)
            if len(parts) >= 4 and parts[3]:
                directory = "/" + parts[3] + "/"
            else:
                directory = "/"
        else:
            directory = "/"

        if directory not in dir_aggr:
            dir_aggr[directory] = {"pages": 0, "monthly_sessions": 0}
        dir_aggr[directory]["pages"] += 1
        dir_aggr[directory]["monthly_sessions"] += traffic

    # シェア計算 + ソート
    result = []
    for directory, agg in dir_aggr.items():
        share_pct = (
            (agg["monthly_sessions"] / total_traffic * 100)
            if total_traffic > 0
            else 0
        )
        result.append({
            "directory": directory,
            "pages": agg["pages"],
            "monthly_sessions": agg["monthly_sessions"],
            "share_pct": round(share_pct, 1),
        })
    result.sort(key=lambda r: r["monthly_sessions"], reverse=True)
    return result[:limit]


# ─── Brand Radar (AI 引用) ────────────────────────────

# Ahrefs Brand Radar が対応する 7 chatbot platforms。
# google_ai_overviews と google_ai_mode は同じリクエストに混在不可、
# 非 Google モデルとも混在不可なので 1 platform につき 1 call。
_BRAND_RADAR_PLATFORMS: list[tuple[str, str]] = [
    ("google_ai_overviews", "AI Overviews"),
    ("google_ai_mode", "AI Mode"),
    ("chatgpt", "ChatGPT"),
    ("gemini", "Gemini"),
    ("perplexity", "Perplexity"),
    ("copilot", "Copilot"),
    ("grok", "Grok"),
]


def _build_brand_radar_where(target: str, mode: str) -> tuple[dict, str]:
    """Brand Radar `where` 句を URL一致モードに合わせて生成。

    Returns: (where_dict, expected_url_prefix)
    expected_url_prefix は API レスポンスを Python 側で再フィルタするために使う
    (Ahrefs API は同一応答内の他ドメイン引用も返すため)。
    """
    domain = _normalize_domain(target)
    if mode == "exact":
        # 完全一致: 特定 URL のみ
        url_no_proto = target
        for prefix in ("https://", "http://"):
            if url_no_proto.startswith(prefix):
                url_no_proto = url_no_proto[len(prefix):]
        where = {"field": "cited_url_exact", "is": ["eq", url_no_proto]}
        return where, url_no_proto
    if mode == "prefix":
        url_no_proto = target
        for prefix in ("https://", "http://"):
            if url_no_proto.startswith(prefix):
                url_no_proto = url_no_proto[len(prefix):]
        where = {"field": "cited_url_prefix", "is": ["eq", url_no_proto]}
        return where, url_no_proto
    if mode == "subdomains":
        where = {"field": "cited_domain_subdomains", "is": ["eq", domain]}
        return where, domain
    # domain (default)
    where = {"field": "cited_domain", "is": ["eq", domain]}
    return where, domain


def _fetch_brand_radar_one_platform(
    data_source: str, where_filter: dict, expected_prefix: str, country: str = ""
) -> Optional[int]:
    """1 platform 分の brand-radar-cited-pages を取得し、自社配下ページの
    responses 合計を返す。API 失敗時 None。

    `country` は空文字なら送信しない (Brand Radar API はユーザー側 Web UI で
    設定済みのレポート / プラン上の地域指定を尊重する。明示的に "JP" 等を
    渡すと {"error":"bad country"} を返すケースがあるため、迷ったら空にする)。
    """
    params: dict[str, Any] = {
        "data_source": data_source,
        "select": "url,responses",
        "where": json.dumps(where_filter),
        "limit": 1000,
    }
    if country:
        params["country"] = country
    resp = _api_get(
        "brand-radar/cited-pages",
        params,
        timeout=60,
    )
    if not resp:
        return None
    pages = _safe_get(resp, "pages", default=None) or []
    if not isinstance(pages, list):
        return 0
    # API は同一応答内の他ドメイン引用も含めて返すため、自社配下のみ Python 側で再フィルタ
    total = 0
    for p in pages:
        if not isinstance(p, dict):
            continue
        url = (p.get("url") or "").lstrip("/")
        # http(s) は API レスポンスに含まれない (n-works.link/blog/...形式)
        if url.startswith(expected_prefix.rstrip("/")):
            r = p.get("responses", 0)
            if isinstance(r, (int, float)):
                total += int(r)
    return total


def get_brand_radar_citations(target: str, mode: str = "domain", country: str = "") -> dict:
    """7 platforms の AI 引用回数を並列取得。

    Returns: {
        "platforms": {
            "google_ai_overviews": {"label": "AI Overviews", "responses": 758, "status": "ok"},
            ...
        },
        "total": 3700,                 # 全 platform の合計
        "fetched_at": "Ahrefs Brand Radar (live)",
        "country": "",
    }
    country は空なら API 呼び出しから除外する (Brand Radar は明示的な "JP" を
    エラー扱いする場合があるため、デフォルトは空 = ユーザー Web UI 設定に従う)。
    エラーの platform は status="error" になり responses は 0。
    """
    if not has_ahrefs_token():
        return _mock_brand_radar()

    where_filter, expected_prefix = _build_brand_radar_where(target, mode)
    platforms_result: dict = {}
    total = 0

    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = {
            executor.submit(
                _fetch_brand_radar_one_platform, ds, where_filter, expected_prefix, country
            ): (ds, label)
            for ds, label in _BRAND_RADAR_PLATFORMS
        }
        for future, (ds, label) in futures.items():
            try:
                count = future.result(timeout=180)
            except Exception as e:
                logger.warning(f"Brand Radar {ds}: {e}")
                count = None
            if count is None:
                platforms_result[ds] = {"label": label, "responses": 0, "status": "error"}
            else:
                platforms_result[ds] = {"label": label, "responses": count, "status": "ok"}
                total += count

    return {
        "platforms": platforms_result,
        "total": total,
        "fetched_at": "Ahrefs Brand Radar (live)",
        "country": country,
    }


# ─── Mock データ (token 未設定時) ──────────────────────

def _mock_metrics(domain: str) -> dict:
    return {
        "domain_rating": 42,
        "monthly_organic_sessions": 12500,
        "referring_domains_total": 287,
        "referring_domains_quality": 152,
        "organic_pages_count": 248,
        "domain": domain,
        "fetched_at": "mock",
    }


def _mock_top_keywords() -> list[dict]:
    return [
        {"keyword": "SEO 内部対策", "volume": 2300, "position": 3, "url": "/blog/seo-guide"},
        {"keyword": "Core Web Vitals 改善", "volume": 1800, "position": 5, "url": "/blog/core-web-vitals"},
        {"keyword": "canonical URL 設定", "volume": 1200, "position": 4, "url": "/blog/canonical-url"},
        {"keyword": "構造化データ JSON-LD", "volume": 980, "position": 7, "url": "/blog/structured-data"},
        {"keyword": "robots.txt 書き方", "volume": 850, "position": 6, "url": "/blog/robots-txt"},
        {"keyword": "サイトマップ 作成", "volume": 720, "position": 8, "url": "/blog/sitemap-xml"},
        {"keyword": "INP 改善", "volume": 640, "position": 4, "url": "/blog/inp-optimization"},
        {"keyword": "hreflang 実装", "volume": 510, "position": 11, "url": "/blog/hreflang-tutorial"},
        {"keyword": "SEO ドメインオーソリティ", "volume": 480, "position": 9, "url": "/blog/eeat-explained"},
        {"keyword": "ページネーション SEO", "volume": 420, "position": 14, "url": "/blog/pagination-seo"},
    ]


def _mock_top_pages() -> list[dict]:
    return [
        {"url": "/blog/seo-guide", "estimated_sessions": 3200},
        {"url": "/blog/core-web-vitals", "estimated_sessions": 2100},
        {"url": "/blog/canonical-url", "estimated_sessions": 1800},
        {"url": "/blog/structured-data", "estimated_sessions": 1400},
        {"url": "/blog/robots-txt", "estimated_sessions": 1200},
        {"url": "/blog/sitemap-xml", "estimated_sessions": 980},
        {"url": "/blog/inp-optimization", "estimated_sessions": 850},
        {"url": "/blog/internal-linking", "estimated_sessions": 720},
        {"url": "/blog/eeat-explained", "estimated_sessions": 580},
        {"url": "/blog/hreflang-tutorial", "estimated_sessions": 510},
    ]


def _mock_top_directories() -> list[dict]:
    return [
        {"directory": "/blog/", "pages": 142, "monthly_sessions": 8250, "share_pct": 66.0},
        {"directory": "/service/", "pages": 18, "monthly_sessions": 1840, "share_pct": 14.7},
        {"directory": "/case/", "pages": 32, "monthly_sessions": 1200, "share_pct": 9.6},
        {"directory": "/column/", "pages": 28, "monthly_sessions": 620, "share_pct": 4.9},
        {"directory": "/about/", "pages": 5, "monthly_sessions": 280, "share_pct": 2.2},
        {"directory": "/news/", "pages": 24, "monthly_sessions": 95, "share_pct": 0.8},
        {"directory": "/contact/", "pages": 3, "monthly_sessions": 75, "share_pct": 0.6},
        {"directory": "/faq/", "pages": 12, "monthly_sessions": 60, "share_pct": 0.5},
        {"directory": "/partner/", "pages": 8, "monthly_sessions": 45, "share_pct": 0.4},
        {"directory": "/sitemap/", "pages": 1, "monthly_sessions": 35, "share_pct": 0.3},
    ]


def _mock_brand_radar() -> dict:
    """token 未設定 / mock モード時のダミー Brand Radar データ。"""
    sample = {
        "google_ai_overviews": ("AI Overviews", 758),
        "google_ai_mode": ("AI Mode", 2600),
        "chatgpt": ("ChatGPT", 24),
        "gemini": ("Gemini", 0),
        "perplexity": ("Perplexity", 87),
        "copilot": ("Copilot", 6),
        "grok": ("Grok", 148),
    }
    platforms = {ds: {"label": label, "responses": n, "status": "ok"} for ds, (label, n) in sample.items()}
    total = sum(p["responses"] for p in platforms.values())
    return {
        "platforms": platforms,
        "total": total,
        "fetched_at": "mock",
        "country": "JP",
    }
