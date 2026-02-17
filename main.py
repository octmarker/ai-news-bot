#!/usr/bin/env python3
"""AI News Bot - Google Cloud Functions 版
マルチカテゴリニュース収集（AI、政治経済、論文、セレンディピティ）をGitHubにコミット
"""

import os
import json
import re as _re
import functions_framework
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

import trafilatura

# Import GNews client
from gnews_client import collect_multi_category_articles

from google import genai
from google.genai import types
from github import Github, Auth
from github.GithubException import GithubException


# タイムゾーン設定
JST = timezone(timedelta(hours=9))


def get_jst_now() -> datetime:
    """現在のJST時刻を取得"""
    return datetime.now(JST)


def log(message: str):
    """タイムスタンプ付きログ出力"""
    now = get_jst_now()
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S JST')}] {message}")


def get_ai_prompt(today: str, yesterday: str) -> str:
    """AIニュース用プロンプト"""
    return f"""今日は{today}です。あなたはAI開発ツール専門のテクニカルニュースキュレーターです。

【重要な制約】
- **日本とアメリカのニュースソースのみを対象としてください**（日本語または英語の記事）
- **中国語（簡体字・繁体字）のソースは絶対に除外してください**
- **台湾、香港、中国本土のメディアは除外**（例：數位時代、工商時報、思否、硬是要學など）
- 必ず{yesterday}〜{today}に公開された記事のみを含めてください
- 記事のURLや本文に含まれる日付を確認し、それ以前の古い記事は絶対に含めないでください
- 該当期間のニュースが見つからない場合は、無理に古い記事を含めず「該当なし」としてください

【収集対象】
以下に関する**技術的なリリース・アップデート情報**を収集してください：
- Google Antigravity（新機能、Skills、アップデート）
- Claude Code / Claude（新機能、MCP、API変更）
- Gemini / Google AI（新モデル、新機能、SDK更新）
- ChatGPT / OpenAI（新機能、GPTs、API更新）
- その他AIコーディングツール（Cursor、GitHub Copilot、Windsurf等）

【優先するコンテンツ】
✅ 新機能・新スキルのリリース発表
✅ バージョンアップ・チェンジログ
✅ 新API・SDK・ライブラリの公開
✅ 公式ブログ・GitHubリリースノート
✅ 開発者向けの技術解説記事

【除外するコンテンツ】
❌ 経営戦略・資金調達・人事ニュース
❌ AIリスク・規制・倫理に関する意見記事
❌ 一般ユーザー向けの使い方ガイド
❌ 噂・リーク情報

【出力要件】
- 日本とアメリカのソースから情報を取得する
- 合計5〜7件程度に厳選
- 各ニュースには**何が新しくなったか**を具体的に記載
- 出力は日本語で統一

【出力フォーマット】
---
## [ツール/プラットフォーム名]

### [リリース・アップデート内容]
公開日: YYYY-MM-DD
[何が新しくなったかを1〜2行で具体的に説明]
→ [ソースURL]

---

該当期間に技術的なリリース情報がない場合は「本日の主要なリリース情報はありませんでした」と記載してください。"""


