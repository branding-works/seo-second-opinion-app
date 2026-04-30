"""
SEO セカンドオピニオン WebUI (Streamlit版)

Branding Works (https://www.branding-works.jp/) のためのSEO診断ツール。
モックアップ HTML と同じUIを Streamlit で実装。

実行: streamlit run app.py
"""

import time
import threading
from datetime import datetime

import streamlit as st
import plotly.graph_objects as go
from dotenv import load_dotenv

from seo_analyzer import (
    analyze_site_structured,
    review_strategy,
    answer_question,
    is_mock_mode,
    _build_mock_structured,
)

import database as db
from admin_ui import (
    render_admin_login_sidebar,
    render_admin_dashboard,
)

# .env 読み込み
load_dotenv()


# DB 初期化 (プロセスにつき1回だけ。Streamlit再実行のたびに Neon 接続するのを防ぐ)
@st.cache_resource(show_spinner=False)
def _init_db_once() -> bool:
    try:
        db.init_db()
        return True
    except Exception:
        return False


_init_db_once()


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

/* サイドバーを常時展開状態に固定 (折りたたみ無効) */
[data-testid="stSidebarCollapseButton"] {
    display: none !important;
}
section[data-testid="stSidebar"] {
    min-width: 360px !important;
    max-width: 360px !important;
    transform: translateX(0) !important;
    visibility: visible !important;
    margin-left: 0 !important;
}
section[data-testid="stSidebar"][aria-expanded="false"] {
    transform: translateX(0) !important;
    margin-left: 0 !important;
}
/* 折りたたまれていた場合の展開ボタンは表示する (緊急避難用) */
[data-testid="collapsedControl"] {
    display: block !important;
}

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

