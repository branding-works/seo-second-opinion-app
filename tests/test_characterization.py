"""現状の動作を固定する特性テスト。リファクタリング中の回帰検知用。

注意: test_url_meta_csv_keys_current_behavior は「現状のバグ」を固定している。
計画書の項目 R5 でバグ修正と同時に期待値を更新すること。
"""
import io
import re
import zipfile

import pytest


@pytest.fixture(autouse=True)
def _safe_env(monkeypatch):
    """live API を絶対に呼ばないための保険。"""
    monkeypatch.setenv("APP_MODE", "mock")
    monkeypatch.delenv("AHREFS_API_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# ─── ahrefs_client: URL一致モード変換 ───────────────────

def test_resolve_target_and_mode_exact():
    from ahrefs_client import resolve_target_and_mode
    # 完全一致は末尾スラッシュを保持したまま渡す(CLAUDE.md 記載の重要仕様)
    assert resolve_target_and_mode("https://example.com/", "完全一致") == ("https://example.com/", "exact")


def test_resolve_target_and_mode_prefix():
    from ahrefs_client import resolve_target_and_mode
    assert resolve_target_and_mode("https://example.com/blog/", "部分一致") == ("https://example.com/blog/", "prefix")


def test_resolve_target_and_mode_domain():
    from ahrefs_client import resolve_target_and_mode
    assert resolve_target_and_mode("https://example.com/blog/x", "ドメイン一致") == ("example.com", "domain")


def test_resolve_target_and_mode_subdomains():
    from ahrefs_client import resolve_target_and_mode
    assert resolve_target_and_mode("http://sub.example.com/a", "サブドメイン含む") == ("sub.example.com", "subdomains")


def test_normalize_domain():
    from ahrefs_client import _normalize_domain
    assert _normalize_domain("https://example.com/path?q=1") == "example.com"
    assert _normalize_domain("  example.com  ") == "example.com"


# ─── csv_export: 基本ユーティリティ ─────────────────────

def test_to_csv_bytes_bom_and_columns():
    import csv_export
    b = csv_export._to_csv_bytes([{"a": 1, "b": "x"}], ["a", "b", "c"])
    assert b.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM (Excel 文字化け対策)
    lines = b.decode("utf-8-sig").splitlines()
    assert lines[0] == "a,b,c"
    assert lines[1] == "1,x,"  # 存在しないカラム c は空欄


def test_slugify_domain():
    import csv_export
    assert csv_export._slugify_domain("https://n-works.link/") == "n-works.link"
    assert csv_export._slugify_domain("") == "site"


def test_make_filename_format():
    import csv_export
    name = csv_export.make_filename("example.co.jp", "kpi")
    assert re.fullmatch(r"example\.co\.jp_kpi_\d{4}-\d{2}-\d{2}\.csv", name)


def _csv_rows(b: bytes) -> list[list[str]]:
    import csv as _csv
    return list(_csv.reader(io.StringIO(b.decode("utf-8-sig"))))


def test_url_meta_csv_keys():
    """R5 で修正済み: 実データのキー名で値が入る。"""
    import csv_export
    page_meta = {
        "title": "T", "meta_description": "D", "canonical": "self",
        "index_status": "登録済み", "structured_data": ["Article", "FAQPage"],
        "fetched": True,
    }
    rows = _csv_rows(csv_export.url_meta_csv(page_meta, "https://x.jp/"))
    d = {r[0]: r[1] for r in rows[1:]}
    assert d["対象URL"] == "https://x.jp/"
    assert d["Title"] == "T"
    assert d["Meta-description"] == "D"
    assert d["インデックス状態"] == "登録済み"
    assert d["構造化データ (種類)"] == "Article, FAQPage"
    assert "viewport" not in d and "h1" not in d


# ─── seo_analyzer: mock 構造とスコア骨格 ────────────────

def test_mock_structured_shape():
    from seo_analyzer import _build_mock_structured
    data = _build_mock_structured("https://example.co.jp/blog/seo-guide")
    assert data["summary"]["total_score"] == 71
    assert [a["total"] for a in data["summary"]["axes"]] == [17, 7, 21, 14, 8]
    assert set(data["axes"].keys()) == {
        "internal_seo", "external_seo", "content_seo", "eeat", "ai_exposure"
    }


def test_analyze_site_structured_mock_mode():
    import seo_analyzer
    assert seo_analyzer.is_mock_mode()
    data = seo_analyzer.analyze_site_structured("https://example.co.jp/")
    assert data["summary"]["total_score"] == 71


def test_build_empty_structured():
    from seo_analyzer import _build_empty_structured
    data = _build_empty_structured("https://x.jp/", {}, {}, error="e")
    assert data["summary"]["total_score"] == 0
    assert [a["total"] for a in data["summary"]["axes"]] == [17, 7, 21, 14, 8]
    assert data["error"] == "e"


def test_normalize_axis():
    from seo_analyzer import _normalize_axis
    assert _normalize_axis("garbage") == {"issues": [], "passed": [], "unverifiable": []}
    out = _normalize_axis({"issues": "notalist", "passed": [{"name": "a"}]})
    assert out["issues"] == []
    assert out["passed"] == [{"name": "a"}]
    assert out["unverifiable"] == []


def test_extract_scores_for_log():
    from seo_analyzer import extract_scores_for_log, _build_mock_structured
    data = _build_mock_structured("https://example.co.jp/")
    axis_scores, total = extract_scores_for_log(data)
    assert total == 71
    assert len(axis_scores) == 5
    assert axis_scores["内部SEO・テクニカル"] == 16
    # 壊れたデータには ({}, None) を返す
    assert extract_scores_for_log({"summary": "broken"}) == ({}, None)
    assert extract_scores_for_log(None) == ({}, None)


# ─── csv_export: ZIP 一括出力 ──────────────────────────

def test_build_full_zip_contains_11_csv():
    import csv_export
    from seo_analyzer import _build_mock_structured
    data = _build_mock_structured("https://example.co.jp/")
    z = zipfile.ZipFile(io.BytesIO(csv_export.build_full_zip(data)))
    names = z.namelist()
    assert len(names) == 11
    assert all(n.endswith(".csv") for n in names)


# ─── database: SQLite 保存・取得の往復 ──────────────────

def test_database_sqlite_roundtrip(tmp_path, monkeypatch):
    import database
    monkeypatch.setattr(database, "DATABASE_URL", "")
    monkeypatch.setattr(database, "SQLITE_PATH", str(tmp_path / "t.db"))
    database.init_db()
    new_id = database.save_analysis(
        mode="サイト分析", target_url="https://x.jp/", url_match_mode="完全一致",
        query_text=None, total_score=71,
        axis_scores={"内部SEO・テクニカル": 16}, full_result={"k": "v"},
    )
    assert new_id >= 1
    rows = database.list_analyses(days=1)
    assert len(rows) == 1
    assert rows[0]["total_score"] == 71
    assert rows[0]["axis_scores"] == {"内部SEO・テクニカル": 16}
    assert rows[0]["full_result"] == {"k": "v"}
    one = database.get_analysis(new_id)
    assert one["mode"] == "サイト分析"


# ─── seo_analyzer: 会話継続(履歴付き呼び出し) ───────────────

def test_answer_question_first_turn_builds_formatted_prompt():
    from seo_analyzer import answer_question
    answer, sent_message = answer_question("ドメインオーソリティは本当に使われていませんか?")
    assert answer  # mockモードなので固定文字列が返る
    assert "モード: C" in sent_message  # 初回は整形済みプロンプトが送信される
    assert "ドメインオーソリティは本当に使われていませんか?" in sent_message


def test_answer_question_follow_up_sends_raw_question_only():
    from seo_analyzer import answer_question
    history = [
        {"role": "user", "content": "モード: C (個別質問)\n\n質問:\n初めの質問\n\n..."},
        {"role": "assistant", "content": "前回の回答"},
    ]
    answer, sent_message = answer_question("では根拠となる特許番号は?", history=history)
    assert answer
    assert sent_message == "では根拠となる特許番号は?"  # 2ターン目以降は整形しない


def test_review_strategy_first_turn_builds_formatted_prompt():
    from seo_analyzer import review_strategy
    answer, sent_message = review_strategy("FAQPage schemaを全ページに入れる")
    assert answer
    assert "モード: B" in sent_message
    assert "FAQPage schemaを全ページに入れる" in sent_message


def test_review_strategy_follow_up_sends_raw_text_only():
    from seo_analyzer import review_strategy
    history = [
        {"role": "user", "content": "モード: B (施策レビュー)\n\nレビュー対象の施策案:\n初回の施策案\n\n..."},
        {"role": "assistant", "content": "前回の評価"},
    ]
    answer, sent_message = review_strategy("2番目の案について詳しく", history=history)
    assert answer
    assert sent_message == "2番目の案について詳しく"