def get_ai_candidate_prompt(
    today: str, yesterday: str,
    boosted_keywords: list = None, suppressed_keywords: list = None,
    preferred_sources: list = None, category_distribution: dict = None,
    serendipity_ratio: float = 0.0, learning_phase: int = 0
) -> str:
    """AIニュース候補生成用プロンプト（パーソナライズド版）"""
    boost_section = ""
    if boosted_keywords:
        boost_section = f"\n🔥 **特に優先**: {', '.join(boosted_keywords)}"

    suppress_section = ""
    if suppressed_keywords:
        suppress_section = f"\n⬇️ **優先度下げる**: {', '.join(suppressed_keywords)}"

    # Phase 2+: 信頼ソースとカテゴリ配分
    source_section = ""
    if learning_phase >= 2 and preferred_sources:
        source_section = f"\n📰 **信頼するソース**: {', '.join(preferred_sources)}"

    # カテゴリ別最低件数の保証（Phase 2+）
    category_section = ""
    if learning_phase >= 2 and category_distribution:
        cat_labels = {
            "ai": "AI・テクノロジー",
            "finance": "金融・経済",
            "politics": "政治・外交",
            "other": "その他"
        }
        # 最低件数を明示
        category_section = """

【重要：カテゴリ別最低件数の保証】
以下の最低件数を必ず確保してください。ブーストワードは各カテゴリ内での優先順位付けに使用します：
- AI・テクノロジー: 最低5〜6件（AIツール、LLM、機械学習関連）
- 金融・経済: 最低4〜5件（日銀、為替、金融政策など）
- 政治・外交: 最低2〜3件（選挙、国会、外交など）

※ブーストワードは全体ではなく、各カテゴリ内でのランキングに反映させてください
※合計10〜15件の中で、上記の最低件数を満たしつつバランスを取ってください"""
    elif learning_phase < 2:
        # Phase 0-1の場合も最低件数を保証
        category_section = """

【カテゴリ別最低件数の保証】
- AI・テクノロジー: 最低5〜6件
- 金融・経済: 最低4〜5件
- 政治・外交: 最低2〜3件"""

    # Phase 3: セレンディピティ枠
    serendipity_section = ""
    if learning_phase >= 3 and serendipity_ratio > 0:
        serendipity_section = """

🎲 **セレンディピティ枠**: 候補のうち2〜3件は、上記の優先トピック以外の
意外性のある記事を含めてください（フィルターバブル防止）。"""

    return f"""今日は{today}です。ニュース候補を10〜15件収集してください。

【重要な制約 - 必ず守ること】
1. **日付の厳守**: {yesterday}〜{today}に公開された記事のみ
   - 記事のURLや本文に含まれる公開日を必ず確認すること
   - 古い記事（1週間以上前など）は絶対に含めない
   - 日付が不明な記事は除外する
2. **ソースの制限**: 日本とアメリカのニュースソースのみ（日本語または英語の記事）
   - 中国語（簡体字・繁体字）のソースは絶対に除外
   - 台湾、香港、中国本土のメディアは除外（例：數位時代、工商時報、思否、硬是要學など）
{boost_section}{suppress_section}{source_section}{category_section}{serendipity_section}

【収集対象とカテゴリ構成】
必ず以下のカテゴリ構成を守り、合計10〜15件を収集してください：

1️⃣ **AI・テクノロジー（5〜6件以上）** ← 最優先カテゴリ
   - AI開発ツール（Gemini, Claude, ChatGPT, Cursor, GitHub Copilot, Windsurf等）の新機能・アップデート
   - LLM/機械学習の技術トレンド・新モデル・ベンチマーク
   - AIエージェント・MCP・ツール連携の新発表
   - AI API・SDK・ライブラリの新リリース
   - 開発者向けの重要な発表・公式ブログ記事

2️⃣ **金融・経済（4〜5件）**
   - 日銀の金融政策・政策金利決定
   - 為替・円高円安の動向
   - GDP・インフレなどマクロ経済指標
   - FRBの金融政策
   - 株式市場の重要な動き

3️⃣ **政治・外交（2〜3件）**
   - 衆院選など選挙関連
   - 国会・内閣の重要決定
   - 日米外交・国際会議
   - 重要法案の可決

⚠️ **重要**: ブーストワードは各カテゴリ内での記事選択に使用し、カテゴリ間のバランスは崩さないこと

【出力フォーマット】
必ず以下の形式で10〜15件出力してください：

1. [記事タイトル（英語なら日本語訳）]
   📅 公開日: YYYY-MM-DD | 📰 [サイト名] | 💡 [一言メモ（20字以内）]
   URL: [記事URL]

2. [記事タイトル]
   📅 公開日: YYYY-MM-DD | 📰 [サイト名] | 💡 [一言メモ]
   URL: [記事URL]

... (10〜15件まで)

※公開日が確認できない記事は含めないこと

該当期間にニュースが見つからない場合は「該当なし」と記載してください。"""


def get_gnews_filtering_prompt(
    today: str, yesterday: str, articles: List[Dict[str, Any]],
    boosted_keywords: list = None, suppressed_keywords: list = None,
    preferred_sources: list = None, category_distribution: dict = None,
    serendipity_ratio: float = 0.0, learning_phase: int = 0,
    learned_interests: dict = None
) -> str:
    """GNews記事フィルタリング用プロンプト（パーソナライズド版）

    事前に収集された記事リストから、ユーザーの選好に基づいて10-15件を選択・ランク付けする
    """
    boost_section = ""
    if boosted_keywords:
        boost_section = f"\n🔥 **特に優先**: {', '.join(boosted_keywords)}"

    suppress_section = ""
    if suppressed_keywords:
        suppress_section = f"\n⬇️ **優先度下げる**: {', '.join(suppressed_keywords)}"

    # preferred_sourcesから日本語ソースのみ抽出 + learned_interestsのソースも含める
    all_sources = set()
    if preferred_sources:
        all_sources.update(preferred_sources)
    if learned_interests:
        for src, score in learned_interests.get("sources", {}).items():
            if score >= 0.5:
                all_sources.add(src)
    source_section = ""
    if learning_phase >= 2 and all_sources:
        source_section = f"\n📰 **信頼するソース（部分一致で判定）**: {', '.join(all_sources)}"

    # カテゴリ配分を動的に生成
    category_lines = []
    category_label_map = {"ai": "AI・テクノロジー", "finance": "経済・金融", "politics": "政治・政策"}
    total_target = 12  # 目標記事数
    if category_distribution:
        for key, label in category_label_map.items():
            ratio = category_distribution.get(key, 0)
            if ratio <= 0:
                continue
            count = max(1, round(total_target * ratio))
            category_lines.append(f"- {label}: 約{count}件")
    else:
        category_lines = ["- AI・テクノロジー: 約6件", "- 経済・金融: 約4件", "- 政治・政策: 約2件"]
    category_section = "\n\n【カテゴリ別目安件数】\n" + "\n".join(category_lines)

    serendipity_section = ""
    if learning_phase >= 3 and serendipity_ratio > 0:
        serendipity_section = """

🎲 **セレンディピティ枠**: 候補のうち2〜3件は、上記の優先トピック以外の
意外性のある記事を含めてください（フィルターバブル防止）。"""

    # ユーザーの興味プロファイル（交差点推論用）
    interest_profile_section = ""
    if learned_interests:
        top_topics = sorted(
            [(t, s) for t, s in learned_interests.get("topics", {}).items() if s >= 0.3],
            key=lambda x: -x[1]
        )
        if top_topics:
            topic_str = ", ".join(f"{t}({s:.1f})" for t, s in top_topics[:10])
            interest_profile_section = f"""

【ユーザーの興味プロファイル（スコア順）】
{topic_str}

上記の興味が複数交差する記事（例: AI×金融政策、コーディング×新モデル）は、
単一キーワードのみ一致する記事より優先すること。"""

    # Format articles list for the prompt
    articles_text = ""
    for i, article in enumerate(articles, 1):
        articles_text += f"""
{i}. {article['title']}
   📰 {article['source']} | 📅 {article['published_at'][:10]}
   💡 {article['description'][:100]}...
   🔗 {article['url']}
   カテゴリ: {article.get('category', '未分類')}
"""

    return f"""今日は{today}です。以下の記事リストから、ユーザーの選好に基づいて10〜15件を選択してください。

【重要な制約】
1. **以下のリストにある記事のみを選択すること**（新しい記事を検索しない）
2. **日付の確認**: {yesterday}〜{today}に公開された記事を優先
3. **推測記事の生成禁止**: リストにない記事を作らない
{boost_section}{suppress_section}{source_section}{category_section}{serendipity_section}{interest_profile_section}

【選択基準】
- ユーザーの興味プロファイルに合致する記事を優先
- 複数の興味が交差する記事は特に高く評価
- 抑制ワードに関連する記事は優先度を下げる
- 信頼するソースの記事を優先（部分一致で判定）

【記事リスト】
{articles_text}

【出力フォーマット】
選択した記事を重要度順に10〜15件出力してください。必ず以下の形式を守ること：

**1️⃣ AI・テクノロジー**

1. [記事タイトル]
   📅 公開日: YYYY-MM-DD | 📰 [サイト名] | 💡 [一言メモ（20字以内）]
   URL: [記事URL]

2. [記事タイトル]
   📅 公開日: YYYY-MM-DD | 📰 [サイト名] | 💡 [一言メモ]
   URL: [記事URL]

**2️⃣ 経済・金融**

3. [記事タイトル]
   📅 公開日: YYYY-MM-DD | 📰 [サイト名] | 💡 [一言メモ]
   URL: [記事URL]

... (10〜15件まで)

⚠️ **重要**: 必ずリストにある記事のみを使用し、URLは元のURLをそのまま使うこと
"""


