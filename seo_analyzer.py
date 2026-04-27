"""
SEO セカンドオピニオン Anthropic API ラッパー。

Mode A (サイト分析) / Mode B (施策レビュー) / Mode C (個別質問) の3モードに対応。
APP_MODE=mock の場合は実APIを呼ばずダミーデータを返す。
"""

import os
import json
import re
import logging
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


def _gather_ahrefs_data(url: str) -> dict:
    """Ahrefs クライアントから対象ドメインの全データを集める。"""
    domain = urlparse(url).netloc or url
    return {
        "metrics": get_site_metrics(domain),
        "top_keywords": get_top_keywords(domain),
        "top_pages": get_top_pages(domain),
        "top_directories": get_top_directories(domain),
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


def _extract_json_from_response(text: str) -> Optional[dict]:
    """LLM応答からJSON部分を抽出。コードブロック対応。"""
    # ```json ... ``` ブロック
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 単独JSON
    m = re.search(r"(\{[\s\S]*\})", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return None


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
    },
    "required": ["issues", "passed"],
}

ANALYSIS_TOOL = {
    "name": "submit_seo_analysis",
    "description": (
        "SEO セカンドオピニオン分析の構造化結果を提出する。"
        "5軸 (内部SEO・テクニカル / 外部SEO・サイテーション / コンテンツSEO・記事 / EEAT・広報 / AI露出) で 20点満点ずつ採点し、"
        "課題項目と通過項目を分けて格納する。"
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
            "axes": {
                "type": "object",
                "properties": {
                    "internal_seo": _AXIS_SCHEMA,
                    "external_seo": _AXIS_SCHEMA,
                    "content_seo": _AXIS_SCHEMA,
                    "eeat": _AXIS_SCHEMA,
                    "ai_exposure": _AXIS_SCHEMA,
                },
                "required": ["internal_seo", "external_seo", "content_seo", "eeat", "ai_exposure"],
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
        "required": ["summary", "axes", "contradictions", "donts", "sources"],
    },
}


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
            "internal_seo": {"issues": [], "passed": []},
            "external_seo": {"issues": [], "passed": []},
            "content_seo": {"issues": [], "passed": []},
            "eeat": {"issues": [], "passed": []},
            "ai_exposure": {"issues": [], "passed": []},
        },
        "ahrefs": empty_ahrefs,
        "contradictions": [],
        "donts": [],
        "sources": [],
        "error": error,
    }


