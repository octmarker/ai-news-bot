# Render でのセットアップ手順

このドキュメントでは、Renderを使ってAI News Botを自動実行する方法を説明します。

## 前提条件

- GitHubアカウント
- Renderアカウント（無料）
- Anthropic APIキー
- GitHub Personal Access Token（リポジトリへの書き込み権限が必要）

## 1. GitHub Personal Access Tokenの作成

1. GitHubにログイン
2. Settings → Developer settings → Personal access tokens → Tokens (classic)
3. "Generate new token (classic)" をクリック
4. 以下を設定：
   - Note: `Render AI News Bot`
   - Expiration: `No expiration` または適切な期限
   - Scopes: `repo` (Full control of private repositories) にチェック
5. "Generate token" をクリック
6. **トークンをコピーして安全な場所に保存**（再表示されません）

## 2. Renderアカウントの作成

1. https://render.com にアクセス
2. "Get Started for Free" をクリック
3. GitHubアカウントで連携してサインアップ

## 3. Renderでのデプロイ

### 方法A: render.yamlを使った自動デプロイ（推奨）

1. Renderダッシュボードで "New +" → "Blueprint" をクリック
2. GitHubリポジトリ `octmarker/ai-news-bot` を選択
3. "Connect" をクリック
4. `render.yaml` が自動検出される
5. 環境変数を設定：
   - `ANTHROPIC_API_KEY`: あなたのAnthropic APIキー
   - `GITHUB_TOKEN`: 上記で作成したGitHub Personal Access Token
6. "Apply" をクリック

### 方法B: 手動セットアップ

1. Renderダッシュボードで "New +" → "Cron Job" をクリック
2. GitHubリポジトリ `octmarker/ai-news-bot` を選択
3. 以下を設定：
   - **Name**: `ai-news-bot`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Command**: `python main.py`
   - **Schedule**: `5 0 * * *` (毎朝9:05 JST)
4. 環境変数を追加：
   - `ANTHROPIC_API_KEY`: あなたのAnthropic APIキー
   - `GITHUB_TOKEN`: 上記で作成したGitHub Personal Access Token
   - `GITHUB_REPOSITORY`: `octmarker/ai-news-bot`
   - `GIT_USER_NAME`: `render-bot`
   - `GIT_USER_EMAIL`: `render-bot@users.noreply.github.com`
5. "Create Cron Job" をクリック

## 4. 動作確認

### 手動実行でテスト

1. Renderダッシュボードで作成したCron Jobを開く
2. "Manual Trigger" または "Trigger Run" ボタンをクリック
3. ログを確認して正常に動作することを確認
4. GitHubリポジトリの `news/` ディレクトリに新しいファイルが追加されているか確認

### スケジュール実行の確認

- 次回の実行予定時刻（9:05 JST）まで待つ
- Renderダッシュボードの "Logs" タブで実行履歴を確認

## トラブルシューティング

### エラー: `Permission denied (publickey)`

GitHub Tokenが正しく設定されていない可能性があります。
- `GITHUB_TOKEN` 環境変数が正しく設定されているか確認
- トークンに `repo` スコープが含まれているか確認

### エラー: `ANTHROPIC_API_KEY is not set`

- Renderの環境変数設定で `ANTHROPIC_API_KEY` が正しく設定されているか確認

### ニュースが収集されない

- Renderのログを確認してエラーメッセージを確認
- Anthropic APIの利用制限に達していないか確認

## 料金について

Renderの無料プランでは：
- **月750時間**のCron Job実行時間が無料
- 1日1回の実行なら十分無料枠内で運用可能
- 実行時間は通常1〜2分程度なので、月60分程度の使用量

## GitHub Actionsとの併用

Renderを使う場合でも、GitHub Actionsの設定はそのまま残しておいて問題ありません。
両方が同時に実行されても、Gitの競合が発生する可能性は低いです（同じ時刻に実行されない限り）。

どちらか一方だけを使いたい場合：
- **GitHub Actionsを無効化**: `.github/workflows/daily-news.yml` を削除またはリネーム
- **Renderを無効化**: RenderのダッシュボードでCron Jobを削除

## 参考リンク

- [Render Cron Jobs ドキュメント](https://render.com/docs/cronjobs)
- [Render 環境変数の設定](https://render.com/docs/environment-variables)
- [GitHub Personal Access Tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token)