def get_politics_prompt(today: str, yesterday: str) -> str:
    """政治経済ニュース用プロンプト"""
    return f"""今日は{today}です。あなたは政治経済専門のニュースキュレーターです。

【重要な制約】
- **日本とアメリカのニュースソースのみを対象としてください**（日本語または英語の記事）
- **中国語（簡体字・繁体字）のソースは絶対に除外してください**
- **台湾、香港、中国本土のメディアは除外**
- 必ず{yesterday}〜{today}に公開された記事のみを含めてください
- 該当期間のニュースが見つからない場合は「該当なし」としてください

【収集対象】
- 日本国内政治（国会、内閣、政策決定、選挙）
- アメリカ政治（ホワイトハウス、議会、大統領令）
- マクロ経済（GDP、金利、為替、株式市場の重要な動き）
- 中央銀行政策（日銀、FRB の政策決定）
- 貿易・通商（関税、FTA、サプライチェーン問題）
- 重要な外交ニュース（日米関係、G7/G20など）

【優先するコンテンツ】
✅ 政策決定・法案可決
✅ 経済指標の発表
✅ 中央銀行の重要発表
✅ 国際会議・首脳会談

【除外するコンテンツ】
❌ ゴシップ・スキャンダル
❌ 憶測・予測記事
❌ ローカルニュース

【出力要件】
- 合計5〜7件程度に厳選
- 各ニュースには何が決まったか/起きたかを具体的に記載
- 出力は日本語で統一

【出力フォーマット】
---
## [カテゴリ: 国内政治/米国政治/経済/金融政策/外交]

### [ニュースタイトル]
日付: YYYY-MM-DD
[何が起きたかを1〜2行で具体的に説明]
→ [ソースURL]

---

該当期間に重要なニュースがない場合は「本日の主要なニュースはありませんでした」と記載してください。"""


def get_papers_prompt(today: str) -> str:
    """AI論文サーベイ用プロンプト"""
    return f"""今日は{today}です。あなたはAI研究論文のキュレーターです。

【収集対象】
過去1週間に発表された重要なAI/ML論文を検索してください：
- arXiv（cs.AI, cs.LG, cs.CL, cs.CV）
- 主要学会（NeurIPS, ICML, ICLR, ACL, EMNLP, CVPR）のプレプリント
- Google Research, DeepMind, OpenAI, Anthropic, Meta AI等の公式発表

【優先トピック】
- LLM / Foundation Models（新しいアーキテクチャ、学習手法）
- Agent / Tool Use（自律エージェント、ツール活用）
- Code Generation（コード生成、プログラム合成）
- Reasoning（推論能力、Chain-of-Thought）
- Multimodal（マルチモーダル、Vision-Language）
- Efficient AI（効率化、量子化、蒸留）

【出力要件】
- 5〜10件程度を厳選
- 重要度の高いものから順に
- 出力は日本語で統一

【出力フォーマット】
---
## [論文タイトル]
**日本語タイトル**: [日本語訳]
**著者**: [主要著者名（所属）]
**発表日**: YYYY-MM-DD
**重要度**: ★★★ / ★★ / ★

### 概要
[論文の主な貢献を2〜3文で説明]

### 注目ポイント
[なぜ重要か、実務への影響を1〜2文で]

→ [arXiv/論文URL]

---

該当期間に重要な論文がない場合は「今週の注目論文はありませんでした」と記載してください。"""


