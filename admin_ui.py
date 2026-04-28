"""
管理者ダッシュボード UI。
URL パラメータ ?admin=secretkey-bw でアクセスし、パスワード認証後に表示。
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import pandas as pd
import streamlit as st

import database as db


ADMIN_URL_KEY = os.getenv("ADMIN_URL_KEY", "secretkey-bw")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


def is_admin_unlock_url() -> bool:
    """URL に ?admin=secretkey-bw が付いているか判定。"""
    params = st.query_params
    return params.get("admin") == ADMIN_URL_KEY


def render_admin_login_sidebar() -> None:
    """サイドバー下部に管理者ログイン expander を表示。
    パスワード入力が成功したら session_state.is_admin = True にする。"""
    if not is_admin_unlock_url():
        return
    if st.session_state.get("is_admin"):
        st.sidebar.success("✅ 管理者としてログイン中")
        if st.sidebar.button("🚪 ログアウト", use_container_width=True):
            st.session_state.is_admin = False
            st.session_state.show_admin_dashboard = False
            st.rerun()
        if st.sidebar.button("📊 管理者ダッシュボード", use_container_width=True, type="primary"):
            st.session_state.show_admin_dashboard = True
            st.rerun()
        if st.session_state.get("show_admin_dashboard"):
            if st.sidebar.button("← 一般UIに戻る", use_container_width=True):
                st.session_state.show_admin_dashboard = False
                st.rerun()
        return

    with st.sidebar.expander("🔐 管理者ログイン", expanded=True):
        password = st.text_input("パスワード", type="password", key="admin_pw_input")
        if st.button("ログイン", use_container_width=True):
            if not ADMIN_PASSWORD:
                st.error("ADMIN_PASSWORD 環境変数が未設定です")
            elif password == ADMIN_PASSWORD:
                st.session_state.is_admin = True
                st.session_state.show_admin_dashboard = True
                st.rerun()
            else:
                st.error("パスワードが違います")


def render_admin_dashboard() -> None:
    """管理者ダッシュボードのメイン画面。"""
    col1, col2 = st.columns([4, 1])
    with col1:
        st.title("📊 管理者ダッシュボード")
        st.caption("Branding Works SEO セカンドオピニオン — 利用ログ")
    with col2:
        if st.button("← 一般UIに戻る", use_container_width=True):
            st.session_state.show_admin_dashboard = False
            st.rerun()

    st.divider()

    days = st.session_state.get("admin_days", 30)
    stats = db.get_summary_stats(days=days)

    st.subheader(f"📈 利用サマリ (過去{days}日)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("総分析数", f"{stats.get('total', 0)}")
    c2.metric("ユニークURL", f"{stats.get('unique_urls', 0)}")
    c3.metric("平均スコア", f"{stats.get('avg_score', 0)}")
    c4.metric("人気モード", stats.get("top_mode", "—"))

    st.divider()

    st.subheader("🔍 フィルタ")
    f1, f2, f3 = st.columns([1, 1, 2])
    with f1:
        days_choice = st.selectbox(
            "期間",
            options=[7, 30, 90, 365],
            format_func=lambda x: f"過去{x}日",
            index=1,
            key="admin_days_select",
        )
        if days_choice != days:
            st.session_state.admin_days = days_choice
            st.rerun()
    with f2:
        mode_filter = st.selectbox(
            "モード",
            options=["すべて", "サイト分析", "施策レビュー", "個別質問"],
            key="admin_mode_filter",
        )
    with f3:
        url_search = st.text_input("URL / クエリ検索", key="admin_url_search", placeholder="例: example.com")

    st.divider()

    rows = db.list_analyses(
        days=st.session_state.get("admin_days", 30),
        mode_filter=mode_filter,
        url_search=url_search,
    )

    st.subheader(f"📋 分析ログ一覧 ({len(rows)}件)")

    if not rows:
        st.info("該当する分析ログはありません。")
        return

    if st.session_state.get("admin_view_id"):
        _render_detail_view(st.session_state.admin_view_id)
        return

    for row in rows:
        _render_log_row(row)

    st.divider()
    st.subheader("📥 エクスポート")
    e1, e2 = st.columns(2)
    df = pd.DataFrame([{
        "id": r["id"],
        "created_at": r["created_at"],
        "mode": r["mode"],
        "target_url": r.get("target_url", ""),
        "url_match_mode": r.get("url_match_mode", ""),
        "query_text": r.get("query_text", ""),
        "total_score": r.get("total_score", ""),
    } for r in rows])
    with e1:
        st.download_button(
            "📄 CSV ダウンロード",
            data=df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"seo_logs_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with e2:
        st.download_button(
            "📦 JSON ダウンロード (詳細含む)",
            data=json.dumps(rows, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
            file_name=f"seo_logs_full_{datetime.now().strftime('%Y%m%d')}.json",
            mime="application/json",
            use_container_width=True,
        )


def _render_log_row(row: dict) -> None:
    """ログ一覧の1行を描画。"""
    created = row.get("created_at", "")
    if isinstance(created, datetime):
        created_str = created.strftime("%Y-%m-%d %H:%M")
    else:
        created_str = str(created)[:16]
    mode = row.get("mode", "—")
    url = row.get("target_url") or ""
    query = row.get("query_text") or ""
    score = row.get("total_score")
    axes = row.get("axis_scores") or {}
    match_mode = row.get("url_match_mode") or ""

    with st.container(border=True):
        c1, c2 = st.columns([5, 1])
        with c1:
            header = f"**{created_str}** | {mode}"
            if match_mode:
                header += f" | {match_mode}"
            st.markdown(header)
            if url:
                st.markdown(f"🌐 `{url}`")
            if query:
                st.markdown(f"💬 「{query[:100]}{'...' if len(query) > 100 else ''}」")
            if score is not None:
                axis_summary = "  ".join([f"{k.split('・')[0]}{v}" for k, v in axes.items()][:5])
                st.markdown(f"**スコア: {score}/100**  {axis_summary}")
        with c2:
            if st.button("詳細を見る", key=f"detail_{row['id']}", use_container_width=True):
                st.session_state.admin_view_id = row["id"]
                st.rerun()


def _render_detail_view(analysis_id: int) -> None:
    """ログ詳細表示(クリック時)。"""
    if st.button("← 一覧に戻る"):
        st.session_state.admin_view_id = None
        st.rerun()

    row = db.get_analysis(analysis_id)
    if not row:
        st.error("ログが見つかりません")
        return

    st.subheader(f"分析詳細 #{analysis_id}")
    st.caption(f"{row.get('created_at', '')} | {row.get('mode', '')}")

    if row.get("target_url"):
        st.markdown(f"**対象URL:** `{row['target_url']}` ({row.get('url_match_mode', '')})")
    if row.get("query_text"):
        st.markdown(f"**クエリ/施策:**\n> {row['query_text']}")

    if row.get("total_score") is not None:
        st.metric("総合スコア", f"{row['total_score']}/100")

    st.divider()
    st.subheader("📄 完全レポート (JSON)")

    full = row.get("full_result") or {}
    if isinstance(full, str):
        try:
            full = json.loads(full)
        except Exception:
            pass

    st.json(full, expanded=False)

    st.download_button(
        "📦 このログをJSONダウンロード",
        data=json.dumps(row, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
        file_name=f"analysis_{analysis_id}.json",
        mime="application/json",
    )
