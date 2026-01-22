# AI News Bot

毎朝9時（JST）に生成AI関連ニュースを自動収集し、Google Docsに保存するボットです。

## 機能

- Claude API（web_search tool）を使用してニュースを収集
- 検索対象: Claude/Anthropic, Gemini/Google AI, ChatGPT/OpenAI, Google Antigravity, 生成AI全般
- 5件程度に厳選し、見出し・要約・ソースURLを出力
- 日本語・英語両方のソースを対象、出力は日本語
- Google Docsにドキュメントを作成し、指定フォルダに保存

## セットアップ

### 1. Google Cloud 設定

1. [Google Cloud Console](https://console.cloud.google.com/)でプロジェクトを作成
2. 以下のAPIを有効化:
   - Google Docs API
   - Google Drive API
3. サービスアカウントを作成:
   - 「IAMと管理」→「サービスアカウント」→「サービスアカウントを作成」
   - 作成後、「キー」タブで JSON キーを作成・ダウンロード
4. Google Drive でフォルダを作成し、サービスアカウントのメールアドレスと共有（編集者権限）
5. フォルダのIDを取得（URLの`/folders/`以降の文字列）

### 2. GitHub Secrets 設定

リポジトリの Settings → Secrets and variables → Actions で以下を設定:

| Secret名 | 説明 |
|---------|------|
| `ANTHROPIC_API_KEY` | Anthropic APIキー |
| `GOOGLE_CREDENTIALS_JSON` | サービスアカウントのJSONキー（ファイル内容をそのまま貼り付け） |
| `GOOGLE_DRIVE_FOLDER_ID` | 保存先Google DriveフォルダのID |

### 3. GitHub Actions の有効化

リポジトリの Actions タブで GitHub Actions を有効化してください。

## ローカル実行

### 環境変数の設定

```bash
export ANTHROPIC_API_KEY="your-api-key"
export GOOGLE_DRIVE_FOLDER_ID="your-folder-id"

# 方法A: 環境変数でJSON文字列を指定
export GOOGLE_CREDENTIALS_JSON='{"type": "service_account", ...}'

# 方法B: credentials.json ファイルを配置（プロジェクトルート）
```

### 実行

```bash
pip install -r requirements.txt
python main.py
```

### Google Drive未設定での実行

`GOOGLE_DRIVE_FOLDER_ID` が未設定の場合、コンソールに収集結果を出力して終了します。
Google Docsへの保存なしでニュース収集をテストしたい場合に便利です。

## カスタマイズ

### 検索キーワードの変更

`main.py` の `collect_news()` 関数内のプロンプトを編集してください。

### 実行スケジュールの変更

`.github/workflows/daily-news.yml` の cron 式を変更してください。

```yaml
schedule:
  - cron: '0 0 * * *'  # UTC 0:00 = JST 9:00
```

### 出力件数の変更

`main.py` のプロンプト内「5件程度に厳選」の部分を変更してください。

## ファイル構成

```
ai-news-bot/
├── main.py                      # メインスクリプト
├── requirements.txt             # Python依存関係
├── README.md                    # このファイル
└── .github/
    └── workflows/
        └── daily-news.yml       # GitHub Actions ワークフロー
```

## ライセンス

MIT