def get_serendipity_prompt(today: str, yesterday: str) -> str:
    """セレンディピティニュース用プロンプト"""
    return f"""今日は{today}です。あなたは「フィルターバブル破壊」専門のニュースキュレーターです。

【ミッション】
テクノロジーや経済に関心が強い読者に、普段触れない分野の興味深いニュースを届けてください。
意外な発見や新しい視点を提供することが目標です。

【重要な制約】
- **日本とアメリカのニュースソースのみ**（日本語または英語の記事）
- **中国語（簡体字・繁体字）のソースは絶対に除外**

【収集対象（ランダムに選択）】
以下の分野から、{yesterday}〜{today}の興味深いニュースを探してください：

科学・自然:
- 宇宙探査、天文学の新発見
- 生物学、生態系、環境科学
- 物理学、化学の基礎研究
- 気候変動、地球科学

歴史・考古学:
- 新しい考古学的発見
- 歴史的文書の解読
- 文化遺産の保存

芸術・文化:
- 美術展、音楽イベント
- 建築、デザインの新潮流
- 文学賞、映画祭

心理学・哲学:
- 認知科学の研究
- 社会心理学の知見
- 哲学的議論

国際・社会:
- 途上国の発展
- 社会運動、市民活動
- 教育、医療の革新

【除外するコンテンツ】
❌ 芸能ゴシップ、セレブニュース
❌ スポーツの試合結果
❌ 犯罪・事件報道
❌ AI・テクノロジー関連（他カテゴリで収集済み）
❌ 政治・経済ニュース（他カテゴリで収集済み）

【出力要件】
- 3〜5件を厳選
- 「へぇ、そうなんだ」と思える意外性のあるものを優先
- 出力は日本語で統一

【出力フォーマット】
---
## [分野: 科学/歴史/芸術/心理学/国際]

### [ニュースタイトル]
日付: YYYY-MM-DD
[何が発見・発表されたかを1〜2行で具体的に説明]

なぜ面白いか: [この発見/ニュースの意外性や興味深さを1文で]

→ [ソースURL]

---

該当期間に興味深いニュースがない場合は「今回のセレンディピティニュースはありませんでした」と記載してください。"""


def get_news_categories(today: str, yesterday: str) -> Dict[str, Dict[str, Any]]:
    """ニュースカテゴリの設定を返す"""
    return {
        "ai": {
            "name": "AI Tech News",
            "daily": True,
            "generate_script": True,
            "prompt": get_ai_prompt(today, yesterday),
        },
        "politics": {
            "name": "Politics & Economy News",
            "daily": True,
            "generate_script": False,
            "prompt": get_politics_prompt(today, yesterday),
        },
        "papers": {
            "name": "AI Papers Survey",
            "daily": False,
            "weekday": 0,  # 月曜日のみ
            "generate_script": False,
            "prompt": get_papers_prompt(today),
        },
        "serendipity": {
            "name": "Serendipity News",
            "daily": False,
            "every_n_days": 3,  # 3日に1回
            "generate_script": False,
            "prompt": get_serendipity_prompt(today, yesterday),
        },
    }


def collect_news(category_id: str, config: Dict[str, Any]) -> str:
    """Gemini APIのGoogle Search groundingを使ってニュースを収集"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    
    log(f"Collecting {config['name']}...")

    # Google Search grounding tool
    grounding_tool = types.Tool(
        google_search=types.GoogleSearch()
    )
    
    gen_config = types.GenerateContentConfig(
        tools=[grounding_tool]
    )
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=config["prompt"],
        config=gen_config,
    )
    
    log(f"{config['name']} collection completed")
    
    return response.text



def load_user_preferences() -> Dict[str, Any]:
    """GitHubからuser_preferences.jsonを読み込む"""
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        log("GITHUB_TOKEN not set, using default preferences")
        return get_default_preferences()
    
    repo_name = os.environ.get("GITHUB_REPOSITORY", "octmarker/ai-news-bot")
    
    try:
        auth = Auth.Token(github_token)
        g = Github(auth=auth)
        repo = g.get_repo(repo_name)
        
        file_content = repo.get_contents("user_preferences.json", ref="main")
        preferences = json.loads(file_content.decoded_content.decode('utf-8'))
        log("Loaded user preferences from GitHub")
        return preferences
    except GithubException as e:
        if e.status == 404:
            log("user_preferences.json not found, using defaults")
            return get_default_preferences()
        raise


def get_default_preferences() -> Dict[str, Any]:
    """デフォルトのユーザー設定を返す"""
    return {
        "learning_phase": 0,
        "selection_history": [],
        "learned_interests": {
            "topics": {},
            "sources": {},
            "categories": {}
        },
        "search_config": {
            "boosted_keywords": [],
            "suppressed_keywords": [],
            "preferred_sources": [],
            "category_distribution": {},
            "serendipity_ratio": 0.0
        },
        "last_updated": None
    }


def _fetch_one_article(article: Dict[str, Any]) -> Dict[str, Any]:
    """1記事の本文をtrafilaturaで取得"""
    try:
        downloaded = trafilatura.fetch_url(article["url"])
        if not downloaded:
            return None
        text = trafilatura.extract(downloaded)
        if not text or len(text) < 100:
            return None
        article["content"] = text[:5000]
        return article
    except Exception as e:
        log(f"  Failed to fetch {article['url'][:60]}: {e}")
        return None


def fetch_article_contents(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """全記事の本文を並列取得し、取得成功した記事のみ返す"""
    log(f"Fetching article contents for {len(articles)} articles...")
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_fetch_one_article, a): a for a in articles}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
    log(f"Successfully fetched {len(results)}/{len(articles)} articles")
    return results


def generate_summary(client, title: str, content: str) -> Optional[Dict[str, Any]]:
    """1記事のGemini要約を生成"""
    prompt = f"""あなたはニュース記事の要約エキスパートです。以下の記事を日本語で要約してください。

