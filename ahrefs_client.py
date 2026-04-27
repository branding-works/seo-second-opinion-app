"""
Ahrefs API v3 クライアント。

AHREFS_API_TOKEN 環境変数が設定されている場合は実 API を呼び出し、
未設定の場合は mock データを返す。

API ドキュメント: https://docs.ahrefs.com/docs/api/reference/
認証: Bearer Token (Advanced プラン以上で利用可能)
"""

import os
import logging
from datetime import datetime
from typing import Optional, Any

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


# 直近のAPIエラーを保持 (UI診断表示用)
_LAST_API_ERRORS: list[str] = []
# 直近の生レスポンスを保持 (フィールド名診断用)
_LAST_RAW_RESPONSES: dict = {}


def get_last_api_errors() -> list[str]:
    """直近の API エラーリスト (UI 表示用)。"""
    return list(_LAST_API_ERRORS)


def get_last_raw_responses() -> dict:
    """直近の生レスポンス (UI 診断表示用)。"""
    return dict(_LAST_RAW_RESPONSES)


def reset_api_errors() -> None:
    _LAST_API_ERRORS.clear()
    _LAST_RAW_RESPONSES.clear()


def _record_error(msg: str) -> None:
    _LAST_API_ERRORS.append(msg)
    if len(_LAST_API_ERRORS) > 20:
        del _LAST_API_ERRORS[:10]


def _record_raw(endpoint: str, response: Optional[dict]) -> None:
    _LAST_RAW_RESPONSES[endpoint] = response


def _api_get(path: str, params: dict) -> Optional[dict]:
    """Ahrefs API に GET リクエスト。エラー時は None を返す。"""
    url = f"{API_BASE}/{path.lstrip('/')}"
    try:
        response = requests.get(
            url, headers=_get_headers(), params=params, timeout=DEFAULT_TIMEOUT
        )
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
        if response.status_code >= 400:
            body = response.text[:200].replace("\n", " ")
            err = f"{response.status_code}: {body} ({path})"
            logger.warning(f"Ahrefs API error: {err}")
            _record_error(err)
            return None
        return response.json()
    except requests.RequestException as e:
        err = f"ネットワークエラー: {str(e)[:200]} ({path})"
        logger.error(err)
        _record_error(err)
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


# ─── 公開関数 ──────────────────────────────────────────

def get_site_metrics(domain: str) -> dict:
    """サイト指標 (DR / 被リンク / 月間セッション)。"""
    reset_api_errors()  # 新しい分析開始でクリア
    if not has_ahrefs_token():
        result = _mock_metrics(domain)
        result["api_status"] = "AHREFS_API_TOKEN 未設定 (Render環境変数を確認)"
        return result

    target = _normalize_domain(domain)
    today_iso = datetime.utcnow().strftime("%Y-%m-%d")
    common = {"target": target, "mode": "domain", "protocol": "both"}

    # Domain Rating (date は YYYY-MM-DD 必須)
    dr_resp = _api_get(
        "site-explorer/domain-rating",
        {**common, "date": today_iso},
    )
    _record_raw("domain-rating", dr_resp)
    dr = (
        _safe_get(dr_resp, "domain_rating", "domain_rating", default=None)
        or _safe_get(dr_resp, "domain_rating", default=None)
    )

    # Traffic / Organic metrics (date 必須)
    metrics_resp = _api_get(
        "site-explorer/metrics",
        {
            **common,
            "country": DEFAULT_COUNTRY,
            "volume_mode": "monthly",
            "date": today_iso,
        },
    )
    _record_raw("metrics", metrics_resp)
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

    # Backlinks/Referring Domains 集計 (フィールド名は live_refdomains が正)
    rd_resp = _api_get("site-explorer/backlinks-stats", {**common, "date": today_iso})
    _record_raw("backlinks-stats", rd_resp)
    rd_total = (
        _safe_get(rd_resp, "metrics", "live_refdomains", default=None)
        or _safe_get(rd_resp, "metrics", "refdomains", default=None)
        or _safe_get(rd_resp, "metrics", "all_time_refdomains", default=None)
        or _safe_get(rd_resp, "live_refdomains", default=None)
        or _safe_get(rd_resp, "refdomains", default=None)
        or _safe_get(rd_resp, "backlinks_stats", "refdomains", default=None)
    )
    rd_dofollow = (
        _safe_get(rd_resp, "metrics", "live_refdomains_dofollow", default=None)
        or _safe_get(rd_resp, "metrics", "refdomains_dofollow", default=None)
        or _safe_get(rd_resp, "metrics", "live_dofollow_refdomains", default=None)
        or _safe_get(rd_resp, "live_refdomains_dofollow", default=None)
        or _safe_get(rd_resp, "refdomains_dofollow", default=None)
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
    }


