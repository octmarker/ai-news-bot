#!/usr/bin/env python3
"""GNews API Client - Fetch news articles from GNews.io API"""

import os
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta


class GNewsClient:
    """Client for interacting with GNews.io API"""
    
    BASE_URL = "https://gnews.io/api/v4"
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize GNews client
        
        Args:
            api_key: GNews API key. If not provided, reads from GNEWS_API_KEY env var
        """
        self.api_key = api_key or os.environ.get("GNEWS_API_KEY")
        if not self.api_key:
            raise ValueError("GNEWS_API_KEY is not set")
    
    def fetch_articles(
        self,
        category: Optional[str] = None,
        query: Optional[str] = None,
        lang: str = "ja",
        country: str = "jp",
        max_articles: int = 10,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fetch articles from GNews API
        
        Args:
            category: GNews category (technology, business, general, etc.)
            query: Search query string
            lang: Language code (default: ja)
            country: Country code (default: jp)
            max_articles: Maximum number of articles to fetch (default: 10)
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            
        Returns:
            List of article dictionaries with keys: title, description, url, source, publishedAt, image
        """
        # Choose endpoint based on whether category or query is provided
        if category:
            endpoint = f"{self.BASE_URL}/top-headlines"
            params = {
                "category": category,
                "lang": lang,
                "country": country,
                "max": max_articles,
                "apikey": self.api_key
            }
        elif query:
            endpoint = f"{self.BASE_URL}/search"
            params = {
                "q": query,
                "lang": lang,
                "country": country,
                "max": max_articles,
                "apikey": self.api_key
            }
            if from_date:
                params["from"] = from_date
            if to_date:
                params["to"] = to_date
        else:
            raise ValueError("Either category or query must be provided")
        
        try:
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("totalArticles", 0) == 0:
                return []
            
            return self._parse_articles(data.get("articles", []))
            
        except requests.exceptions.RequestException as e:
            print(f"GNews API error: {e}")
            return []
    
    def _parse_articles(self, articles: List[Dict]) -> List[Dict[str, Any]]:
        """Parse GNews API response to standardized format
        
        Args:
            articles: Raw articles from GNews API
            
        Returns:
            List of parsed article dictionaries
        """
        parsed = []
        for article in articles:
            parsed.append({
                "title": article.get("title", ""),
                "description": article.get("description", ""),
                "url": article.get("url", ""),
                "source": article.get("source", {}).get("name", "Unknown"),
                "published_at": article.get("publishedAt", ""),
                "image": article.get("image", ""),
                "content": ""
            })
        return parsed


def build_search_query(boosted_keywords: List[str]) -> str:
    """Build GNews search query from boosted keywords
    
    Args:
        boosted_keywords: List of keywords to boost
        
    Returns:
        Search query string (e.g., "AI OR LLM OR ChatGPT")
    """
    if not boosted_keywords:
        return ""
    
    # GNews uses OR operator for multiple keywords
    return " OR ".join(boosted_keywords)


def fetch_gnews_articles(
    category: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    max_articles: int = 10,
    days_back: int = 1
) -> List[Dict[str, Any]]:
    """Convenience function to fetch articles with common defaults
    
    Args:
        category: GNews category (technology, business, general, etc.)
        keywords: List of keywords to search for
        max_articles: Maximum number of articles to fetch
        days_back: Number of days to look back for articles
        
    Returns:
        List of article dictionaries
    """
    client = GNewsClient()
    
    # Calculate date range
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    
    if keywords:
        query = build_search_query(keywords)
        return client.fetch_articles(
            query=query,
            max_articles=max_articles,
            from_date=from_date,
            to_date=to_date
        )
    elif category:
        return client.fetch_articles(
            category=category,
            max_articles=max_articles
        )
    else:
        raise ValueError("Either category or keywords must be provided")