【記事タイトル】
{title}

【記事本文】
{content}

【出力形式】
以下のJSON形式で出力してください。JSON以外は出力しないでください：
{{
  "headline": "記事の一言見出し（30字以内）",
  "key_points": ["ポイント1", "ポイント2", "ポイント3"],
  "detailed_summary": "200〜300字の詳細要約。記事の背景、主要な事実、影響や意義を含む",
  "why_it_matters": "なぜこのニュースが重要なのかを1〜2文で"
}}"""

    safety = [
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
    ]
    gen_config = types.GenerateContentConfig(safety_settings=safety)

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=gen_config,
        )
        text = response.text
        import re
        json_match = re.search(r'\{[\s\S]*\}', text)
        if not json_match:
            return None
        return json.loads(json_match.group())
    except Exception as e:
        log(f"  Summary generation failed: {e}")
        return None


def generate_summaries(client, articles: List[Dict[str, Any]], rate_limit: int = 4) -> List[Dict[str, Any]]:
    """フィルタリング済み記事に要約を生成。要約失敗した記事は除外

    rate_limit: 連続リクエスト数（この数ごとに60秒待機）。フィルタリングで1リクエスト消費済みなので
                無料枠(5/分)の場合はデフォルト4で開始
    """
    import time
    log(f"Generating summaries for {len(articles)} articles...")
    results = []
    for i, article in enumerate(articles, 1):
        if i > 1 and (i - 1) % rate_limit == 0:
            log(f"  Rate limit: waiting 60s...")
            time.sleep(60)
            rate_limit = 5  # 2回目以降は5リクエスト/分フルに使える
        log(f"  Summarizing {i}/{len(articles)}: {article['title'][:40]}...")
        summary = generate_summary(client, article["title"], article["content"])
        if summary:
            article["summary"] = summary
            results.append(article)
        else:
            log(f"  Skipped (summary failed): {article['title'][:40]}")
    log(f"Successfully summarized {len(results)}/{len(articles)} articles")
    return results


def _normalize_url_path(url: str) -> str:
    """URLからドメインを除去してパス部分のみ返す（同一記事の異ドメイン配信検出用）"""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    # パス + クエリを正規化（末尾スラッシュ除去）
    return parsed.path.rstrip("/")


def _title_prefix(title: str, length: int = 20) -> str:
    """タイトルの先頭N文字を返す（タイトル類似度の簡易チェック用）"""
    return title.strip()[:length].strip()


def _is_duplicate(article: Dict[str, Any], prev_urls: set, prev_url_paths: set, prev_title_prefixes: set) -> bool:
    """記事が過去の候補と重複しているかを複数シグナルで判定"""
    url = article.get("url", "")
    title = article.get("title", "")

    # 1. URL完全一致
    if url in prev_urls:
        return True

    # 2. URLパス一致（ドメイン違い、同一記事）
    path = _normalize_url_path(url)
    if path and path in prev_url_paths:
        return True

    # 3. タイトル先頭一致
    prefix = _title_prefix(title)
    if prefix and prefix in prev_title_prefixes:
        return True

    return False


def load_previous_candidates(days_back: int = 2) -> tuple:
    """過去の候補ファイルからURL・タイトルを取得し、重複除外に使用する

    Args:
        days_back: 何日前まで遡って重複チェックするか

    Returns:
        (urls: set, url_paths: set, title_prefixes: set)
    """
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        log("GITHUB_TOKEN not set, skipping dedup")
        return set(), set(), set()

    repo_name = os.environ.get("GITHUB_REPOSITORY", "octmarker/ai-news-bot")
    now = get_jst_now()

    all_urls = set()
    all_url_paths = set()
    all_title_prefixes = set()

    try:
        auth = Auth.Token(github_token)
        g = Github(auth=auth)
        repo = g.get_repo(repo_name)

        for days_ago in range(1, days_back + 1):
            date_str = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")

            for ext in [".json", ".md"]:
                path = f"news/{date_str}-candidates{ext}"
                try:
                    file_content = repo.get_contents(path, ref="main")
                    text = file_content.decoded_content.decode("utf-8")

                    if ext == ".json":
                        data = json.loads(text)
                        for a in data.get("articles", []):
                            url = a.get("url", "")
                            title = a.get("title", "")
                            if url:
                                all_urls.add(url)
                                all_url_paths.add(_normalize_url_path(url))
                            if title:
                                all_title_prefixes.add(_title_prefix(title))
                    else:
                        urls = set(_re.findall(r'URL:\s*(https?://\S+)', text))
                        all_urls.update(urls)
                        for url in urls:
                            all_url_paths.add(_normalize_url_path(url))
                        # mdからタイトルも抽出（番号付きリスト形式）
                        titles = _re.findall(r'^\d+\.\s+(.+)$', text, _re.MULTILINE)
                        for title in titles:
                            all_title_prefixes.add(_title_prefix(title))

                    log(f"Loaded previous candidates from {path}")
                    break  # json found, skip md
                except GithubException as e:
                    if e.status == 404:
                        continue
                    raise

        log(f"Dedup data: {len(all_urls)} URLs, {len(all_url_paths)} paths, {len(all_title_prefixes)} title prefixes")
        return all_urls, all_url_paths, all_title_prefixes

    except Exception as e:
        log(f"Error loading previous candidates: {e}")
        return set(), set(), set()


def collect_candidates(today: str, yesterday: str, preferences: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """ニュース候補を収集（GNews API + 本文取得 + Gemini フィルタリング + 要約）"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)

    log("Collecting news candidates with GNews API...")

    # user_preferencesから検索条件を取得
    search_config = preferences.get("search_config", {})
    boosted = search_config.get("boosted_keywords", [])
    suppressed = search_config.get("suppressed_keywords", [])
    preferred_sources = search_config.get("preferred_sources", [])
    category_distribution = search_config.get("category_distribution", {})
    serendipity_ratio = search_config.get("serendipity_ratio", 0.0)
    learning_phase = preferences.get("learning_phase", 0)
    learned_interests = preferences.get("learned_interests", {})

    # Stage 1: Collect articles from GNews API
    try:
        articles = collect_multi_category_articles(
            preferences=preferences,
            total_articles=30
        )
        log(f"Collected {len(articles)} articles from GNews API")

        if not articles:
            log("No articles collected from GNews API")
            return None
    except Exception as e:
        log(f"Error collecting from GNews API: {e}")
        return None

    # Stage 1.5: Remove articles that appeared in previous candidates (multi-signal dedup)
    prev_urls, prev_url_paths, prev_title_prefixes = load_previous_candidates(days_back=2)
    if prev_urls or prev_title_prefixes:
        before = len(articles)
        articles = [a for a in articles if not _is_duplicate(a, prev_urls, prev_url_paths, prev_title_prefixes)]
        removed = before - len(articles)
        if removed > 0:
            log(f"Removed {removed} duplicate articles from previous days")

    # Stage 2: Fetch article contents (filter out failures)
    articles = fetch_article_contents(articles)
    if not articles:
        log("No articles could be fetched")
        return None

    # Stage 3: Filter and rank with Gemini
    log("Filtering articles with Gemini...")

    prompt = get_gnews_filtering_prompt(
        today, yesterday, articles, boosted, suppressed,
        preferred_sources=preferred_sources,
        category_distribution=category_distribution,
        serendipity_ratio=serendipity_ratio,
        learning_phase=learning_phase,
        learned_interests=learned_interests
    )

    gen_config = types.GenerateContentConfig()

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=gen_config,
    )

    # Geminiが選んだ記事番号を抽出して、元のarticlesリストからマッチさせる
    selected = parse_filtered_articles(response.text, articles)
    log(f"Gemini selected {len(selected)} articles")

    if not selected:
        log("No articles selected by Gemini")
        return None

    # Stage 4: Generate summaries for selected articles
    selected = generate_summaries(client, selected)
    if not selected:
        log("No articles could be summarized")
        return None

    return selected


