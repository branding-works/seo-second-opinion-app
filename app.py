"""
SEO セカンドオピニオン WebUI (Streamlit版)

Branding Works (https://www.branding-works.jp/) のためのSEO診断ツール。
モックアップ HTML と同じUIを Streamlit で実装。

実行: streamlit run app.py
"""

import time
from datetime import datetime

import streamlit as st
import plotly.graph_objects as go
from dotenv import load_dotenv

from seo_analyzer import analyze_site, review_strategy, answer_question, is_mock_mode
from ahrefs_client import (
    get_site_metrics,
    get_top_keywords,
    get_top_pages,
    get_top_directories,
)

# .env 読み込み
load_dotenv()


# ─── ページ設定 ────────────────────────────────────────
st.set_page_config(
    page_title="SEO セカンドオピニオン",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─── カスタム CSS (BWブランディング) ────────────────────
st.markdown(
    """
<style>
:root {
  --bw-green: #1cb57b;
  --bw-green-dark: #4A9529;
  --bw-bg: #f5f3ee;
  --bw-card: #ffffff;
  --bw-border: #e5e5e0;
  --bw-text: #1a1a1a;
  --bw-text-secondary: #6b6b6b;
}

/* 全体背景 */
.stApp { background: var(--bw-bg); }
section[data-testid="stSidebar"] { background: #fff; }

/* Streamlit のデフォルトヘッダーを隠す */
header[data-testid="stHeader"] { display: none; }
.stDeployButton { display: none; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }

/* カスタムヘッダー */
.bw-header {
    background: var(--bw-green);
    color: white;
    padding: 0.65rem 1.5rem;
    margin: -4rem -3rem 1.5rem -3rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--bw-green-dark);
}
.bw-header-title {
    font-size: 1.15rem;
    font-weight: 700;
    letter-spacing: 0.01em;
    margin: 0;
}
.bw-header a {
    color: rgba(255,255,255,0.95);
    text-decoration: none;
    font-size: 0.78rem;
    font-weight: 600;
    border-bottom: 1px solid rgba(255,255,255,0.4);
}
.bw-header a:hover { border-bottom-color: white; }

/* 課題スコア */
.score-total-block {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    padding: 1rem 1.4rem;
    background: white;
    border: 1px solid var(--bw-border);
    border-radius: 8px;
    margin-bottom: 1rem;
}
.score-total-label {
    font-size: 0.7rem;
    font-weight: 700;
    color: var(--bw-text-secondary);
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-right: 0.5rem;
}
.score-total-value {
    font-size: 2.6rem;
    font-weight: 700;
    line-height: 1;
    color: #0f1729;
    font-feature-settings: "tnum";
}
.score-total-max {
    font-size: 1rem;
    color: var(--bw-text-secondary);
    font-weight: 600;
}
.score-total-rating {
    margin-left: auto;
    font-size: 0.78rem;
    font-weight: 700;
    padding: 0.25rem 0.7rem;
    border-radius: 999px;
    background: #fef3c7;
    color: #92400e;
}

/* スコア行 */
.score-row {
    margin-bottom: 0.7rem;
}
.score-row-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 0.25rem;
}
.score-name {
    font-weight: 600;
    color: var(--bw-text);
    font-size: 0.85rem;
}
.score-value {
    font-feature-settings: "tnum";
    font-family: "SF Mono", "Consolas", monospace;
    font-size: 0.78rem;
    font-weight: 700;
    color: #0f1729;
}
.score-bar-bg {
    height: 9px;
    background: #f3f0e8;
    border-radius: 4px;
    overflow: hidden;
    position: relative;
}
.score-bar-bg::after {
    content: "";
    position: absolute;
    inset: 0;
    pointer-events: none;
    background-image:
      linear-gradient(90deg, transparent calc(25% - 0.5px), rgba(0,0,0,0.28) calc(25% - 0.5px), rgba(0,0,0,0.28) calc(25% + 0.5px), transparent calc(25% + 0.5px)),
      linear-gradient(90deg, transparent calc(50% - 0.5px), rgba(0,0,0,0.28) calc(50% - 0.5px), rgba(0,0,0,0.28) calc(50% + 0.5px), transparent calc(50% + 0.5px)),
      linear-gradient(90deg, transparent calc(75% - 0.5px), rgba(0,0,0,0.28) calc(75% - 0.5px), rgba(0,0,0,0.28) calc(75% + 0.5px), transparent calc(75% + 0.5px));
}
.score-bar-fill {
    height: 100%;
    background: var(--bw-green);
    border-radius: 4px;
}
.score-bar-fill.warn { background: #d97706; }

/* ボタン */
.stButton > button {
    background: #0f1729;
    color: white;
    border: none;
    font-weight: 700;
    border-radius: 4px;
    transition: background 0.15s;
}
.stButton > button:hover { background: var(--bw-green); color: white; }

/* テキストエリア */
.stTextArea textarea {
    background: #fafaf8;
    border: 1.5px solid #d4d4cf;
    border-radius: 6px;
}
.stTextArea textarea:focus {
    border-color: var(--bw-green);
    background: white;
}

/* タブ */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    border-bottom: 2px solid var(--bw-border);
}
.stTabs [data-baseweb="tab"] {
    padding: 0.85rem 1.5rem;
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--bw-text-secondary);
}
.stTabs [aria-selected="true"] {
    color: var(--bw-green);
    border-bottom: 3px solid var(--bw-green);
    font-weight: 700;
}

/* メトリックカード */
.kpi-card {
    background: #f9f7f0;
    border: 1px solid #f0eee8;
    border-radius: 6px;
    padding: 0.85rem 1rem;
}
.kpi-label {
    font-size: 0.66rem;
    color: var(--bw-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 700;
    margin-bottom: 0.3rem;
}
.kpi-value {
    font-size: 1.55rem;
    font-weight: 700;
    font-feature-settings: "tnum";
    color: #0f1729;
}
.kpi-sub {
    font-size: 0.7rem;
    color: var(--bw-text-secondary);
    margin-top: 0.2rem;
}

/* チャットメッセージ */
.chat-msg {
    display: grid;
    grid-template-columns: 36px 1fr;
    gap: 0.85rem;
    margin-bottom: 1.5rem;
}
.chat-avatar {
    width: 36px;
    height: 36px;
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 0.78rem;
}
.chat-avatar-user { background: #f3f0e8; color: #1a1a1a; }
.chat-avatar-ai { background: var(--bw-green); color: white; }
.chat-name { font-weight: 700; font-size: 0.85rem; }
.chat-time { font-size: 0.7rem; color: #9ca3af; margin-left: 0.5rem; }
.chat-content { font-size: 0.88rem; line-height: 1.7; margin-top: 0.45rem; }

.mock-banner {
    background: #fef3c7;
    color: #78350f;
    padding: 0.65rem 1rem;
    border-radius: 6px;
    border: 1px solid #fde68a;
    font-size: 0.85rem;
    margin-bottom: 1rem;
}
</style>
""",
    unsafe_allow_html=True,
)


# ─── ヘッダー ───────────────────────────────────────────
st.markdown(
    """
<div class="bw-header">
    <span class="bw-header-title">SEO セカンドオピニオン</span>
    <a href="https://www.branding-works.jp/" target="_blank" rel="noopener">株式会社ブランディングワークス</a>
</div>
""",
    unsafe_allow_html=True,
)


# ─── サイドバー (左パネル) ──────────────────────────────
with st.sidebar:
    st.markdown("**分析モード**")
    mode = st.radio(
        "モード",
        ["サイト分析", "施策レビュー", "個別質問"],
        label_visibility="collapsed",
        key="mode",
    )

    st.divider()

    if mode == "サイト分析":
        st.markdown("**対象URL**")
        url = st.text_input(
            "URL",
            value="https://example.co.jp/blog/seo-guide",
            label_visibility="collapsed",
            key="target_url",
        )
        url_match = st.radio(
            "URL一致モード",
            ["完全一致", "部分一致", "ドメイン一致", "サブドメイン含む"],
            label_visibility="collapsed",
            horizontal=True,
            key="url_match",
        )
    elif mode == "施策レビュー":
        st.markdown("**レビューする施策を入力**")
        review_text = st.text_area(
            "施策案",
            height=220,
            label_visibility="collapsed",
            placeholder="例:\n1. サイト全体に FAQPage schema を追加\n2. 月20本ペースで新規記事を投入\n3. 過去記事の更新日を一括書き換え\n4. EMD ドメインを新規取得",
            key="review_text",
        )
        related_url = st.text_input(
            "関連URL (任意)",
            placeholder="https://example.co.jp/",
            key="related_url",
        )
    else:  # 個別質問
        st.markdown("**質問内容を入力**")
        question_text = st.text_area(
            "質問",
            height=180,
            label_visibility="collapsed",
            placeholder="例: Google はドメインオーソリティをランキング要因として使っていないと公式に言っているが、これは本当ですか?",
            key="question_text",
        )

    st.divider()

    with st.expander("追加データ", expanded=False):
        st.checkbox("Ahrefs MCPでサイト指標取得", value=True, key="use_ahrefs")
        st.checkbox("Web上でエビデンス検証", value=True, key="use_web")
        st.checkbox("GSCデータ連携", value=False, key="use_gsc")
        st.checkbox("GA4 organic連携", value=False, key="use_ga4")

    with st.expander("参照する資料", expanded=False):
        st.checkbox("Google特許", value=True)
        st.checkbox("2024-05 リーク資料", value=True)
        st.checkbox("DOJ訴訟資料", value=True)
        st.checkbox("品質評価ガイドライン (QRG)", value=True)
        st.checkbox("Mark Williams-Cook (VRP)", value=True)
        st.checkbox("Search Central Blog", value=True)
        st.checkbox("Search Central ドキュメント", value=True)
        st.checkbox("Search Central サポート", value=True)

    button_label = {
        "サイト分析": "分析を実行",
        "施策レビュー": "評価する",
        "個別質問": "質問する",
    }[mode]
    run_btn = st.button(button_label, type="primary", use_container_width=True)


# ─── メイン領域: モード別コンテンツ ─────────────────────

# モック警告
if is_mock_mode():
    st.markdown(
        """<div class="mock-banner">
        ⚠️ <strong>APP_MODE=mock</strong> で動作中です。実データを取得するには .env で <code>ANTHROPIC_API_KEY</code> を設定し <code>APP_MODE=live</code> に変更してください。
        </div>""",
        unsafe_allow_html=True,
    )


# ─── 共通: スコア配分(モックデータ) ──────────────────
DEFAULT_SCORES = {
    "内部SEO・テクニカル": (16, 17, 3),
    "外部SEO・サイテーション": (14, 7, 2),
    "コンテンツSEO・記事": (15, 21, 5),
    "EEAT・広報": (11, 14, 6),
    "AI露出 (LLMO・AI引用)": (15, 8, 2),
}


def render_radar_chart(scores: dict) -> go.Figure:
    """5軸レーダーチャート (Plotly)。"""
    short_names = {
        "内部SEO・テクニカル": "内部SEO",
        "外部SEO・サイテーション": "外部SEO",
        "コンテンツSEO・記事": "コンテンツSEO",
        "EEAT・広報": "EEAT・広報",
        "AI露出 (LLMO・AI引用)": "AI露出",
    }
    categories = [short_names[k] for k in scores.keys()]
    values = [v[0] for v in scores.values()]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=values + [values[0]],
            theta=categories + [categories[0]],
            fill="toself",
            fillcolor="rgba(28, 181, 123, 0.18)",
            line=dict(color="#1cb57b", width=2),
            marker=dict(size=10, color="#1cb57b", line=dict(color="white", width=2)),
            hovertemplate="%{theta}: %{r}/20<extra></extra>",
        )
    )
    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 20],
                tickvals=[5, 10, 15, 20],
                tickfont=dict(size=9, color="#c4c4bf"),
                gridcolor="#e5e5e0",
            ),
            angularaxis=dict(
                tickfont=dict(size=11, color="#1a1a1a"),
                gridcolor="#e5e5e0",
            ),
            bgcolor="white",
        ),
        showlegend=False,
        margin=dict(l=60, r=60, t=40, b=40),
        height=380,
        paper_bgcolor="white",
    )
    return fig