def collect_multi_category_articles(
    preferences: Dict[str, Any],
    total_articles: int = 30
) -> List[Dict[str, Any]]:
    """Collect articles from multiple categories based on user preferences

    Uses max 4 GNews API calls to stay within rate limits:
    - AI: 2 keyword searches (combined groups)
    - Finance: 1 keyword search
    - Politics: 1 keyword search

    Args:
        preferences: User preferences dictionary with search_config
        total_articles: Total number of articles to fetch across all categories

    Returns:
        Combined list of articles from all categories
    """
    search_config = preferences.get("search_config", {})
    boosted_keywords = search_config.get("boosted_keywords", [])
    category_distribution = search_config.get("category_distribution", {})

    all_articles = []
    existing_urls = set()
    existing_url_paths = set()  # URL paths for cross-domain dedup
    existing_title_prefixes = set()  # Title prefixes for content dedup

    def _url_path(url: str) -> str:
        """Extract URL path for cross-domain comparison"""
        from urllib.parse import urlparse
        return urlparse(url).path.rstrip("/")

    def _is_seen(article: Dict[str, Any]) -> bool:
        """Check if article is already in the batch (URL, path, or title match)"""
        url = article.get("url", "")
        if url in existing_urls:
            return True
        path = _url_path(url)
        if path and len(path) > 5 and path in existing_url_paths:
            return True
        title = article.get("title", "").strip()[:20].strip()
        if title and title in existing_title_prefixes:
            return True
        return False

    def _mark_seen(article: Dict[str, Any]):
        """Mark article as seen"""
        url = article.get("url", "")
        existing_urls.add(url)
        existing_url_paths.add(_url_path(url))
        title = article.get("title", "").strip()[:20].strip()
        if title:
            existing_title_prefixes.add(title)

    # --- AI keywords: 2 groups, each combined with OR (max 10 terms per GNews query) ---
    AI_KEYWORD_GROUPS = [
        ["AI", "人工知能", "LLM", "ChatGPT", "Gemini", "Claude"],
        ["生成AI", "AIエージェント", "機械学習", "OpenAI", "GitHub Copilot", "大規模言語モデル"],
    ]

    # Classify user's boosted keywords into categories
    FINANCE_MARKER_WORDS = ["日銀", "利上げ", "雇用統計", "インフレ", "金融政策", "GDP", "為替",
                            "株価", "経済", "金利", "円安", "円高", "財政", "景気"]
    POLITICS_MARKER_WORDS = ["衆院選", "選挙", "国会", "政策", "外交", "安全保障", "法案",
                             "政治", "与党", "野党", "内閣", "フェイク"]

    def _classify_keyword(kw: str) -> str:
        for marker in FINANCE_MARKER_WORDS:
            if marker in kw or kw in marker:
                return "finance"
        for marker in POLITICS_MARKER_WORDS:
            if marker in kw or kw in marker:
                return "politics"
        return "ai"

    # ========== AI articles (2 API calls) ==========
    ai_ratio = category_distribution.get("ai", 0)
    if ai_ratio > 0:
        ai_count = max(1, round(total_articles * ai_ratio))
        per_group = max(5, ai_count // 2 + 2)

        for keyword_group in AI_KEYWORD_GROUPS:
            # Merge user's AI boosted keywords into first group
            group_articles = fetch_gnews_articles(
                keywords=keyword_group,
                max_articles=per_group,
                days_back=2
            )
            for a in group_articles:
                if not _is_seen(a):
                    _mark_seen(a)
                    a["category"] = "AI・テクノロジー"
                    all_articles.append(a)

    # ========== Finance articles (1 API call) ==========
    finance_ratio = category_distribution.get("finance", 0)
    if finance_ratio > 0:
        finance_count = max(1, round(total_articles * finance_ratio))
        # Use business category but post-filter for financial relevance
        FINANCE_FILTER_WORDS = ["日銀", "金融", "為替", "GDP", "株", "経済", "利上げ", "円安",
                                "円高", "金利", "インフレ", "景気", "財政", "FRB", "物価",
                                "債券", "投資", "市場", "指標", "雇用", "貿易"]
        # Merge user's finance-related boosted keywords
        user_finance_kws = [kw for kw in boosted_keywords if _classify_keyword(kw) == "finance"]
        all_finance_words = set(FINANCE_FILTER_WORDS + user_finance_kws)

        # Over-fetch to have enough after filtering
        raw_finance = fetch_gnews_articles(
            category="business",
            max_articles=finance_count * 3,
            days_back=2
        )
        for a in raw_finance:
            if _is_seen(a):
                continue
            # Check if title or description contains finance-related keywords
            text = (a.get("title", "") + " " + a.get("description", "")).lower()
            if any(kw in text for kw in all_finance_words):
                _mark_seen(a)
                a["category"] = "経済・金融"
                all_articles.append(a)

    # ========== Politics articles (1 API call) ==========
    politics_ratio = category_distribution.get("politics", 0)
    if politics_ratio > 0:
        politics_count = max(1, round(total_articles * politics_ratio))
        # Use general category but post-filter for political relevance
        POLITICS_FILTER_WORDS = ["国会", "選挙", "外交", "法案", "内閣", "首脳", "安全保障",
                                 "政治", "与党", "野党", "政権", "首相", "大統領", "条約",
                                 "防衛", "議会", "政策", "大臣", "関税", "制裁"]
        user_politics_kws = [kw for kw in boosted_keywords if _classify_keyword(kw) == "politics"]
        all_politics_words = set(POLITICS_FILTER_WORDS + user_politics_kws)

        # Over-fetch heavily — general category has low politics hit rate
        raw_politics = fetch_gnews_articles(
            category="general",
            max_articles=politics_count * 5,
            days_back=2
        )
        for a in raw_politics:
            if _is_seen(a):
                continue
            text = (a.get("title", "") + " " + a.get("description", "")).lower()
            if any(kw in text for kw in all_politics_words):
                _mark_seen(a)
                a["category"] = "政治・政策"
                all_articles.append(a)

    return all_articles


if __name__ == "__main__":
    # Test the client
    print("Testing GNews API client...")
    
    try:
        articles = fetch_gnews_articles(category="technology", max_articles=5)
        print(f"\nFetched {len(articles)} technology articles:")
        for i, article in enumerate(articles, 1):
            print(f"\n{i}. {article['title']}")
            print(f"   Source: {article['source']}")
            print(f"   URL: {article['url'][:60]}...")
    except Exception as e:
        print(f"Error: {e}")