def parse_filtered_articles(gemini_response: str, original_articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Geminiのフィルタリング結果からURLでマッチして選択された記事を返す"""
    import re
    selected = []
    seen_urls = set()

    # URLを抽出
    url_pattern = re.compile(r'URL:\s*\[?(https?://[^\s\]\)]+)')
    for match in url_pattern.finditer(gemini_response):
        url = match.group(1)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        # 元の記事リストからURLでマッチ
        for article in original_articles:
            if article["url"] == url:
                selected.append(article)
                break

    return selected


def collect_candidates_legacy(today: str, yesterday: str, preferences: Dict[str, Any]) -> str:
    """レガシー版：Gemini Groundingを使った候補収集（フォールバック用）"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    
    log("Using legacy Gemini Grounding method...")

    search_config = preferences.get("search_config", {})
    boosted = search_config.get("boosted_keywords", [])
    suppressed = search_config.get("suppressed_keywords", [])
    preferred_sources = search_config.get("preferred_sources", [])
    category_distribution = search_config.get("category_distribution", {})
    serendipity_ratio = search_config.get("serendipity_ratio", 0.0)
    learning_phase = preferences.get("learning_phase", 0)

    prompt = get_ai_candidate_prompt(
        today, yesterday, boosted, suppressed,
        preferred_sources=preferred_sources,
        category_distribution=category_distribution,
        serendipity_ratio=serendipity_ratio,
        learning_phase=learning_phase
    )

    grounding_tool = types.Tool(
        google_search=types.GoogleSearch()
    )
    
    gen_config = types.GenerateContentConfig(
        tools=[grounding_tool]
    )
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=gen_config,
    )
    
    log("Legacy candidate collection completed")
    
    return response.text


