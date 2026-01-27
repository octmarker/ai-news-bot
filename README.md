# AI News Bot

毎朝9時（JST）に生成AI関連ニュースを自動収集し、リポジトリに保存するボットです。

## 機能

- Claude API（web_search tool）を使用してニュースを収集
- 検索対象: Claude/Anthropic, Gemini/Google AI, ChatGPT/OpenAI, Google Antigravity, 生成AI全般
- 5件程度に厳選し、見出し・要約・ソースURLを出力
- 日本語・英語両方のソースを対象、出力は日本語
- `news/YYYY-MM-DD.md` 形式でリポジトリに自動コミット

## セットアップ

### 1. GitHub Secrets 設定

リポジトリの Settings → Secrets and variables → Actions で以下を設定:

| Secret名 | 説明 |
|---------|------|
| `ANTHROPIC_API_KEY` | Anthropic APIキー |

### 2. GitHub Actions の有効化

リポジトリの Actions タブで GitHub Actions を有効化してください。

## ローカル実行

```bash
export ANTHROPIC_API_KEY="your-api-key"
pip install -r requirements.txt
python main.py
```

ローカル実行時は `news/` ディレクトリにファイルが保存されますが、自動コミットは行われません。

## カスタマイズ

### 検索キーワードの変更

`main.py` の `collect_news()` 関数内のプロンプトを編集してください。

### 実行スケジュールの変更

`.github/workflows/daily-news.yml` の cron 式を変更してください。

```yaml
schedule:
  - cron: '5 0 * * *'  # UTC 0:05 = JST 9:05
```

### 出力件数の変更

`main.py` のプロンプト内「5件程度に厳選」の部分を変更してください。

## ファイル構成

```
ai-news-bot/
├── main.py                      # メインスクリプト
├── requirements.txt             # Python依存関係
├── README.md                    # このファイル
├── news/                        # ニュース保存先
│   └── YYYY-MM-DD.md
└── .github/
    └── workflows/
        └── daily-news.yml       # GitHub Actions ワークフロー
```

## ライセンス

MIT
