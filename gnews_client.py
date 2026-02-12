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
    articles_per_category: int = 12
) -> List[Dict[str, Any]]:
    """Collect articles from multiple categories based on user preferences
    
    Args:
        preferences: User preferences dictionary with search_config
        articles_per_category: Number of articles to fetch per category
        
    Returns:
        Combined list of articles from all categories
    """
    search_config = preferences.get("search_config", {})
    boosted_keywords = search_config.get("boosted_keywords", [])
    
    all_articles = []
    
    # Category mapping: GNews category -> Our category label
    categories = {
        "technology": "AI・テクノロジー",
        "business": "経済・金融",
        "general": "政治・政策"
    }
    
    for gnews_category, our_category in categories.items():
        # Fetch articles for this category
        articles = fetch_gnews_articles(
            category=gnews_category,
            max_articles=articles_per_category,
            days_back=2  # Look back 2 days to ensure we have enough articles
        )
        
        # Add category label to each article
        for article in articles:
            article["category"] = our_category
        
        all_articles.extend(articles)
    
    # If we have boosted keywords, also do a keyword search
    if boosted_keywords:
        keyword_articles = fetch_gnews_articles(
            keywords=boosted_keywords,
            max_articles=10,
            days_back=2
        )
        
        # Deduplicate by URL
        existing_urls = {a["url"] for a in all_articles}
        for article in keyword_articles:
            if article["url"] not in existing_urls:
                article["category"] = "AI・テクノロジー"  # Default to tech for keyword matches
                all_articles.append(article)
    
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
