"""
SEO セカンドオピニオン Anthropic API ラッパー。

Mode A (サイト分析) / Mode B (施策レビュー) / Mode C (個別質問) の3モードに対応。
APP_MODE=mock の場合は実APIを呼ばずダミーデータを返す。
"""

import os
import json
from typing import Optional
from urllib.parse import urlparse
from anthropic import Anthropic
from agent_system_prompt import SYSTEM_PROMPT
from ahrefs_client import (
    get_site_metrics,
    get_top_keywords,
    get_top_pages,
    get_top_directories,
)


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