def render_score_bars(scores: dict):
    """スコアバー (HTML)。"""
    rows_html = ""
    for name, (score, total_checks, _) in scores.items():
        pct = (score / 20) * 100
        bar_class = "warn" if pct < 60 else ""
        rows_html += f"""
        <div class="score-row">
            <div class="score-row-header">
                <span class="score-name">{name}</span>
                <span class="score-value">{score}/20</span>
            </div>
            <div class="score-bar-bg">
                <div class="score-bar-fill {bar_class}" style="width: {pct}%;"></div>
            </div>
        </div>
        """
    st.markdown(rows_html, unsafe_allow_html=True)


# ─── Mode A: サイト分析 ─────────────────────────────────
if mode == "サイト分析":
    # 課題スコア + レーダー
    total_score = sum(v[0] for v in DEFAULT_SCORES.values())

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.markdown(
            f"""
        <div class="score-total-block">
            <span class="score-total-label">総合スコア</span>
            <span class="score-total-value">{total_score}</span>
            <span class="score-total-max">/ 100</span>
            <span class="score-total-rating">課題スコア</span>
        </div>
        """,
            unsafe_allow_html=True,
        )

        sub_left, sub_right = st.columns([1, 1])
        with sub_left:
            st.plotly_chart(render_radar_chart(DEFAULT_SCORES), use_container_width=True, config={"displayModeBar": False})
        with sub_right:
            render_score_bars(DEFAULT_SCORES)

    with col_right:
        st.markdown("**調査URLメタ情報**")
        st.markdown(
            f"""
| 項目 | 値 |
|---|---|
| Title | SEO 内部対策の完全ガイド \\| example.co.jp |
| Meta-desc | SEO 内部対策のベストプラクティスを、Google公式情報とリーク資料を踏まえて解説 |
| インデックス | ✓ 登録済み (canonical: self) |
| 構造化データ | `Article` `BreadcrumbList` `Organization` |
| 対象URL | [{st.session_state.get('target_url', '')}]({st.session_state.get('target_url', '')}) |
        """,
            unsafe_allow_html=False,
        )

    # サマリー
    st.markdown("### サマリー")
    sum_col1, sum_col2, sum_col3 = st.columns(3)
    with sum_col1:
        st.markdown("**強み**")
        st.markdown("独自の現場データに基づく記述が部分的に存在 / 内部リンク設計はトピックハブを形成しつつある")
    with sum_col2:
        st.markdown("**懸念**")
        st.markdown("著者プロフィール欠落により `siteAuthority` の伸びが阻害 / `OriginalContentScore` を押し下げる重複コンテンツが3記事")
    with sum_col3:
        st.markdown("**施策案**")
        st.markdown("著者プロフィールの構造化と組織情報の整備 (EEAT軸 / 優先度 高)")

    st.divider()

    # 3タブ
    tab1, tab2, tab3 = st.tabs(["課題サマリ", "サイトデータ", "参考"])

    with tab1:
        st.markdown("**課題可能性** _(発見数 / 全チェック項目数)_")

        axis_tabs = st.tabs([
            f"内部SEO・テクニカル 3/17",
            f"外部SEO・サイテーション 2/7",
            f"コンテンツSEO・記事 5/21",
            f"EEAT・広報 6/14",
            f"AI露出 (LLMO・AI引用) 2/8",
        ])

        # 各軸の指摘事項テーブル (モックデータ)
        with axis_tabs[0]:
            st.markdown("#### 指摘事項")
            st.markdown(
                """
| 観点 | 施策 | エビデンス | 確認URL | 優先度 |
|---|---|---|---|---|
| ページ表示速度 (PageSpeed モバイル48点) | 画像のWebP化、render-blocking JS の defer | [公式](https://web.dev/articles/vitals) [リーク](https://hexdocs.pm/google_api_content_warehouse/0.4.0/api-reference.html) | [/blog/seo-guide](https://example.co.jp/blog/seo-guide) | 高 |
| パンくずリスト未設置 | BreadcrumbList schema を全記事に実装 | [公式](https://developers.google.com/search/docs/appearance/structured-data/breadcrumb) [リーク](https://hexdocs.pm/google_api_content_warehouse/0.4.0/api-reference.html) | [/blog/seo-guide](https://example.co.jp/blog/seo-guide) | 中 |
| alt属性の不備 (画像30%未設定) | CMS 側で alt 必須バリデーション | [公式](https://developers.google.com/search/docs/appearance/google-images) | [/blog/structured-data](https://example.co.jp/blog/structured-data) | 中 |
            """
            )
            st.markdown("#### ✓ 問題のなかった項目 (14件)")
            st.markdown(
                """
- ✓ URL正規化 (HTTPS対応済み)
- ✓ リンク切れなし
- ✓ sitemap.xml 設置・送信済み
- ✓ robots.txt 適切
- ✓ 内部リンク 絶対パス記載
- ✓ 主要ページからの導線設置
- ✓ CSS-Positioning なし
- ✓ モバイル ユーザビリティOK
- ✓ モバイルアノテーション設定
- ✓ MFI 対応
- ✓ カスタム404 設置
- ✓ サイトマップページ
- ✓ Search Console 登録
- ✓ GA4 設定
            """
            )

        with axis_tabs[1]:
            st.markdown("#### 指摘事項")
            st.markdown(
                """
| 観点 | 施策 | エビデンス | 確認URL | 優先度 |
|---|---|---|---|---|
| 外部発リンクの関連性 (5件検出) | 関連性低リンクに `nofollow` 付加 | [QRG](https://services.google.com/fh/files/misc/hsw-sqrg.pdf) [リーク](https://hexdocs.pm/google_api_content_warehouse/0.4.0/api-reference.html) | [/blog/inp-optimization](https://example.co.jp/blog/inp-optimization) | 中 |
| Google ビジネスプロフィール 未設定 | GBP登録、NAP整備 | [公式](https://support.google.com/business/) | [Google Maps](https://www.google.com/maps) | 低 |
            """
            )
            st.markdown("#### ✓ 問題のなかった項目 (5件)")
            st.markdown(
                """
- ✓ アンカーテキスト最適化
- ✓ 中古ドメイン使用なし
- ✓ サイトレピュテーション健全
- ✓ 外部リンクのアンカー多様性
- ✓ サイテーション / ブランド言及あり
            """
            )

        with axis_tabs[2]:
            st.markdown("#### 指摘事項")
            st.markdown(
                """
| 観点 | 施策 | エビデンス | 確認URL | 優先度 |
|---|---|---|---|---|
| `<title>`タグ対策KW不足 (10ページ) | title に「対策KW + サービス名」 | [リーク](https://hexdocs.pm/google_api_content_warehouse/0.4.0/api-reference.html) [公式](https://developers.google.com/search/docs/appearance/title-link) | [/service/](https://example.co.jp/service/) | 高 |
| メインコンテンツ情報不足 (5ページ idx除外) | 独自視点・一次情報を追加 | [リーク](https://hexdocs.pm/google_api_content_warehouse/0.4.0/api-reference.html) [QRG](https://services.google.com/fh/files/misc/hsw-sqrg.pdf) | [/blog/sitemap-xml](https://example.co.jp/blog/sitemap-xml) | 高 |
| 重複コンテンツ (類似度高い記事3件) | canonical設定 or 統合 | [リーク](https://hexdocs.pm/google_api_content_warehouse/0.4.0/api-reference.html) | [/blog/inp-optimization](https://example.co.jp/blog/inp-optimization) | 中 |
| `<h1>`タグ不適切 (複数h1ページ4件) | h1を1ページ1つに統一 | [公式](https://developers.google.com/style/headings) | [/about/](https://example.co.jp/about/) | 中 |
| meta-description重複 (8ページ) | 各ページ独自の description 作成 | [公式](https://developers.google.com/search/docs/appearance/snippet) | [/blog/structured-data](https://example.co.jp/blog/structured-data) | 低 |
            """
            )
            st.markdown("#### ✓ 問題のなかった項目 (16件)")
            st.markdown(
                "title重複なし / hx階層適切 / コンテンツボリューム適正 / 自動生成テキストなし / コピーテキストなし / 大量定型文なし / 類似コンテンツなし / 重複URLなし / ナビゲーションリンク整備 / サブコンテンツ適正 ほか"
            )

        with axis_tabs[3]:
            st.markdown("#### 指摘事項")
            st.markdown(
                """
| 観点 | 施策 | エビデンス | 確認URL | 優先度 |
|---|---|---|---|---|
| 著者プロフィール (記事ごとの著者明示なし) | 記事末尾に Person schema 付きで配置 | [QRG](https://services.google.com/fh/files/misc/hsw-sqrg.pdf) [リーク×2](https://hexdocs.pm/google_api_content_warehouse/0.4.0/api-reference.html) | [/blog/seo-guide](https://example.co.jp/blog/seo-guide) | 高 |
| 組織情報 (会社概要が薄手) | Organization schema追加 | [QRG](https://services.google.com/fh/files/misc/hsw-sqrg.pdf) [公式](https://blog.google/products/search/about-search-results/) | [/about/](https://example.co.jp/about/) | 高 |
| ブランド指名検索 (月間200 → 目標1,000+) | 展示会・PR配信で社名露出 | [VRP](https://www.candour.co.uk/blog/google-search-leak/) [リーク](https://hexdocs.pm/google_api_content_warehouse/0.4.0/api-reference.html) | [/](https://example.co.jp/) | 高 |
| 第三者言及 (権威媒体露出ゼロ) | 業界トップ3媒体に寄稿/取材獲得 | [QRG](https://services.google.com/fh/files/misc/hsw-sqrg.pdf) [訴訟資料](https://www.justice.gov/atr/case/us-and-plaintiff-states-v-google-llc-search) | [/](https://example.co.jp/) | 中 |
| Wikipedia/Wikidata (エントリ未作成) | Wikidata エンティティ作成 | [特許](https://patents.google.com/patent/US8396865B1) [推測] | [Wikidata](https://www.wikidata.org/) | 中 |
| 受賞・認証 (記載なし) | 受賞・認証あれば組織ページに明示 | [QRG](https://services.google.com/fh/files/misc/hsw-sqrg.pdf) | [/about/](https://example.co.jp/about/) | 低 |
            """
            )
            st.markdown("#### ✓ 問題のなかった項目 (8件)")
            st.markdown(
                "HTTPS / プライバシーポリシー / 運営会社情報整備 / お問い合わせフォーム / 著者ページ存在 / 引用・出典記載 / 記事更新日記載 / 専門用語の用語集"
            )

        with axis_tabs[4]:
            st.markdown("#### 指摘事項")
            st.markdown(
                """
| 観点 | 施策 | エビデンス | 確認URL | 優先度 |
|---|---|---|---|---|
| llms.txt 未設置 | サイトルートに llms.txt 配置 | [二次解説](https://llmstxt.org/) | [/llms.txt](https://example.co.jp/llms.txt) | 低 |
| AI Overviews への引用ゼロ | パッセージ最適化、Q&A形式 | [公式](https://blog.google/products/search/ai-overviews-update-may-2024/) [二次解説](https://ipullrank.com/the-rank-revolution-by-mike-king) | [SERP例](https://www.google.com/search?q=SEO+%E5%86%85%E9%83%A8%E5%AF%BE%E7%AD%96&udm=14) | 中 |
            """
            )
            st.markdown("#### ✓ 問題のなかった項目 (6件)")
            st.markdown(
                "Article schema設置 / robots.txt AIクローラー許可 / パッセージ構造良好 / 一次情報・独自データ記載 / 質問形式の見出し使用 / 用語集・FAQ整備"
            )

        st.divider()
        st.markdown("### 実施にあたって要検討施策")
        st.warning(
            """
- **架空の著者プロフィールを生成** — QRGは実体験を重視。Lowest 品質判定の対象 [QRG]
- **EMD (完全一致ドメイン) を新規取得** — `ExactMatchDomainDemotion` 属性が存在 [リーク]
- **FAQスキーマを通常コンテンツに追加** — 2023-08以降、政府・医療以外ではリッチリザルトに表示されない [公式]
- **記事の更新日のみ書き換える** — `bylineDate` と `semanticDate` を比較する仕組みあり、内容を変えない更新は逆効果 [リーク]
- **HowToスキーマの追加** — 2023-09に大半のクエリで廃止済み [公式]
        """
        )

    with tab2:
        st.markdown("#### Ahrefs サイト指標")
        st.caption("出典: Ahrefs Site Explorer / 2026-04-27時点 (mock)")

        metrics = get_site_metrics("example.co.jp")
        kc1, kc2, kc3, kc4 = st.columns(4)
        with kc1:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">Domain Rating</div><div class="kpi-value">{metrics["domain_rating"]}<span style="font-size:0.78rem;color:#6b6b6b;margin-left:0.2rem;">/100</span></div><div class="kpi-sub">前月比 +1</div></div>',
                unsafe_allow_html=True,
            )
        with kc2:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">月間自然検索セッション</div><div class="kpi-value">{metrics["monthly_organic_sessions"]:,}</div><div class="kpi-sub">直近30日</div></div>',
                unsafe_allow_html=True,
            )
        with kc3:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">被リンク元ドメイン (全体)</div><div class="kpi-value">{metrics["referring_domains_total"]}</div><div class="kpi-sub">RD 全カウント</div></div>',
                unsafe_allow_html=True,
            )
        with kc4:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">被リンク元ドメイン (価値あり)</div><div class="kpi-value">{metrics["referring_domains_quality"]}</div><div class="kpi-sub">dofollow / 非スパム</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown("")
        st.info(f"**{metrics['organic_pages_count']}** ページが自然検索流入を獲得中 (Ahrefs 上位ページ)")

        st.markdown("#### 流入貢献KW 上位10")
        kw_data = get_top_keywords("example.co.jp")
        kw_table = "| KW | 月間 | 順位 | 獲得URL |\n|---|---|---|---|\n"
        for k in kw_data:
            kw_table += f"| {k['keyword']} | {k['volume']:,} | {k['position']} | [{k['url']}](https://example.co.jp{k['url']}) |\n"
        st.markdown(kw_table)

        st.markdown("#### 流入URL 上位10")
        page_data = get_top_pages("example.co.jp")
        page_table = "| URL | 推定セッション/月 |\n|---|---|\n"
        for p in page_data:
            page_table += f"| [{p['url']}](https://example.co.jp{p['url']}) | {p['estimated_sessions']:,} |\n"
        st.markdown(page_table)

        st.markdown("#### 記事ディレクトリ + サイト構成上位10")
        dir_data = get_top_directories("example.co.jp")
        dir_table = "| ディレクトリ | ページ数 | 月間流入 | シェア |\n|---|---|---|---|\n"
        for d in dir_data:
            dir_table += f"| [{d['directory']}](https://example.co.jp{d['directory']}) | {d['pages']} | {d['monthly_sessions']:,} | {d['share_pct']:.1f}% |\n"
        st.markdown(dir_table)

    with tab3:
        st.markdown("#### 参考: Google公式系情報より調査サイトに関連する項目")
        st.caption("公式発言を鵜呑みにしないこと。施策判断のときに必ず参照する。")
        st.markdown(
            """
| Googleの公式メッセージ | 内部実装の事実 | 裏付け資料 |
|---|---|---|
| Gary Illyes「ドメイン全体の権威スコアは存在しない」 | `siteAuthority` 属性が存在 | [リーク 2024-05](https://hexdocs.pm/google_api_content_warehouse/0.4.0/api-reference.html) |
| Gary Illyes「クリックは直接ランキングに使わない」 | NavBoost が13ヶ月のクリックデータを使用 | [訴訟資料](https://www.justice.gov/atr/case/us-and-plaintiff-states-v-google-llc-search) |
| 公式「EMD に特別な扱いはない」 | `ExactMatchDomainDemotion` 属性が存在 | [リーク 2024-05](https://hexdocs.pm/google_api_content_warehouse/0.4.0/api-reference.html) |
        """
        )

        st.markdown("#### 出典・参考資料")
        st.markdown(
            """
1. [品質評価ガイドライン (QRG) 2023-11版 p.26-33](https://services.google.com/fh/files/misc/hsw-sqrg.pdf) — Experience / About Us / Reputation Research
2. [Content Warehouse API leak (2024-05)](https://hexdocs.pm/google_api_content_warehouse/0.4.0/api-reference.html) — siteAuthority / pageEntityAuthor / ExactMatchDomainDemotion 等
3. [US v. Google LLC (Case 1:20-cv-03010)](https://www.justice.gov/atr/case/us-and-plaintiff-states-v-google-llc-search) — Pandu Nayak deposition (2023-10-18)
4. [Mark Williams-Cook via Google VRP (2024-12)](https://www.candour.co.uk/blog/google-search-leak/) — 指名検索とサイト品質スコアの関連
5. [US8396865B1](https://patents.google.com/patent/US8396865B1) — Sharing user-submitted data
6. [US9031929](https://patents.google.com/patent/US9031929) — Site quality score
7. [Search Central Blog "An update on rich results in Search" (2023-08-08)](https://developers.google.com/search/blog/2023/08/howto-faq-changes)
8. [Mike King (iPullRank) 2024-05-28](https://ipullrank.com/google-algo-leak)
        """
        )

    # 実行ボタン押下時 — ステータス表示付き
    if run_btn:
        st.markdown("---")
        with st.status("分析を実行中...", expanded=True) as status:
            st.write(f"📥 対象URL を取得中: `{url}`")
            time.sleep(0.4)
            st.write("🔍 Ahrefs サイト指標を取得中...")
            time.sleep(0.5)
            st.write("📊 流入KW・上位URL・ディレクトリを集計中...")
            time.sleep(0.4)
            st.write("🤖 Anthropic Opus 4.7 にリクエスト中...")
            if is_mock_mode():
                time.sleep(0.8)
                result = None
                status.update(label="✓ 分析完了 (mockモード)", state="complete", expanded=False)
            else:
                result = analyze_site(url, url_match)
                st.write("✏️  結果を整形中...")
                time.sleep(0.2)
                status.update(label="✓ 分析完了", state="complete", expanded=False)
        if result:
            st.markdown("### 🔄 リアルタイム分析結果")
            st.markdown(result)


