# SEO セカンドオピニオン WebUI

Branding Works (https://www.branding-works.jp/) が提供する SEO 診断ツール。Google特許・公式情報・QRG・リーク資料・DOJ訴訟資料・VRP情報に基づくエビデンスベースの診断を 5軸 (内部SEO・テクニカル / 外部SEO・サイテーション / コンテンツSEO・記事 / EEAT・広報 / AI露出 LLMO・AI引用) で 20点満点 × 5 = 100点でスコア化。

## ローカル起動 (5分)

### 1. Python 仮想環境を作成

PowerShell:
```powershell
cd C:\Users\owner\.claude\seo-second-opinion-app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

bash (Git Bash):
```bash
cd /c/Users/owner/.claude/seo-second-opinion-app
python -m venv .venv
source .venv/Scripts/activate
```

### 2. 依存パッケージをインストール

```bash
pip install -r requirements.txt
```

### 3. 環境変数を設定

`.env.example` を `.env` にコピーして編集:

```bash
cp .env.example .env
```

最低限必要な設定:
- `ANTHROPIC_API_KEY=sk-ant-...` ([Anthropic Console](https://console.anthropic.com/settings/keys) で取得)
- `APP_MODE=live` (実APIを使う場合) / `mock` (UIプレビューのみ)

### 4. アプリ起動

```bash
streamlit run app.py
```

ブラウザが自動で開きます (`http://localhost:8501`)。

## 動作モード

| `APP_MODE` | 動作 | 用途 |
|---|---|---|
| `mock` (デフォルト) | ダミーデータ表示。API は呼ばない | UIデザイン確認、デモ |
| `live` | 実 Anthropic API を呼び出す | 本番分析 |

`mock` モードでも UI は完全に動作します。

## デプロイ (Render.com)

### 手順 (15分)

1. このフォルダの内容を GitHub リポジトリに push
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<YOUR_USER>/seo-second-opinion-app.git
   git push -u origin main
   ```

2. https://dashboard.render.com にログイン

3. **「New + → Blueprint」** をクリック → GitHub リポジトリを連携 → `render.yaml` を自動検出

4. 環境変数を設定:
   - `ANTHROPIC_API_KEY` (機密、ダッシュボードで個別入力)
   - `AHREFS_API_TOKEN` (任意)
   - `APP_MODE` を `live` に変更 (実API使う場合)

5. **Deploy** クリック → 数分でデプロイ完了

### 公開URL
`https://seo-second-opinion-XXXX.onrender.com` のような形式で自動発行。Free プランは 15分無アクセスで sleep するため、商用なら **Starter プラン ($7/月)** を推奨。

### カスタムドメイン
`tools.branding-works.jp` のようなサブドメインで公開する場合:
- Render ダッシュボード → Settings → Custom Domain → CNAME 設定 → SSL 自動発行 (Let's Encrypt)

## ファイル構成

```
seo-second-opinion-app/
├── app.py                      # Streamlit メインアプリ
├── seo_analyzer.py             # Anthropic API ラッパー (3モード)
├── agent_system_prompt.py      # システムプロンプト (Python文字列)
├── ahrefs_client.py            # Ahrefs API クライアント (mock fallback)
├── requirements.txt            # Python 依存
├── render.yaml                 # Render.com デプロイ設定
├── .env.example                # 環境変数テンプレ
├── .gitignore
└── README.md                   # このファイル
```

## カスタマイズ

### システムプロンプトの変更
`agent_system_prompt.py` の `SYSTEM_PROMPT` 定数を編集。元ソースは `~/.claude/agents/google-seo-second-opinion.md`。

### モックデータの変更
`ahrefs_client.py` の `_mock_*` 関数 / `seo_analyzer.py` の `_mock_*_response` 関数を編集。

### モデルの変更
`.env` の `ANTHROPIC_MODEL` で指定。Sonnet が応答速い (`claude-sonnet-4-6`)、コスト最適なら Haiku (`claude-haiku-4-5-20251001`)。

### Ahrefs 実 API 接続
`ahrefs_client.py` の TODO コメント箇所を実装。Ahrefs API token 必要 (https://ahrefs.com/api)。

## 管理者専用ログ閲覧機能

フリーツールとして公開しても、第三者にはログが見えず**管理者だけ**が全利用ログを閲覧できる仕組み。

### しくみ
1. 一般ユーザーは普通のURLでアクセス → 通常UIのみ、管理者要素は完全非表示
2. 管理者は `https://<your-app>/?admin=secretkey-bw` でアクセス → サイドバーに「🔐 管理者ログイン」expander が出現
3. `ADMIN_PASSWORD` 環境変数と一致するパスワードを入力 → 「📊 管理者ダッシュボード」ボタンが出現
4. ダッシュボードで全分析ログ閲覧、CSV/JSON エクスポート可能

### セットアップ (Render)

#### 1. Neon (無料 Postgres) を準備
1. https://neon.tech に GitHubアカウントでログイン (無料3GB)
2. New Project → Region は Japan に近い場所 (Singapore等)
3. 接続URLをコピー: `postgresql://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require`

#### 2. Render 側で環境変数を設定
Render ダッシュボード → Environment:
- `ADMIN_PASSWORD` = (任意の長めのパスワード、例 `bw-seo-admin-2026-xyz`)
- `ADMIN_URL_KEY` = `secretkey-bw` (URLの目印。変えてもよい)
- `DATABASE_URL` = (Neonでコピーしたpostgresql://...)

設定後、自動再デプロイが走り、起動時にテーブル `analyses` が自動作成される。

#### 3. アクセス確認
- 一般 URL: `https://<your-app>.onrender.com` → 普段通り(サイドバーでモード切り替え可)
- 施策レビュー専用 URL: `https://<your-app>.onrender.com/?mode=review` → 施策レビュー固定、モード切り替え非表示
- 個別質問専用 URL: `https://<your-app>.onrender.com/?mode=ask` → 個別質問固定、モード切り替え非表示
- 管理者 URL: `https://<your-app>.onrender.com/?admin=secretkey-bw` → ログイン欄が出現
- パスワード入力後、サイドバー「📊 管理者ダッシュボード」をクリック

### 管理者ダッシュボード機能
- 過去30日の利用サマリ (総分析数 / ユニークURL / 平均スコア / 人気モード)
- 期間フィルタ (7日/30日/90日/365日)、モードフィルタ、URL/クエリ検索
- 各ログの「詳細を見る」で完全なJSONレポート閲覧
- CSV / JSON 一括エクスポート
- ログアウトボタン

### ローカル実行 (DB なしでも動く)
`DATABASE_URL` 未設定なら SQLite (`/tmp/seo_logs.db`) に保存。Render Free プランで再デプロイすると消えるため本番はNeon必須。

### プライバシーに関する注意
- ユーザーの IPアドレスや生メールは保存していない (`user_hash` 列はSHA-256ハッシュのみ)
- 入力したURL・施策・質問内容はログに残るため、管理者が閲覧することを利用規約に明記推奨

## トラブルシューティング

### `streamlit: command not found`
仮想環境がアクティブでない可能性。再アクティベート:
```bash
source .venv/Scripts/activate  # bash
.\.venv\Scripts\Activate.ps1   # PowerShell
```

### `❌ ANTHROPIC_API_KEY が設定されていません`
`.env` ファイルが正しく読み込まれていない。`.env` がプロジェクトルートにあるか、`load_dotenv()` がコール後に環境変数が設定されているか確認。

### 文字化け (Windows)
PowerShell で UTF-8 設定:
```powershell
$env:PYTHONIOENCODING="utf-8"
streamlit run app.py
```

## 関連ドキュメント

- HTML モックアップ: `~/.claude/google-seo-second-opinion-mockup.html`
- エージェント定義: `~/.claude/agents/google-seo-second-opinion.md`
- スキル入口: `~/.claude/skills/google-seo-second-opinion/SKILL.md`
- Render デプロイ詳細: `~/.claude/google-seo-second-opinion-DEPLOY.md`