def run_candidate_mode() -> Tuple[bool, str]:
    """候補生成モードのメイン処理"""
    log("=== AI News Bot (Candidate Mode) ===")
    
    try:
        now = get_jst_now()
        today = now.strftime("%Y年%m月%d日")
        yesterday = (now - timedelta(days=1)).strftime("%Y年%m月%d日")
        date_str = now.strftime("%Y-%m-%d")
        
        # ユーザー設定を読み込み（Vercel Cronで毎日更新済み）
        preferences = load_user_preferences()

        # 候補を収集（本文取得 + フィルタリング + 要約込み）
        articles = collect_candidates(today, yesterday, preferences)

        if not articles:
            return False, "No candidates collected"

        # JSON形式で出力
        output = {
            "date": date_str,
            "articles": []
        }
        for i, article in enumerate(articles, 1):
            output["articles"].append({
                "number": i,
                "title": article["title"],
                "source": article["source"],
                "description": article["description"],
                "url": article["url"],
                "category": article.get("category", "未分類"),
                "published_at": article.get("published_at", "")[:10],
                "summary": article.get("summary", {})
            })

        candidates_content = json.dumps(output, ensure_ascii=False, indent=2)

        # GitHubにプッシュ
        candidates_path = f"news/{date_str}-candidates.json"
        push_to_github(
            file_path=candidates_path,
            content=candidates_content,
            commit_message=f"Add news candidates for {date_str}"
        )

        log(f"Saved: {candidates_path} ({len(output['articles'])} articles)")
        log("=== Candidate Mode Completed ===")

        return True, f"Saved: {candidates_path}"
        
    except Exception as e:
        error_msg = f"Error: {type(e).__name__}: {e}"
        log(f"CRITICAL ERROR: {error_msg}")
        import traceback
        traceback.print_exc()
        return False, error_msg


def generate_script(news_content: str) -> str:
    """収集したニュースから番組原稿を生成"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    
    log("Generating news script...")

    prompt = f"""# 役割
あなたは朝のAIニュース番組の原稿ライターです。視聴者にわかりやすく、親しみやすいトーンでAI業界の最新ニュースを伝える原稿を作成してください。

# 入力
以下のニュースネタから原稿を作成してください：

{news_content}

# 出力形式
以下の構成で原稿を作成してください：

## 1. オープニング（2〜3文）
- 「おはようございます」から始める挨拶
- 本日のニュースの概要を軽く予告

## 2. ニュース本文（ネタごとに1セクション）
各ニュースは以下の構成で：
- **見出し**：ニュースのタイトル（【ニュース①：〇〇】の形式）
- **導入**：話題の切り替えを示す短いつなぎ（「まずは〜」「続いては〜」「最後は〜」など）
- **本文**：3〜4段落で構成
  - 何が起きたか（事実）
  - 背景や文脈の補足
  - 意義や影響についての一言コメント
- 専門用語は簡潔に補足説明を入れる
- 金額は日本円換算も併記（概算でOK）

## 3. クロージング（2〜3文）
- ニュース全体の簡単なまとめ
- 「良い一日を！」などポジティブな締めくくり

# トーン・文体ガイドライン
- 親しみやすく、堅すぎない敬体（です・ます調）
- 読み上げやすいリズム感を意識
- 「〜ですね」「〜の形です」など柔らかい表現を適度に使用
- 感嘆符（！）は控えめに（クロージングで1〜2回程度）
- 絵文字は使用しない

