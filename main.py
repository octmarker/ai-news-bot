#!/usr/bin/env python3
"""AI News Bot - Google Cloud Functions 版
マルチカテゴリニュース収集（AI、政治経済、論文、セレンディピティ）をGitHubにコミット
"""

import os
import json
import functions_framework
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any, List
from collections import Counter

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


# カテゴリ分類用キーワード定数
CATEGORY_KEYWORDS = {
    "ai": ["Claude", "Gemini", "ChatGPT", "OpenAI", "Anthropic", "AI", "LLM",
           "Cursor", "Copilot", "エージェント", "機械学習", "GPT", "Windsurf",
           "GitHub Copilot", "MCP", "SDK"],
    "finance": ["日銀", "金融政策", "為替", "円高", "円安", "利上げ", "政策金利",
                "FRB", "GDP", "インフレ", "国債", "株式", "金利", "マクロ経済"],
    "politics": ["衆院選", "選挙", "国会", "内閣", "大統領", "外交", "防衛",
                 "ホワイトハウス", "議会", "法案", "首脳会談"]
}


def determine_learning_phase(preferences: Dict[str, Any]) -> int:
    """selection_historyの蓄積量からPhaseを判定"""
    entries = len(preferences.get("selection_history", []))
    if entries < 3:
        return 0
    elif entries < 7:
        return 1
    elif entries < 14:
        return 2
    else:
        return 3


def classify_topic_category(topic: str) -> str:
    """トピックをカテゴリに分類する"""
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in topic.lower():
                return category
    return "other"


def compute_suppressed_topics(history: List[Dict], phase: int) -> List[str]:
    """候補に出たが選ばれにくいトピックを特定する"""
    candidate_counts = Counter()
    selected_set = Counter()

    for entry in history:
        candidate_topics = entry.get("candidate_topics", [])
        if not candidate_topics:
            continue
        for t in candidate_topics:
            candidate_counts[t] += 1
        for t in entry.get("selected_topics", []):
            selected_set[t] += 1

    suppressed = []
    # Phase 3: より厳しい閾値
    min_appearances = 4 if phase >= 3 else 5
    max_rate = 0.15 if phase >= 3 else 0.20

    for topic, count in candidate_counts.items():
        if count >= min_appearances:
            rate = selected_set.get(topic, 0) / count
            if rate < max_rate:
                suppressed.append(topic)

    return suppressed


def compute_category_distribution(history: List[Dict]) -> Dict[str, float]:
    """選択されたトピックのカテゴリ分布を計算"""
    category_counts = Counter()
    total = 0

    for entry in history:
        for topic in entry.get("selected_topics", []):
            cat = classify_topic_category(topic)
            category_counts[cat] += 1
            total += 1

    if total == 0:
        return {}

    return {cat: round(count / total, 2) for cat, count in category_counts.items()}