# ─── Mode B: 施策レビュー ───────────────────────────────
elif mode == "施策レビュー":
    st.markdown("### 施策レビュー")
    st.caption(
        "既にお持ちの SEO 施策案を貼り付けてください。Google特許・公式情報・QRG・リーク資料・DOJ訴訟資料・VRP に照らして1つずつ評価し、機能する根拠 / 機能しない根拠 / より良い代替案を提示します。"
    )
    st.divider()

    # サンプル会話 (mock)
    st.markdown(
        """
<div class="chat-msg">
    <div class="chat-avatar chat-avatar-user">U</div>
    <div>
        <span class="chat-name">あなた</span><span class="chat-time">2026-04-27 10:32</span>
        <div class="chat-content">
            以下の施策を検討中です。評価をお願いします。
            <ol>
                <li>サイト全体に <code>FAQPage</code> schema を追加してリッチリザルト獲得を狙う</li>
                <li>競合上位記事の構成を参考に、月20本ペースで新規記事を投入</li>
                <li>過去記事の更新日を一括で「2026-04-27」に書き換えて鮮度シグナルを強化</li>
                <li>EMD(<code>seo-pro.jp</code>)を新規取得して関連サイトとして運用</li>
            </ol>
        </div>
    </div>
</div>
""",
        unsafe_allow_html=True,
    )

    if run_btn:
        review_input = st.session_state.get("review_text", "")
        related = st.session_state.get("related_url", "")
        if not review_input.strip():
            st.warning("施策案を入力してください")
        else:
            with st.status("施策レビューを実行中...", expanded=True) as status:
                st.write("📋 施策案を解析中...")
                time.sleep(0.3)
                st.write("🔍 各案を特許・公式情報・QRG・リーク資料に照らして評価中...")
                time.sleep(0.5)
                st.write("🤖 Anthropic Opus 4.7 にリクエスト中...")
                if is_mock_mode():
                    time.sleep(0.7)
                    result = review_strategy(review_input, related)
                    status.update(label="✓ 評価完了 (mockモード)", state="complete", expanded=False)
                else:
                    result = review_strategy(review_input, related)
                    st.write("✏️  結果を整形中...")
                    time.sleep(0.2)
                    status.update(label="✓ 評価完了", state="complete", expanded=False)
            st.markdown(
                f"""
<div class="chat-msg">
    <div class="chat-avatar chat-avatar-ai">SO</div>
    <div>
        <span class="chat-name">SEO セカンドオピニオン</span><span class="chat-time">{datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
    </div>
</div>
""",
                unsafe_allow_html=True,
            )
            st.markdown(result)


