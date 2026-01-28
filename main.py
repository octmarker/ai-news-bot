#!/usr/bin/env python3
"""AI News Bot - 生成AI関連ニュースを収集してMarkdownファイルに保存 (Gemini版)"""

import os
import subprocess
from datetime import datetime, timezone, timedelta

import google.generativeai as genai


def collect_news() -> str:
    """Gemini APIのGoogle Search groundingを使ってニュースを収集"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    genai.configure(api_key=api_key)

    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    today = now.strftime("%Y年%m月%d日")
    yesterday = (now - timedelta(days=1)).strftime("%Y年%m月%d日")
    
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S JST')}] Starting news collection...")
    print(f"Target period: {yesterday} ~ {today}")

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

    # Gemini 2.5 Flash with Google Search grounding (stable version)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        tools="google_search_retrieval",
    )
    
    print(f"[{datetime.now(jst).strftime('%Y-%m-%d %H:%M:%S JST')}] Sending request to Gemini API...")
    
    response = model.generate_content(prompt)
    
    print(f"[{datetime.now(jst).strftime('%Y-%m-%d %H:%M:%S JST')}] News collection completed successfully")
    
    return response.text


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
    jst = timezone(timedelta(hours=9))
    print(f"[{datetime.now(jst).strftime('%Y-%m-%d %H:%M:%S JST')}] Starting git operations...")
    
    # Render環境の場合、Gitリポジトリを初期化
    github_token = os.environ.get("GITHUB_TOKEN")
    github_repo = os.environ.get("GITHUB_REPOSITORY")
    
    if github_token and github_repo and not os.environ.get("GITHUB_ACTIONS"):
        print("Initializing Git repository for Render...")
        
        # .gitディレクトリが存在しない場合は初期化
        if not os.path.exists(".git"):
            subprocess.run(["git", "init"], check=True)
            subprocess.run(["git", "remote", "add", "origin", f"https://{github_token}@github.com/{github_repo}.git"], check=True)
            print("Git repository initialized and remote added")
        else:
            # リモートが存在しない場合は追加
            result = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True)
            if result.returncode != 0:
                subprocess.run(["git", "remote", "add", "origin", f"https://{github_token}@github.com/{github_repo}.git"], check=True)
            else:
                subprocess.run(["git", "remote", "set-url", "origin", f"https://{github_token}@github.com/{github_repo}.git"], check=True)
        
        # mainブランチに切り替え（存在しない場合は作成）
        subprocess.run(["git", "checkout", "-B", "main"], check=True)
    
    # Git設定（環境変数から取得、デフォルトはGitHub Actions用）
    git_user_name = os.environ.get("GIT_USER_NAME", "github-actions[bot]")
    git_user_email = os.environ.get("GIT_USER_EMAIL", "github-actions[bot]@users.noreply.github.com")
    
    subprocess.run(["git", "config", "user.name", git_user_name], check=True)
    subprocess.run(["git", "config", "user.email", git_user_email], check=True)

    # Pull before adding files to avoid rebase conflicts
    print("Pulling latest changes...")
    pull_result = subprocess.run(
        ["git", "pull", "--rebase", "origin", "main"],
        capture_output=True,
        text=True,
    )
    if pull_result.returncode != 0:
        print(f"Pull warning: {pull_result.stderr}")
    
    # 追加
    subprocess.run(["git", "add", filename], check=True)
    print(f"Added {filename} to git")

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        capture_output=True,
    )

    if result.returncode != 0:  # 変更がある場合
        date_str = os.path.basename(filename).replace(".md", "")
        
        print(f"Committing changes for {date_str}...")
        subprocess.run(
            ["git", "commit", "-m", f"Add AI news for {date_str}"],
            check=True,
        )
        
        print("Pushing to remote...")
        subprocess.run(["git", "push"], check=True)
        print(f"[{datetime.now(jst).strftime('%Y-%m-%d %H:%M:%S JST')}] Successfully committed and pushed: {filename}")
    else:
        print(f"[{datetime.now(jst).strftime('%Y-%m-%d %H:%M:%S JST')}] No changes detected, skipping commit")


def main():
    jst = timezone(timedelta(hours=9))
    print(f"[{datetime.now(jst).strftime('%Y-%m-%d %H:%M:%S JST')}] === AI News Bot ===")
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

    # GitHub ActionsまたはRender環境でコミット
    if os.environ.get("GITHUB_ACTIONS") or os.environ.get("RENDER"):
        git_commit_and_push(filename)
    else:
        print(f"[{datetime.now(jst).strftime('%Y-%m-%d %H:%M:%S JST')}] Skipping git operations (local environment)")
    
    print(f"[{datetime.now(jst).strftime('%Y-%m-%d %H:%M:%S JST')}] === Completed ===")


if __name__ == "__main__":
    main()
