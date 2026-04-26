"""
Ahrefs API クライアント。

未設定時は mock データを返す。実APIアクセスには有料の Ahrefs API token が必要。
詳細: https://ahrefs.com/api
"""

import os
from typing import Optional


def has_ahrefs_token() -> bool:
    return bool(os.getenv("AHREFS_API_TOKEN"))


def get_site_metrics(domain: str) -> dict:
    """サイト指標 (DR / 被リンク / 月間セッション) を取得。

    実装は将来 https://api.ahrefs.com/v3/ にHTTP呼び出しを追加。
    現状はモックデータを返す。
    """
    if not has_ahrefs_token():
        return _mock_metrics(domain)

    # TODO: 実際の Ahrefs API 呼び出し
    # import requests
    # headers = {"Authorization": f"Bearer {os.getenv('AHREFS_API_TOKEN')}"}
    # response = requests.get(
    #     "https://api.ahrefs.com/v3/site-explorer/domain-rating",
    #     headers=headers,
    #     params={"target": domain, "mode": "domain"},
    # )
    # return response.json()

    return _mock_metrics(domain)


def get_top_keywords(domain: str, limit: int = 10) -> list[dict]:
    """流入貢献KW 上位N件。"""
    if not has_ahrefs_token():
        return _mock_top_keywords()

    # TODO: 実 API 呼び出し
    return _mock_top_keywords()


def get_top_pages(domain: str, limit: int = 10) -> list[dict]:
    """流入URL 上位N件。"""
    if not has_ahrefs_token():
        return _mock_top_pages()

    # TODO: 実 API 呼び出し
    return _mock_top_pages()


def get_top_directories(domain: str, limit: int = 10) -> list[dict]:
    """サイト構成 上位ディレクトリ。"""
    if not has_ahrefs_token():
        return _mock_top_directories()

    # TODO: 実 API 呼び出し (top_pages を集計してディレクトリ単位に変換)
    return _mock_top_directories()


# ─── Mock data ────────────────────────────────────────

def _mock_metrics(domain: str) -> dict:
    return {
        "domain_rating": 42,
        "monthly_organic_sessions": 12500,
        "referring_domains_total": 287,
        "referring_domains_quality": 152,
        "organic_pages_count": 248,
        "domain": domain,
        "fetched_at": "2026-04-27 (mock)",
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