/* テキスト入力 (対象URL等) */
.stTextInput > div > div > input,
.stTextInput input {
    background: #fafaf8 !important;
    border: 1.5px solid #d4d4cf !important;
    border-radius: 6px !important;
    padding: 0.55rem 0.75rem !important;
    transition: border-color 0.15s, background 0.15s;
}
.stTextInput > div > div > input:focus,
.stTextInput input:focus {
    border-color: var(--bw-green) !important;
    background: white !important;
    box-shadow: 0 0 0 2px rgba(28, 181, 123, 0.15);
}

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
        st.markdown("**調査対象URL入力**")
        url = st.text_input(
            "URL",
            placeholder="https://example.co.jp/blog/seo-guide",
            label_visibility="collapsed",
            key="target_url",
        )
        if not url:
            url = "https://example.co.jp/blog/seo-guide"
        url_match = st.radio(
            "URL一致モード",
            ["部分一致", "完全一致", "ドメイン一致", "サブドメイン含む"],
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

    # ─── 管理者ログイン (URL ?admin=secretkey-bw でのみ表示) ───
    render_admin_login_sidebar()


# ─── 管理者ダッシュボードを表示中ならここで短絡 ─────────
if st.session_state.get("is_admin") and st.session_state.get("show_admin_dashboard"):
    render_admin_dashboard()
    st.stop()


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
    """5軸レーダーチャート (Plotly)。LLM の表記揺れに耐性あり。"""
    short_names_map = {
        "内部SEO・テクニカル": "内部SEO",
        "外部SEO・サイテーション": "外部SEO",
        "コンテンツSEO・記事": "コンテンツSEO",
        "EEAT・広報": "EEAT",
        "AI露出 (LLMO・AI引用)": "AI露出",
        # LLM の別表記揺れに対応
        "AI露出 (LLMO)": "AI露出",
        "AI露出 (AI引用)": "AI露出",
        "AI露出": "AI露出",
    }
    def _shorten(name: str) -> str:
        if name in short_names_map:
            return short_names_map[name]
        # 括弧 / 中点で分割して先頭部分を返す
        for sep in ("(", " ", "・"):
            if sep in name:
                return name.split(sep)[0][:12]
        return name[:12]
    categories = [_shorten(k) for k in scores.keys()]
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


# ─── Mode A: サイト分析 (データドリブン) ───────────────────


def _scores_dict_from_data(data: dict) -> dict:
    """data["summary"]["axes"] を render_radar_chart / render_score_bars 用の dict に変換。"""
    out = {}
    for ax in data["summary"]["axes"]:
        out[ax["name"]] = (ax["score"], ax["total"], ax["issues"])
    return out


def _render_axis_content(axis_data: dict):
    """課題サマリタブ内・各軸の指摘事項+通過項目+確認不可項目を描画。"""
    issues = axis_data.get("issues", [])
    passed = axis_data.get("passed", [])
    unverifiable = axis_data.get("unverifiable", [])

    if issues:
        st.markdown("#### 指摘事項")
        table = "| 観点 | 施策 | エビデンス | 確認URL | 優先度 |\n|---|---|---|---|---|\n"
        for it in issues:
            if not isinstance(it, dict):
                table += f"| {it} | — | — | — | — |\n"
                continue
            obs = it.get("observation", "")
            sub = it.get("observation_sub", "")
            obs_full = f"{obs} ({sub})" if sub else obs
            ev_parts = []
            for e in it.get("evidence", []) or []:
                if isinstance(e, dict):
                    ev_parts.append(f"[{e.get('label','')}]({e.get('url','#')})")
                else:
                    ev_parts.append(str(e))
            ev = " ".join(ev_parts)
            check_url = it.get("check_url", "")
            # 確認URL は省略せずフル表示
            check_md = f"[{check_url}]({check_url})" if check_url else ""
            priority = it.get("priority", "")
            table += f"| {obs_full} | {it.get('action','')} | {ev} | {check_md} | {priority} |\n"
        st.markdown(table)
    else:
        st.success("✓ 課題なし")

    if passed:
        st.markdown(f"#### ✓ 問題のなかった項目 ({len(passed)}件)")
        items = []
        for p in passed:
            if not isinstance(p, dict):
                items.append(f"- ✓ {p}")
                continue
            name = p.get("name", "")
            url_p = p.get("url", "")
            if url_p:
                items.append(f"- ✓ {name} [↗]({url_p})")
            else:
                items.append(f"- ✓ {name}")
        st.markdown("\n".join(items))

    if unverifiable:
        st.markdown(f"#### ⓘ 確認不可 ({len(unverifiable)}件)")
        st.caption("提供された HTML / メタ情報 / Ahrefs データだけでは合否判定できなかった項目。スコアの減点対象には含めていません。別途 GSC・実機計測などで確認が必要です。")
        items = []
        for u in unverifiable:
            if not isinstance(u, dict):
                items.append(f"- ⓘ {u}")
                continue
            name = u.get("name", "")
            reason = u.get("reason", "")
            url_u = u.get("url", "")
            head = f"- ⓘ **{name}**" if name else "- ⓘ"
            if reason:
                head += f" — {reason}"
            if url_u:
                head += f" [↗]({url_u})"
            items.append(head)
        st.markdown("\n".join(items))


if mode == "サイト分析":

    # ─── 実行ボタン押下時: データ更新 ───
    if run_btn:
        st.markdown("---")
        # 想定総時間 (秒)。Ahrefs API 並列化 + Sonnet + max_tokens 削減後の見込み。
        ESTIMATED_SECONDS = 90
        # 想定処理ステージ (累積秒数, ラベル)。プログレスバーの体感UX用。
        # 実際の処理境界とは厳密には一致しないが、ユーザーに「今何をしているか」を伝える
        STAGES = [
            (15, "🔍 Ahrefs サイトデータ取得中..."),
            (90, "🧠 AI による多軸スコアリング中 (Sonnet 4.6)..."),
        ]

        progress_bar = st.progress(0, text=f"調査分析中  想定 {ESTIMATED_SECONDS}秒")
        status_box = st.empty()

        # 別スレッドで分析実行 → メインで進捗バー更新
        result_holder: dict = {}

        def _worker():
            try:
                if is_mock_mode():
                    # mock も実時間で 3-5 秒程度かけて終わる
                    time.sleep(3.0)
                    result_holder["data"] = _build_mock_structured(url)
                else:
                    result_holder["data"] = analyze_site_structured(url, url_match)
            except Exception as e:
                result_holder["error"] = str(e)
                result_holder["data"] = None

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        # 進捗バーを 1秒ごと更新 (ESTIMATED_SECONDS で 100% に到達)
        start = time.time()
        while thread.is_alive():
            elapsed = time.time() - start
            pct = min(99, int(elapsed / ESTIMATED_SECONDS * 100))
            remaining = max(0, ESTIMATED_SECONDS - int(elapsed))
            # 経過時間に応じてステージラベルを切り替え
            stage_label = STAGES[-1][1]
            for boundary, label in STAGES:
                if elapsed <= boundary:
                    stage_label = label
                    break
            progress_bar.progress(
                pct,
                text=f"{stage_label}  ·  残り約 {remaining}秒",
            )
            time.sleep(1.0)

        thread.join(timeout=2)

        # 分析が早く終わった場合も含め、完了で 100% にジャンプ
        progress_bar.progress(100, text="✓ 完了")
        time.sleep(0.3)
        progress_bar.empty()

        new_data = result_holder.get("data")
        if new_data is None:
            new_data = _build_mock_structured(url)
            new_data["error"] = result_holder.get("error", "分析処理が中断されました")
            new_data["ahrefs"] = {
                "metrics": {},
                "top_keywords": [],
                "top_pages": [],
                "top_directories": [],
                "domain": "",
            }

        st.session_state.analysis_data = new_data

        # ─── 分析ログをDBに保存 ───
        try:
            axis_scores = {}
            total_score = None
            if isinstance(new_data.get("axes"), list):
                axis_scores = {a.get("name", "?"): a.get("score", 0) for a in new_data["axes"]}
                total_score = sum(int(v) for v in axis_scores.values() if isinstance(v, (int, float)))
            db.save_analysis(
                mode="サイト分析",
                target_url=url,
                url_match_mode=url_match,
                query_text=None,
                total_score=total_score,
                axis_scores=axis_scores,
                full_result=new_data,
            )
        except Exception:
            pass

        if new_data.get("error"):
            status_box.error(
                f"⚠️ 分析が完了できませんでした: {new_data['error']}\n\n"
                "スコア・指摘事項は空欄表示になります。再度「分析を実行」を試してください。"
            )
        elif is_mock_mode():
            status_box.info("✓ 分析完了 (mockモード)")
        else:
            status_box.success("✓ 分析完了")
            # 軽微な警告 (型不一致による自動補正など) を表示
            warnings = new_data.get("_warnings", [])
            if warnings:
                with st.expander("⚠ 軽微な警告 (自動補正済み)", expanded=False):
                    for w in warnings:
                        st.caption(f"• {w}")

    # ─── データ取得 (session_state にあれば使用、無ければ mock) ───
    data = st.session_state.get("analysis_data")
    is_example_data = data is None or not isinstance(data, dict) or "summary" not in data
    if is_example_data:
        data = _build_mock_structured(url)
        st.info("【例】これはサンプル表示です。実際の分析結果を表示するには、左の「分析を実行」ボタンを押してください。")

    # summary が dict でない場合の防御 (LLMが文字列で返すケース)
    raw_summary = data.get("summary", {})
    if not isinstance(raw_summary, dict):
        data["summary"] = {
            "total_score": 0,
            "axes": [],
            "strengths": str(raw_summary) if raw_summary else "",
            "concerns": "",
            "priority_action": "",
        }
    summary = data["summary"]
    url_meta = data.get("url_meta", {}) if isinstance(data.get("url_meta"), dict) else {}
    target_url = data.get("target_url", url) or url

    # axes (data 直下) が無い・不完全な場合の防御
    if "axes" not in data or not isinstance(data.get("axes"), dict):
        data["axes"] = {
            "internal_seo": {"issues": [], "passed": []},
            "external_seo": {"issues": [], "passed": []},
            "content_seo": {"issues": [], "passed": []},
            "eeat": {"issues": [], "passed": []},
            "ai_exposure": {"issues": [], "passed": []},
        }
    # 各軸の中身が dict でない場合も補正
    for k in ["internal_seo", "external_seo", "content_seo", "eeat", "ai_exposure"]:
        if not isinstance(data["axes"].get(k), dict):
            data["axes"][k] = {"issues": [], "passed": []}
        data["axes"][k].setdefault("issues", [])
        data["axes"][k].setdefault("passed", [])

    # summary.axes が list でない場合の防御
    if "axes" not in summary or not isinstance(summary.get("axes"), list):
        summary["axes"] = [
            {"key": "internal_seo", "name": "内部SEO・テクニカル", "score": 0, "issues": 0, "total": 17},
            {"key": "external_seo", "name": "外部SEO・サイテーション", "score": 0, "issues": 0, "total": 7},
            {"key": "content_seo", "name": "コンテンツSEO・記事", "score": 0, "issues": 0, "total": 21},
            {"key": "eeat", "name": "EEAT・広報", "score": 0, "issues": 0, "total": 14},
            {"key": "ai_exposure", "name": "AI露出 (LLMO・AI引用)", "score": 0, "issues": 0, "total": 8},
        ]
    scores_dict = _scores_dict_from_data(data)
    total_score = summary.get("total_score", 0) if isinstance(summary, dict) else 0

    # ─── 上段: スコア + レーダー + メタ情報 ───
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
            st.plotly_chart(
                render_radar_chart(scores_dict),
                use_container_width=True,
                config={"displayModeBar": False},
            )
        with sub_right:
            render_score_bars(scores_dict)

    with col_right:
        st.markdown("**調査URLメタ情報**")
        title_v = url_meta.get("title") or "(取得失敗)"
        desc_v = url_meta.get("meta_description") or "(なし)"
        idx_v = url_meta.get("index_status") or "(不明)"
        canonical_v = url_meta.get("canonical") or "self"
        sd_v = " ".join([f"`{s}`" for s in url_meta.get("structured_data", [])]) or "(なし)"
        title_v = str(title_v).replace("|", "\\|")
        desc_v = str(desc_v).replace("|", "\\|")
        st.markdown(
            f"""
| 項目 | 値 |
|---|---|
| Title | {title_v} |
| Meta-desc | {desc_v} |
| インデックス | {idx_v} (canonical: {canonical_v}) |
| 構造化データ | {sd_v} |
| 対象URL | [{target_url}]({target_url}) |
        """,
            unsafe_allow_html=False,
        )

    # ─── サマリー ───
    st.markdown("### サマリー")
    sum_col1, sum_col2, sum_col3 = st.columns(3)
    with sum_col1:
        st.markdown("**強み**")
        st.markdown(summary.get("strengths", ""))
    with sum_col2:
        st.markdown("**懸念**")
        st.markdown(summary.get("concerns", ""))
    with sum_col3:
        st.markdown("**施策案**")
        st.markdown(summary.get("priority_action", ""))

    st.divider()

    # ─── 3タブ ───
    tab1, tab2, tab3 = st.tabs(["課題サマリ", "サイトデータ", "参考"])

    with tab1:
        st.markdown("**課題可能性** _(発見数 / 全チェック項目数)_")

        axes_meta = summary["axes"]
        axis_keys = [a["key"] for a in axes_meta]
        axis_labels = [
            f"{a['name']} {a['issues']}/{a['total']}" for a in axes_meta
        ]
        axis_tabs = st.tabs(axis_labels)

        for tab_obj, axis_key in zip(axis_tabs, axis_keys):
            with tab_obj:
                _render_axis_content(data["axes"].get(axis_key, {"issues": [], "passed": []}))

        st.divider()
        st.markdown("### 実施にあたって要検討施策")
        donts = data.get("donts", [])
        if donts:
            donts_lines = []
            for d in donts:
                if not isinstance(d, dict):
                    donts_lines.append(f"- {d}")
                    continue
                donts_lines.append(
                    f"- **{d.get('name','')}** — {d.get('reason','')} [{d.get('evidence_label','')}]({d.get('evidence_url','#')})"
                )
            st.warning("\n".join(donts_lines))

    with tab2:
        st.markdown("#### Ahrefs サイト指標")
        ahrefs = data.get("ahrefs", {})
        metrics = ahrefs.get("metrics", {})
        fetched_at = metrics.get("fetched_at", "")
        api_status = metrics.get("api_status", "")
        api_errors = metrics.get("api_errors", [])
        ahrefs_empty = bool(data.get("error")) or not metrics

        if ahrefs_empty:
            st.info("(分析データなし — 分析が完了するとここに Ahrefs サイト指標が表示されます)")
        else:
            st.caption(f"出典: Ahrefs Site Explorer / 2026-04-27時点 ({fetched_at})")
            # API ステータス警告
            if api_status and api_status != "live":
                with st.expander(f"⚠ Ahrefs API ステータス: {api_status}", expanded=False):
                    if api_errors:
                        st.markdown("**API エラー詳細:** (右上のコピーアイコンで一括コピー)")
                        st.code("\n\n".join(api_errors[:10]), language=None)
                    else:
                        st.caption("詳細エラーなし")
            # live モードでも個別エンドポイントが失敗していればエラーを見せる
            elif api_errors:
                with st.expander(f"⚠ 個別 API エラー ({len(api_errors)}件)", expanded=True):
                    st.caption("メイン指標は取得できているが、一部のエンドポイントで失敗。右上のコピーアイコンで一括コピー可能。")
                    st.code("\n\n".join(api_errors[:10]), language=None)

            # 診断: 生レスポンス (フィールド名のずれを確認するため)
            raw_responses = metrics.get("_raw_responses", {})
            if raw_responses:
                with st.expander("🔧 診断: Ahrefs API 生レスポンス (フィールド名確認用)", expanded=False):
                    import json as _json
                    # 一括コピー用: 全 endpoint+response を 1 つの code block に連結 (右上アイコンでクリップボードへ)
                    st.caption("📋 全レスポンスをまとめてコピーする場合は、下のブロック右上のコピーアイコンを使用。")
                    dump_lines = []
                    for endpoint, resp in raw_responses.items():
                        dump_lines.append(f"=== {endpoint} ===")
                        if resp is None:
                            dump_lines.append("(None - エラー)")
                        else:
                            dump_lines.append(_json.dumps(resp, ensure_ascii=False, indent=2)[:3000])
                        dump_lines.append("")
                    st.code("\n".join(dump_lines), language="json")
                    st.divider()
                    # 個別表示 (見やすさ重視)
                    st.caption("以下は endpoint 別の個別表示 (各ブロック右上アイコンで個別コピー)。")
                    for endpoint, resp in raw_responses.items():
                        st.markdown(f"**`{endpoint}`**")
                        if resp is None:
                            st.code("(None - エラー)", language=None)
                        else:
                            st.code(_json.dumps(resp, ensure_ascii=False, indent=2)[:3000], language="json")

            kc1, kc2, kc3, kc4 = st.columns(4)
            with kc1:
                st.markdown(
                    f'<div class="kpi-card"><div class="kpi-label">Domain Rating</div><div class="kpi-value">{metrics.get("domain_rating", 0)}<span style="font-size:0.78rem;color:#6b6b6b;margin-left:0.2rem;">/100</span></div><div class="kpi-sub">前月比 ±</div></div>',
                    unsafe_allow_html=True,
                )
            with kc2:
                st.markdown(
                    f'<div class="kpi-card"><div class="kpi-label">月間自然検索セッション</div><div class="kpi-value">{metrics.get("monthly_organic_sessions", 0):,}</div><div class="kpi-sub">直近30日</div></div>',
                    unsafe_allow_html=True,
                )
            with kc3:
                st.markdown(
                    f'<div class="kpi-card"><div class="kpi-label">被リンク元ドメイン (全体)</div><div class="kpi-value">{metrics.get("referring_domains_total", 0)}</div><div class="kpi-sub">RD 全カウント</div></div>',
                    unsafe_allow_html=True,
                )
            with kc4:
                st.markdown(
                    f'<div class="kpi-card"><div class="kpi-label">被リンク元ドメイン (価値あり)</div><div class="kpi-value">{metrics.get("referring_domains_quality", 0)}</div><div class="kpi-sub">dofollow / 非スパム</div></div>',
                    unsafe_allow_html=True,
                )

            # ─── Brand Radar (AI 引用) を 8カラム横一列で表示 ───
            br = ahrefs.get("brand_radar", {})
            br_platforms = br.get("platforms", {}) if isinstance(br, dict) else {}
            br_total = br.get("total", 0) if isinstance(br, dict) else 0
            if br_platforms:
                # 順序: すべて → 7プラットフォーム
                br_cards = [("すべて", br_total, "全プラットフォーム")]
                for key in [
                    "google_ai_overviews", "google_ai_mode", "chatgpt",
                    "gemini", "perplexity", "copilot", "grok",
                ]:
                    p = br_platforms.get(key, {})
                    if isinstance(p, dict):
                        br_cards.append((p.get("label", key), p.get("responses", 0), "AI 引用"))
                cols = st.columns(len(br_cards))
                for col, (label, value, sub) in zip(cols, br_cards):
                    with col:
                        st.markdown(
                            f'<div class="kpi-card"><div class="kpi-label">{label}</div><div class="kpi-value">{value:,}</div><div class="kpi-sub">{sub}</div></div>',
                            unsafe_allow_html=True,
                        )
                st.caption(
                    "AI 引用 (Ahrefs Brand Radar) — 自社ドメイン配下のURLが各 AI チャットボット応答内で引用された累計回数。URL一致モード適用。"
                )

            st.markdown("")
            pages_display = metrics.get("organic_pages_count_display") or str(metrics.get("organic_pages_count", 0))
            st.info(f"**{pages_display}** ページが自然検索流入を獲得中 (Ahrefs 上位ページ)")

            st.markdown("#### 流入貢献KW 上位10")
            domain_for_links = ahrefs.get("domain", "")
            kw_data = ahrefs.get("top_keywords", [])
            if kw_data:
                kw_table = "| KW | 月間 | 順位 | 獲得URL |\n|---|---|---|---|\n"
                for k in kw_data:
                    ku = k.get("url", "")
                    # 既にフルURLが入っている。path のみの場合はドメインを補完。
                    if ku.startswith("http"):
                        kw_url = ku
                    elif ku.startswith("/"):
                        kw_url = f"https://{domain_for_links}{ku}"
                    else:
                        kw_url = ku or "#"
                    kw_table += f"| {k.get('keyword','')} | {k.get('volume',0):,} | {k.get('position',0)} | [{kw_url}]({kw_url}) |\n"
                st.markdown(kw_table)
            else:
                st.caption("(データなし)")

            st.markdown("#### 流入URL 上位10")
            page_data = ahrefs.get("top_pages", [])
            if page_data:
                page_table = "| URL | 流入貢献KW | 検索Vol | 推定セッション/月 |\n|---|---|---|---|\n"
                for p in page_data:
                    pu = p.get("url", "")
                    if pu.startswith("http"):
                        p_url = pu
                    elif pu.startswith("/"):
                        p_url = f"https://{domain_for_links}{pu}"
                    else:
                        p_url = pu or "#"
                    top_kw = p.get("top_keyword") or "—"
                    top_vol = p.get("top_keyword_volume", 0)
                    vol_disp = f"{top_vol:,}" if top_vol else "—"
                    page_table += f"| [{p_url}]({p_url}) | {top_kw} | {vol_disp} | {p.get('estimated_sessions',0):,} |\n"
                st.markdown(page_table)
            else:
                st.caption("(データなし)")

            st.markdown("#### 流入上位ディレクトリ")
            dir_data = ahrefs.get("top_directories", [])
            if dir_data:
                dir_table = "| ディレクトリ | ページ数 | 月間流入 | シェア |\n|---|---|---|---|\n"
                for d in dir_data:
                    du = d.get("directory", "")
                    d_url = f"https://{domain_for_links}{du}" if du.startswith("/") else (du or "#")
                    dir_table += f"| [{du}]({d_url}) | {d.get('pages',0)} | {d.get('monthly_sessions',0):,} | {d.get('share_pct',0):.1f}% |\n"
                st.markdown(dir_table)
            else:
                st.caption("(データなし)")

    with tab3:
        contradictions = data.get("contradictions", [])
        sources = data.get("sources", [])
        reference_empty = bool(data.get("error")) or (not contradictions and not sources)

        if reference_empty:
            st.info("(分析データなし — 分析が完了するとここに参考情報・出典が表示されます)")
        else:
            st.markdown("#### 参考: Google公式系情報より調査サイトに関連する項目")
            st.caption("公式発言を鵜呑みにしないこと。施策判断のときに必ず参照する。")
            if contradictions:
                contra_table = "| Googleの公式メッセージ | 内部実装の事実 | 裏付け資料 |\n|---|---|---|\n"
                for c in contradictions:
                    # LLM が稀にスキーマ無視で string を返すケースに耐える
                    if not isinstance(c, dict):
                        pub = str(c).replace("|", "\\|")
                        contra_table += f"| {pub} | — | — |\n"
                        continue
                    pub = str(c.get("public", "")).replace("|", "\\|")
                    intl = str(c.get("internal", "")).replace("|", "\\|")
                    src = f"[{c.get('source_label','')}]({c.get('source_url','#')})"
                    contra_table += f"| {pub} | {intl} | {src} |\n"
                st.markdown(contra_table)
            else:
                st.caption("(参考対比情報なし)")

            st.markdown("#### 出典・参考資料")
            if sources:
                src_lines = []
                for i, s in enumerate(sources, 1):
                    if not isinstance(s, dict):
                        src_lines.append(f"{i}. {s}")
                        continue
                    src_lines.append(
                        f"{i}. [{s.get('text','')}]({s.get('url','#')}) `[{s.get('label','')}]`"
                    )
                st.markdown("\n".join(src_lines))
            else:
                st.caption("(出典データなし)")


# ─── Mode B: 施策レビュー ───────────────────────────────
elif mode == "施策レビュー":
    st.markdown("### 施策レビュー")
    st.caption(
        "既にお持ちの SEO 施策案を貼り付けてください。Google特許・公式情報・QRG・リーク資料・DOJ訴訟資料・VRP に照らして1つずつ評価し、機能する根拠 / 機能しない根拠 / より良い代替案を提示します。"
    )
    st.divider()
    st.info("【例】以下はサンプル会話です。実際にレビューするには、左の入力欄に施策案を貼り付けて「評価する」ボタンを押してください。")

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
            try:
                db.save_analysis(
                    mode="施策レビュー",
                    target_url=related or None,
                    url_match_mode=None,
                    query_text=review_input,
                    total_score=None,
                    axis_scores=None,
                    full_result={"answer_markdown": result, "input": review_input, "related_url": related},
                )
            except Exception:
                pass
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
    st.info("【例】以下はサンプル会話です。実際に質問するには、左の入力欄に質問を入力して「質問する」ボタンを押してください。")

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
            try:
                db.save_analysis(
                    mode="個別質問",
                    target_url=None,
                    url_match_mode=None,
                    query_text=q_input,
                    total_score=None,
                    axis_scores=None,
                    full_result={"answer_markdown": result, "question": q_input},
                )
            except Exception:
                pass
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