def update_preferences(preferences: Dict[str, Any]) -> Dict[str, Any]:
    """selection_historyに基づいてプリファレンスを自動学習更新する"""
    history = preferences.get("selection_history", [])
    phase = determine_learning_phase(preferences)
    old_phase = preferences.get("learning_phase", 0)

    if phase == 0:
        preferences["learning_phase"] = phase
        return preferences

    log(f"Learning Phase: {phase} (entries: {len(history)})")

    now = get_jst_now()

    # トピック・ソース集計（Phase 3では時間減衰あり）
    topic_counts = Counter()
    source_counts = Counter()

    for entry in history:
        weight = 1.0
        if phase >= 3:
            entry_date_str = entry.get("date", "")
            if entry_date_str:
                try:
                    from datetime import date as date_type
                    entry_date = datetime.strptime(entry_date_str, "%Y-%m-%d").date()
                    days_ago = (now.date() - entry_date).days
                    weight = 2.0 if days_ago <= 7 else 1.0
                except ValueError:
                    pass

        for t in entry.get("selected_topics", []):
            topic_counts[t] += weight
        for s in entry.get("selected_sources", []):
            source_counts[s] += weight

    # Phase 1: 基本スコアリング
    if phase >= 1:
        topic_scores = {t: min(c * 0.1, 0.5) for t, c in topic_counts.items()}
        source_scores = {s: min(c * 0.1, 0.5) for s, c in source_counts.items()}

        # 3回以上選ばれたトピック → boost
        boosted = [t for t, c in topic_counts.items() if c >= 3]

        preferences["learned_interests"]["topics"] = topic_scores
        preferences["learned_interests"]["sources"] = source_scores
        preferences["search_config"]["boosted_keywords"] = boosted
        preferences["search_config"]["suppressed_keywords"] = []

    # Phase 2: suppressed、カテゴリ分布、preferred_sources
    if phase >= 2:
        suppressed = compute_suppressed_topics(history, phase)
        preferences["search_config"]["suppressed_keywords"] = suppressed

        cat_dist = compute_category_distribution(history)
        preferences["search_config"]["category_distribution"] = cat_dist
        preferences["learned_interests"]["categories"] = cat_dist

        # ソースのうちスコア上位をpreferred_sourcesに
        sorted_sources = sorted(source_counts.items(), key=lambda x: x[1], reverse=True)
        preferred = [s for s, _ in sorted_sources[:5]]
        preferences["search_config"]["preferred_sources"] = preferred

    # Phase 3: 正規化スコア + セレンディピティ
    if phase >= 3:
        max_topic = max(topic_counts.values()) if topic_counts else 1
        topic_scores = {t: round(c / max_topic, 2) for t, c in topic_counts.items()}
        max_source = max(source_counts.values()) if source_counts else 1
        source_scores = {s: round(c / max_source, 2) for s, c in source_counts.items()}

        preferences["learned_interests"]["topics"] = topic_scores
        preferences["learned_interests"]["sources"] = source_scores
        preferences["search_config"]["serendipity_ratio"] = 0.15
    else:
        preferences["search_config"]["serendipity_ratio"] = 0.0

    preferences["learning_phase"] = phase
    preferences["last_updated"] = now.isoformat()

    if phase != old_phase:
        log(f"Phase changed: {old_phase} → {phase}")

    return preferences


def save_preferences_to_github(preferences: Dict[str, Any]):
    """user_preferences.jsonをGitHubに保存"""
    content = json.dumps(preferences, ensure_ascii=False, indent=4)
    push_to_github(
        file_path="user_preferences.json",
        content=content,
        commit_message=f"Update user preferences (Phase {preferences.get('learning_phase', 0)})"
    )
    log("Saved preferences to GitHub")


def collect_candidates(today: str, yesterday: str, preferences: Dict[str, Any]) -> str:
    """ニュース候補を収集（パーソナライズ対応）"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    
    log("Collecting news candidates...")

    # user_preferencesから検索条件を取得
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

    # Google Search grounding tool
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
    
    log("Candidate collection completed")
    
    return response.text


def run_candidate_mode() -> Tuple[bool, str]:
    """候補生成モードのメイン処理"""
    log("=== AI News Bot (Candidate Mode) ===")
    
    try:
        now = get_jst_now()
        today = now.strftime("%Y年%m月%d日")
        yesterday = (now - timedelta(days=1)).strftime("%Y年%m月%d日")
        date_str = now.strftime("%Y-%m-%d")
        
        # ユーザー設定を読み込み
        preferences = load_user_preferences()

        # 自動学習更新
        if preferences.get("selection_history"):
            preferences = update_preferences(preferences)
            try:
                save_preferences_to_github(preferences)
            except Exception as e:
                log(f"Warning: Failed to save preferences: {e}")

        # 候補を収集
        candidates = collect_candidates(today, yesterday, preferences)
        
        if not candidates:
            return False, "No candidates collected"
        
        # candidates.md を生成
        candidates_content = f"""# 📰 ニュース候補 - {date_str}

以下から気になる記事の番号を選んでください。
Claudeに「1,3,5を選ぶ」のように伝えると、詳細要約を生成します。

---

{candidates}

---

💡 **選択方法**: 記事番号をカンマ区切りで伝えてください（例: 1,4,7）
"""
        
        # GitHubにプッシュ
        candidates_path = f"news/{date_str}-candidates.md"
        push_to_github(
            file_path=candidates_path,
            content=candidates_content,
            commit_message=f"Add news candidates for {date_str}"
        )
        
        log(f"Saved: {candidates_path}")
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