# 注意事項
- 提供されたネタの順番は重要度や話題のつながりで並び替えてOK
- 同じ企業の話題が複数ある場合はまとめて扱う
- URLは原稿内に含めない（読み上げ用のため）
- 1ニュースあたり150〜200文字程度を目安に"""

    gen_config = types.GenerateContentConfig()
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=gen_config,
    )
    
    log("Script generation completed")
    
    return response.text


def push_to_github(file_path: str, content: str, commit_message: str) -> bool:
    """GitHub APIを使用してファイルをコミット・プッシュ"""
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        raise ValueError("GITHUB_TOKEN is not set")
    
    repo_name = os.environ.get("GITHUB_REPOSITORY", "octmarker/ai-news-bot")
    
    log(f"Pushing to GitHub: {file_path}")
    
    try:
        # 新しい認証方式を使用
        auth = Auth.Token(github_token)
        g = Github(auth=auth)
        repo = g.get_repo(repo_name)
        
        # ファイルが存在するかチェック
        try:
            existing_file = repo.get_contents(file_path, ref="main")
            # ファイルが存在する場合は更新
            repo.update_file(
                path=file_path,
                message=commit_message,
                content=content,
                sha=existing_file.sha,
                branch="main"
            )
            log(f"Updated existing file: {file_path}")
        except GithubException as e:
            if e.status == 404:
                # ファイルが存在しない場合は新規作成
                repo.create_file(
                    path=file_path,
                    message=commit_message,
                    content=content,
                    branch="main"
                )
                log(f"Created new file: {file_path}")
            else:
                raise
        
        return True
        
    except GithubException as e:
        log(f"GitHub API Error: {e.status} - {e.data.get('message', 'Unknown error')}")
        raise
    except Exception as e:
        log(f"Error pushing to GitHub: {e}")
        raise


def run_news_bot() -> Tuple[bool, str]:
    """ニュースボットのメイン処理"""
    log("=== AI News Bot (Multi-Category) ===")
    
    try:
        now = get_jst_now()
        today = now.strftime("%Y年%m月%d日")
        yesterday = (now - timedelta(days=1)).strftime("%Y年%m月%d日")
        date_str = now.strftime("%Y-%m-%d")
        current_weekday = now.weekday()  # 0=月曜, 6=日曜
        
        log(f"Date: {date_str}, Weekday: {current_weekday}")
        
        # カテゴリ設定を取得
        categories = get_news_categories(today, yesterday)
        
        results = []
        
        for category_id, config in categories.items():
            # 実行判定
            if config.get("daily"):
                should_run = True
            elif config.get("every_n_days"):
                # N日に1回（日付を基準に判定）
                day_of_year = now.timetuple().tm_yday
                should_run = (day_of_year % config["every_n_days"] == 0)
            else:
                # 特定曜日のみ
                should_run = (current_weekday == config.get("weekday", 0))
            
            if not should_run:
                log(f"Skipping {config['name']} (not scheduled today)")
                continue
            
            log(f"Processing: {config['name']}")
            
            # 1. ニュース収集
            news_content = collect_news(category_id, config)
            
            if not news_content:
                log(f"No content for {config['name']}")
                continue
            
            # 2. ニュースファイルを保存
            news_path = f"news/{date_str}-{category_id}.md"
            news_file_content = f"# {config['name']} - {date_str}\n\n{news_content}"
            
            push_to_github(
                file_path=news_path,
                content=news_file_content,
                commit_message=f"Add {config['name']} for {date_str}"
            )
            log(f"Saved: {news_path}")
            results.append(news_path)
            
            # 3. 原稿生成（必要な場合のみ）
            if config.get("generate_script"):
                # 「主要なリリース情報がありませんでした」の場合はスキップ
                skip_keywords = ["主要なリリース情報はありませんでした", "主要なニュースはありませんでした", "注目論文はありませんでした"]
                should_generate = not any(kw in news_content for kw in skip_keywords)
                
                if should_generate:
                    log("Generating script...")
                    script_content = generate_script(news_content)
                    
                    if script_content:
                        script_path = f"scripts/{date_str}-{category_id}.md"
                        script_file_content = f"# {config['name']} Script - {date_str}\n\n{script_content}"
                        
                        push_to_github(
                            file_path=script_path,
                            content=script_file_content,
                            commit_message=f"Add {config['name']} script for {date_str}"
                        )
                        log(f"Saved script: {script_path}")
                        results.append(script_path)
                else:
                    log("Skipping script generation (no major news)")
        
        log("=== Completed Successfully ===")
        return True, f"Saved files: {', '.join(results)}"
        
    except Exception as e:
        error_msg = f"Error: {type(e).__name__}: {e}"
        log(f"CRITICAL ERROR: {error_msg}")
        import traceback
        traceback.print_exc()
        return False, error_msg


# Cloud Functions エントリーポイント (HTTP トリガー)
@functions_framework.http
def main(request):
    """Cloud Functions HTTP エントリーポイント
    
    Query Parameters:
        mode: 'candidate' (default) or 'legacy'
    """
    log("Function triggered via HTTP")
    
    # モード判定（デフォルトは候補モード）
    mode = request.args.get('mode', 'candidate')
    
    if mode == 'legacy':
        log("Running in legacy mode")
        success, message = run_news_bot()
    else:
        log("Running in candidate mode")
        success, message = run_candidate_mode()
    
    if success:
        return {
            "status": "success",
            "mode": mode,
            "message": message,
            "timestamp": get_jst_now().isoformat()
        }, 200
    else:
        return {
            "status": "error",
            "mode": mode,
            "message": message,
            "timestamp": get_jst_now().isoformat()
        }, 500


# Cloud Functions エントリーポイント (Pub/Sub トリガー - Cloud Scheduler用)
@functions_framework.cloud_event
def scheduled_main(cloud_event):
    """Cloud Functions Pub/Sub エントリーポイント (Cloud Scheduler から呼び出し)
    
    デフォルトで候補モードを使用
    """
    log("Function triggered via Cloud Scheduler (Pub/Sub)")
    
    # 環境変数でモード切り替え（オプション）
    mode = os.environ.get("NEWS_BOT_MODE", "candidate")
    
    if mode == "legacy":
        success, message = run_news_bot()
    else:
        success, message = run_candidate_mode()
    
    if success:
        log(f"Scheduled execution completed: {message}")
    else:
        log(f"Scheduled execution failed: {message}")
        raise Exception(message)  # エラーを返してリトライを促す


# ローカル実行用
if __name__ == "__main__":
    import sys
    
    log("Running locally...")
    
    # コマンドライン引数でモード切り替え
    mode = sys.argv[1] if len(sys.argv) > 1 else "candidate"
    
    if mode == "legacy":
        log("Running in legacy mode")
        success, message = run_news_bot()
    else:
        log("Running in candidate mode")
        success, message = run_candidate_mode()
    
    print(f"\nResult: {'Success' if success else 'Failed'}")
    print(f"Message: {message}")