# ─── Mode C: 個別質問 ──────────────────────────────────
else:
    st.markdown("### 個別質問")
    st.caption(
        "SEO に関する単発の質問にエビデンス付きで回答します。Google公式が答えていない領域は推測ラベルを付けて明示し、根拠が弱い場合は「分からない」と言います。"
    )
    st.divider()

    st.markdown(
        """
<div class="chat-msg">
    <div class="chat-avatar chat-avatar-user">U</div>
    <div>
        <span class="chat-name">あなた</span><span class="chat-time">2026-04-27 11:08</span>
        <div class="chat-content">
            Google は「ドメインオーソリティはランキング要因として使っていない」と公式に言っていますが、これは本当ですか? 社内で論争になっています。
        </div>
    </div>
</div>
""",
        unsafe_allow_html=True,
    )

    if run_btn:
        q_input = st.session_state.get("question_text", "")
        if not q_input.strip():
            st.warning("質問を入力してください")
        else:
            with st.status("質問を解析中...", expanded=True) as status:
                st.write("❓ 質問を解析中...")
                time.sleep(0.3)
                st.write("📚 一次資料 (特許・公式・QRG・リーク・訴訟・VRP) を参照中...")
                time.sleep(0.4)
                st.write("🤖 Anthropic Opus 4.7 にリクエスト中...")
                if is_mock_mode():
                    time.sleep(0.7)
                    result = answer_question(q_input)
                    status.update(label="✓ 回答完了 (mockモード)", state="complete", expanded=False)
                else:
                    result = answer_question(q_input)
                    st.write("✏️  結果を整形中...")
                    time.sleep(0.2)
                    status.update(label="✓ 回答完了", state="complete", expanded=False)
            st.markdown(
                f"""
<div class="chat-msg">
    <div class="chat-avatar chat-avatar-ai">SO</div>
    <div>
        <span class="chat-name">SEO セカンドオピニオン</span><span class="chat-time">{datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
    </div>
</div>
""",
                unsafe_allow_html=True,
            )
            st.markdown(result)