def analyze_site_structured(
    url: str,
    url_match_mode: str = "完全一致",
) -> dict:
    """Mode A の構造化版。Anthropic Tool Use で JSON を保証。"""
    if is_mock_mode():
        return _build_mock_structured(url)

    client = get_client()
    ahrefs_data = _gather_ahrefs_data(url)
    page_meta = _fetch_page_meta(url)

    if client is None:
        return _build_empty_structured(url, ahrefs_data, page_meta, error="ANTHROPIC_API_KEY 未設定")

    user_message = f"""モード: A (サイト分析・構造化出力モード)
対象URL: {url}
URL一致モード: {url_match_mode}

ページメタ情報 (HTML から自動抽出):
{json.dumps(page_meta, ensure_ascii=False, indent=2)}

Ahrefs データ (Site Explorer):
{json.dumps(ahrefs_data, ensure_ascii=False, indent=2)}

要求:
- 5軸ごとに issues (指摘事項) と passed (通過項目) を埋める
- score = ((total - issues件数) / total) * 20 で四捨五入
- evidence は最低1件、url 必須。ラベルは「公式」「QRG」「リーク」「訴訟」「VRP」「特許」「二次解説」「Googler発言」のいずれか
- check_url は対象ドメイン配下の実在URL (与えられた URL のドメインを使う)
- contradictions は対象サイトに関連するもの2-3件
- donts は対象サイトに該当しそうな都市伝説的施策 3-5件
- sources は出典リスト 6-10件
- 推測の評価は priority "低" とし、observation_sub に「推測扱い」と書く

提出は submit_seo_analysis ツールを使うこと (必須)。"""

    try:
        response = client.messages.create(
            model=get_model(),
            max_tokens=16000,  # 大きなレスポンスに対応 (出力切れを防止)
            system=SYSTEM_PROMPT,
            tools=[ANALYSIS_TOOL],
            tool_choice={"type": "tool", "name": "submit_seo_analysis"},
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        logger.error(f"Anthropic API error: {e}")
        return _build_empty_structured(url, ahrefs_data, page_meta, error=f"Anthropic API エラー: {str(e)[:200]}")

    # stop_reason を取得 (max_tokens 切れ検出用)
    stop_reason = getattr(response, "stop_reason", "")
    logger.info(f"Anthropic response stop_reason={stop_reason}, blocks={[getattr(b, 'type', '?') for b in response.content]}")

    # tool_use ブロックを抽出
    parsed = None
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_seo_analysis":
            parsed = block.input
            break

    if parsed is None:
        logger.warning(f"LLM did not call submit_seo_analysis tool. stop_reason={stop_reason}")
        return _build_empty_structured(url, ahrefs_data, page_meta, error=f"LLMがツール呼び出しを行わなかった (stop_reason={stop_reason})")

    # スキーマ検証 (必須キー確認)
    if not isinstance(parsed, dict) or "summary" not in parsed or "axes" not in parsed:
        keys_str = list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__
        logger.warning(f"LLM tool input missing required keys: keys={keys_str}, stop_reason={stop_reason}")
        if stop_reason == "max_tokens":
            err_msg = f"LLM応答が max_tokens で切れました (含まれるキー: {keys_str})。max_tokens を増やすか、対象URLを単純化してください。"
        else:
            err_msg = f"LLM応答に必須フィールド (summary/axes) が含まれていません (stop_reason={stop_reason}, 含まれるキー: {keys_str})"
        return _build_empty_structured(url, ahrefs_data, page_meta, error=err_msg)

    # summary が dict でない場合 (string で返してきたケース)
    if not isinstance(parsed.get("summary"), dict):
        logger.warning(f"LLM returned summary as {type(parsed.get('summary')).__name__}, not dict")
        return _build_empty_structured(
            url, ahrefs_data, page_meta,
            error=f"LLM応答の summary が dict でなく {type(parsed.get('summary')).__name__} で返されました"
        )

    # axes が dict でない場合
    if not isinstance(parsed.get("axes"), dict):
        logger.warning(f"LLM returned axes as {type(parsed.get('axes')).__name__}, not dict")
        return _build_empty_structured(
            url, ahrefs_data, page_meta,
            error=f"LLM応答の axes が dict でなく {type(parsed.get('axes')).__name__} で返されました"
        )

    # 任意フィールドのデフォルト補完 (空配列で安全に表示できるように)
    parsed.setdefault("contradictions", [])
    parsed.setdefault("donts", [])
    parsed.setdefault("sources", [])
    if "axes" in parsed and isinstance(parsed["axes"], dict):
        for k in ["internal_seo", "external_seo", "content_seo", "eeat", "ai_exposure"]:
            parsed["axes"].setdefault(k, {"issues": [], "passed": []})
            parsed["axes"][k].setdefault("issues", [])
            parsed["axes"][k].setdefault("passed", [])

    # ahrefs / page_meta / target_url を注入
    parsed["ahrefs"] = ahrefs_data
    parsed["url_meta"] = page_meta
    parsed["target_url"] = url
    return parsed


def analyze_site(
    url: str,
    url_match_mode: str = "完全一致",
    ahrefs_data: Optional[dict] = None,
    references: Optional[list] = None,
) -> str:
    """Mode A: サイト分析。

    Args:
        url: 対象URL
        url_match_mode: URL一致モード
        ahrefs_data: Ahrefs データ (None の場合は ahrefs_client から自動取得)
        references: 参照する資料のリスト

    Returns:
        Markdown 形式の分析レポート文字列
    """
    if is_mock_mode():
        return _mock_analyze_response(url)

    client = get_client()
    if client is None:
        return "❌ ANTHROPIC_API_KEY が設定されていません。.env を確認してください。"

    # Ahrefs データを自動取得 (mockモード時はダミーデータ、トークン設定時は実データ)
    if ahrefs_data is None:
        ahrefs_data = _gather_ahrefs_data(url)

    user_message = f"""モード: A (サイト分析)
対象URL: {url}
URL一致モード: {url_match_mode}

事前収集データ (Ahrefs):
{json.dumps(ahrefs_data, ensure_ascii=False, indent=2)}

参照する資料: {', '.join(references) if references else '全て'}

要求:
- 5軸 (内部SEO・テクニカル / 外部SEO・サイテーション / コンテンツSEO・記事 / EEAT・広報 / AI露出 LLMO・AI引用) で 20点満点 × 5 = 100点でスコア化
- 各課題項目には確認URL (実際にチェックしたページ) を添える
- 通過項目 (問題のなかった項目) も同じく確認URL付きで列挙
- エビデンスにはクリック可能なソースURLを必ず添える
- 優先度は 高 / 中 / 低 の3段階のみ
- サイトデータセクションは上記の「事前収集データ (Ahrefs)」を必ず使う。データが含まれているなら「(未取得)」と書かない
- 出力は WebUI 表示用の Markdown 形式で、3タブ構造 (課題サマリ / サイトデータ / 参考) に対応するセクション分けで返す

サイト分析を実行してください。"""

    response = client.messages.create(
        model=get_model(),
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


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
        system=SYSTEM_PROMPT,
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
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


# ─── Structured mock data (UI binding 用) ────────────────────

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
        "ahrefs": _gather_ahrefs_data(url),
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

def _mock_analyze_response(url: str) -> str:
    """ダミーの分析結果 (UI開発用)。"""
    return f"""# SEO セカンドオピニオン: {url}

## 総合スコア: 71/100

- 内部SEO・テクニカル: 16/20 (3件 / 17項目)
- 外部SEO・サイテーション: 14/20 (2件 / 7項目)
- コンテンツSEO・記事: 15/20 (5件 / 21項目)
- EEAT・広報: 11/20 (6件 / 14項目)
- AI露出 (LLMO・AI引用): 15/20 (2件 / 8項目)

## サマリー
- **強み**: 独自の現場データに基づく記述が部分的に存在 / 内部リンク設計はトピックハブを形成しつつある
- **懸念**: 著者プロフィール欠落により siteAuthority の伸びが阻害 / OriginalContentScore を押し下げる重複コンテンツが3記事
- **施策案**: 著者プロフィールの構造化と組織情報の整備 (EEAT軸 / 優先度 高)

⚠️ これは APP_MODE=mock で表示されているダミーデータです。実データを取得するには .env で ANTHROPIC_API_KEY を設定し APP_MODE=live に変更してください。
"""


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