def get_top_keywords(domain: str, limit: int = 10) -> list[dict]:
    """流入貢献KW 上位N件。"""
    if not has_ahrefs_token():
        return _mock_top_keywords()

    target = _normalize_domain(domain)
    today_iso = datetime.utcnow().strftime("%Y-%m-%d")
    resp = _api_get(
        "site-explorer/organic-keywords",
        {
            "target": target,
            "mode": "domain",
            "country": DEFAULT_COUNTRY,
            "limit": limit,
            "date": today_iso,
        },
    )
    _record_raw("organic-keywords", resp)
    keywords = (
        _safe_get(resp, "keywords", default=None)
        or _safe_get(resp, "organic_keywords", default=None)
        or _safe_get(resp, "data", default=None)
    )
    if not keywords:
        logger.warning("Ahrefs API: 上位KW取得失敗、mock fallback")
        return _mock_top_keywords()

    result = []
    for k in keywords[:limit]:
        url_full = k.get("best_position_url") or k.get("url", "")
        # ドメイン部分を除去してパスのみに
        if url_full.startswith("http"):
            url_path = "/" + url_full.split("/", 3)[-1] if "/" in url_full[8:] else "/"
        else:
            url_path = url_full or "/"
        result.append({
            "keyword": k.get("keyword", ""),
            "volume": k.get("volume", 0),
            "position": k.get("position", 0),
            "url": url_path,
        })
    return result


def get_top_pages(domain: str, limit: int = 10) -> list[dict]:
    """流入URL 上位N件。"""
    if not has_ahrefs_token():
        return _mock_top_pages()

    target = _normalize_domain(domain)
    today_iso = datetime.utcnow().strftime("%Y-%m-%d")
    resp = _api_get(
        "site-explorer/top-pages",
        {
            "target": target,
            "mode": "domain",
            "country": DEFAULT_COUNTRY,
            "limit": limit,
            "date": today_iso,
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
        if url_full.startswith("http"):
            parts = url_full.split("/", 3)
            url_path = "/" + parts[-1] if len(parts) > 3 else "/"
        else:
            url_path = url_full or "/"
        result.append({
            "url": url_path,
            "estimated_sessions": p.get("traffic", 0),
        })
    return result


def get_top_directories(domain: str, limit: int = 10) -> list[dict]:
    """サイト構成 上位ディレクトリ。

    top-pages の結果からディレクトリ単位に集計する (大量ページ取得→集計)。
    """
    if not has_ahrefs_token():
        return _mock_top_directories()

    target = _normalize_domain(domain)
    today_iso = datetime.utcnow().strftime("%Y-%m-%d")
    # 大量取得してディレクトリ単位に集計
    resp = _api_get(
        "site-explorer/top-pages",
        {
            "target": target,
            "mode": "domain",
            "country": DEFAULT_COUNTRY,
            "limit": 500,  # ディレクトリ集計のため広めに取得
            "date": today_iso,
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
        traffic = p.get("traffic", 0)
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
