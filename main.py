#!/usr/bin/env python3
"""AI News Bot - 生成AI関連ニュースを収集してGoogle Docsに保存"""

import json
import os
from datetime import datetime, timezone, timedelta

import anthropic
from google.oauth2 import service_account
from googleapiclient.discovery import build


def get_google_credentials():
    """Google認証情報を取得（環境変数またはファイルから）"""
    scopes = [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive.file",
    ]

    # 環境変数からJSON文字列を取得
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_info = json.loads(creds_json)
        return service_account.Credentials.from_service_account_info(
            creds_info, scopes=scopes
        )

    # ローカルファイルから取得
    creds_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    if os.path.exists(creds_file):
        return service_account.Credentials.from_service_account_file(
            creds_file, scopes=scopes
        )

    return None


def collect_news() -> str:
    """Claude APIのweb_search toolを使ってニュースを収集"""
    client = anthropic.Anthropic()

    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y年%m月%d日")

    prompt = f"""今日は{today}です。過去24〜48時間以内の生成AI関連の最新ニュースを検索してください。

検索対象キーワード:
- Claude / Anthropic
- Gemini / Google AI
- ChatGPT / OpenAI
- Google Antigravity（Googleのバイブコーディングプラットフォーム）
- 生成AI / Generative AI 全般

以下の形式で5件程度に厳選して日本語で出力してください。日本語・英語両方のソースを対象にしてください。

出力形式:
## [ニュースの見出し]
[1〜2行の要約]
ソース: [URL]

---

重要度・話題性の高いものを優先してください。"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        tools=[{"type": "web_search_20250305"}],
        messages=[{"role": "user", "content": prompt}],
    )

    # レスポンスからテキスト部分を抽出
    result_text = ""
    for block in response.content:
        if block.type == "text":
            result_text += block.text

    return result_text


def create_google_doc(content: str, folder_id: str | None) -> str | None:
    """Google Docsにドキュメントを作成"""
    credentials = get_google_credentials()
    if not credentials:
        print("Google認証情報が見つかりません")
        return None

    # ドキュメント作成
    docs_service = build("docs", "v1", credentials=credentials)
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).strftime("%Y-%m-%d")
    title = f"AI News - {today}"

    doc = docs_service.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]

    # コンテンツを挿入
    requests = [{"insertText": {"location": {"index": 1}, "text": content}}]
    docs_service.documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()

    # フォルダに移動
    if folder_id:
        drive_service = build("drive", "v3", credentials=credentials)
        drive_service.files().update(
            fileId=doc_id, addParents=folder_id, fields="id, parents"
        ).execute()

    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
    return doc_url


def main():
    print("=== AI News Bot ===")
    print("ニュースを収集中...")

    news_content = collect_news()

    if not news_content:
        print("ニュースの収集に失敗しました")
        return

    print("\n--- 収集結果 ---")
    print(news_content)
    print("----------------\n")

    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")

    if not folder_id:
        print("GOOGLE_DRIVE_FOLDER_IDが未設定のため、コンソール出力のみで終了します")
        return

    credentials = get_google_credentials()
    if not credentials:
        print("Google認証情報が見つからないため、コンソール出力のみで終了します")
        return

    print("Google Docsにドキュメントを作成中...")
    doc_url = create_google_doc(news_content, folder_id)

    if doc_url:
        print(f"ドキュメントを作成しました: {doc_url}")
    else:
        print("ドキュメントの作成に失敗しました")


if __name__ == "__main__":
    main()
