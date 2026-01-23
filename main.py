#!/usr/bin/env python3
"""AI News Bot - 生成AI関連ニュースを収集してMarkdownファイルに保存"""

import os
import subprocess
from datetime import datetime, timezone, timedelta

import httpx


def collect_news() -> str:
    """Claude APIのweb_search toolを使ってニュースを収集"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set")

    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y年%m月%d日")

    yesterday = (datetime.now(timezone(timedelta(hours=9))) - timedelta(days=1)).strftime("%Y年%m月%d日")

    prompt = f"""今日は{today}です。あなたはVibe Coding専門のニュースキュレーターです。

【重要な制約】
- 必ず{yesterday}〜{today}に公開された記事のみを含めてください
- 記事のURLや本文に含まれる日付を確認し、それ以前の古い記事は絶対に含めないでください
- 該当期間のニュースが見つからない場合は、無理に古い記事を含めず「該当なし」としてください

【検索トピック】
優先（必ず検索）:
- Google Antigravity（Googleのエージェント型開発プラットフォーム）
- Claude Code（Anthropicのコーディングエージェント）

補助（大きなニュースがあれば）:
- Claude / Anthropic
- Gemini / Google AI
- ChatGPT / OpenAI

【出力要件】
- 合計5件程度に厳選（該当期間のニュースがない場合は少なくてOK）
- 日本語・英語両方のソースを対象
- 出力は日本語で統一

【出力フォーマット】
---
## [カテゴリ名]

### [ニュースの見出し]
公開日: YYYY-MM-DD
[1〜2行の要約]
→ [ソースURL]

---

該当期間にニュースがない場合は「本日の主要ニュースはありませんでした」と記載してください。"""

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
    }

    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    # レスポンスからテキスト部分を抽出
    result_text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            result_text += block.get("text", "")

    return result_text


def save_to_file(content: str) -> str:
    """ニュースをMarkdownファイルに保存"""
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst)
    date_str = today.strftime("%Y-%m-%d")

    # newsディレクトリを作成
    os.makedirs("news", exist_ok=True)

    # ファイルに保存
    filename = f"news/{date_str}.md"
    header = f"# AI News - {date_str}\n\n"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(header + content)

    return filename


def git_commit_and_push(filename: str):
    """変更をコミットしてプッシュ"""
    # Git設定
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)

    # 追加・コミット・プッシュ
    subprocess.run(["git", "add", filename], check=True)

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        capture_output=True,
    )

    if result.returncode != 0:  # 変更がある場合
        date_str = os.path.basename(filename).replace(".md", "")
        subprocess.run(
            ["git", "commit", "-m", f"Add AI news for {date_str}"],
            check=True,
        )
        subprocess.run(["git", "push"], check=True)
        print(f"コミットしてプッシュしました: {filename}")
    else:
        print("変更がないためコミットをスキップしました")


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

    print("ファイルに保存中...")
    filename = save_to_file(news_content)
    print(f"保存しました: {filename}")

    # GitHub Actions環境でのみコミット
    if os.environ.get("GITHUB_ACTIONS"):
        git_commit_and_push(filename)


if __name__ == "__main__":
    main()
