#!/usr/bin/env python3
"""Site Scraper - Fetch news articles directly from 10 curated news sites.

Replaces GNews API with direct scraping of:
  AI: TechCrunch, WIRED, Ars Technica, MIT Technology Review,
      Anthropic News, Anthropic Research, Gemini Release Notes, OpenAI
  Economy: CNBC, Nikkei (日経新聞)
"""

import re
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed


# --- Site definitions ---

SITES = {
    "techcrunch": {
        "name": "TechCrunch",
        "base_url": "https://techcrunch.com",
        "category": "AI・テクノロジー",
        "lang": "en",
    },
    "wired": {
        "name": "WIRED",
        "base_url": "https://www.wired.com",
        "category": "AI・テクノロジー",
        "lang": "en",
    },
    "arstechnica": {
        "name": "Ars Technica",
        "base_url": "https://arstechnica.com",
        "category": "AI・テクノロジー",
        "lang": "en",
    },
    "mittr": {
        "name": "MIT Technology Review",
        "base_url": "https://www.technologyreview.com",
        "category": "AI・テクノロジー",
        "lang": "en",
    },
    "cnbc": {
        "name": "CNBC",
        "base_url": "https://www.cnbc.com",
        "category": "経済・金融",
        "lang": "en",
    },
    "nikkei": {
        "name": "日本経済新聞",
        "base_url": "https://www.nikkei.com",
        "category": "経済・金融",
        "lang": "ja",
    },
    "anthropic_news": {
        "name": "Anthropic",
        "base_url": "https://www.anthropic.com",
        "category": "AI・テクノロジー",
        "lang": "en",
    },
    "anthropic_research": {
        "name": "Anthropic Research",
        "base_url": "https://www.anthropic.com",
        "category": "AI・テクノロジー",
        "lang": "en",
    },
    "gemini_releases": {
        "name": "Gemini Release Notes",
        "base_url": "https://gemini.google",
        "category": "AI・テクノロジー",
        "lang": "ja",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://openai.com",
        "category": "AI・テクノロジー",
        "lang": "en",
    },
}

# --- AI keyword filters ---

AI_KEYWORDS_EN = [
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "llm", "large language model", "chatgpt", "gpt", "openai", "gemini",
    "claude", "anthropic", "neural", "generative ai", "gen ai",
    "copilot", "ai agent", "chatbot", "transformer", "diffusion",
    "midjourney", "stable diffusion", "nvidia", "deepmind",
    "reinforcement learning", "computer vision", "nlp", "robotics",
    "autonomous", "self-driving", "vibe coding", "ai coding",
    "algorithm", "automation", "data center", "gpu", "chip",
    "semiconductor", "robot", "bot", "model", "training",
    "inference", "benchmark", "prompt", "agent",
    "hugging face", "meta ai", "mistral", "perplexity",
    "openclaw", "moltbot", "seedance",
]

AI_KEYWORDS_JA = [
    "ai", "人工知能", "機械学習", "深層学習", "llm", "大規模言語モデル",
    "chatgpt", "生成ai", "aiエージェント", "openai", "ロボット",
]

ECONOMY_KEYWORDS_EN = [
    "economy", "market", "stock", "fed", "inflation", "gdp", "trade",
    "tariff", "earnings", "investment", "wall street", "crypto",
    "bitcoin", "interest rate", "bond", "treasury", "recession",
    "bank", "financial", "oil", "commodity", "s&p", "nasdaq", "dow",
]

ECONOMY_KEYWORDS_JA = [
    "日銀", "金融", "為替", "gdp", "株", "経済", "利上げ", "円安",
    "円高", "金利", "インフレ", "景気", "財政", "物価", "債券",
    "投資", "市場", "指標", "雇用", "貿易", "日経平均",
]

# Headers to mimic a browser request
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
}


def _fetch_page(url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
    """Fetch a page and return a BeautifulSoup object."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  [WARN] Failed to fetch {url}: {e}")
        return None


def _is_article_url(url: str, base_url: str) -> bool:
    """Check if a URL looks like an article link (not a category/tag page)."""
    if not url or not url.startswith(("http://", "https://", "/")):
        return False

    parsed = urlparse(url)
    path = parsed.path.strip("/")

    # Skip obvious non-article paths
    skip_patterns = [
        r"^$",                     # homepage
        r"^(tag|category|topic|author|about|contact|privacy|terms|newsletter|video|podcast|events)",
        r"^(search|login|signup|register|subscribe|account|settings|help|faq)",
        r"^(page/\d+|feed|rss|sitemap)",
    ]
    for pattern in skip_patterns:
        if re.match(pattern, path, re.IGNORECASE):
            return False

    # Must have enough path depth to be an article
    segments = [s for s in path.split("/") if s]
    if len(segments) < 2:
        return False

    return True


def _text_matches_keywords(text: str, keywords: List[str]) -> bool:
    """Check if text contains any of the given keywords (case-insensitive)."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def _get_recent_cutoff(days: int = 2) -> str:
    """Return cutoff date string (YYYY-MM-DD) for filtering recent articles."""
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


# Month name -> number mapping for parsing dates like "Feb 20, 2026"
_MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def _parse_anthropic_date(text: str) -> str:
    """Extract date from Anthropic link text like 'AnnouncementsFeb 20, 2026Title...'.

    Returns YYYY-MM-DD string or empty string if no date found.
    """
    match = re.search(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(\d{4})",
        text
    )
    if match:
        month = _MONTH_MAP[match.group(1).lower()]
        day = match.group(2).zfill(2)
        year = match.group(3)
        return f"{year}-{month}-{day}"
    return ""


# =============================================================================
# Per-site scrapers
# =============================================================================

def scrape_techcrunch(max_articles: int = 15) -> List[Dict[str, Any]]:
    """Scrape TechCrunch for AI-related articles."""
    articles = []
    soup = _fetch_page("https://techcrunch.com")
    if not soup:
        return articles

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if not href.startswith("https://techcrunch.com/"):
            continue

        # TechCrunch article URLs: /YYYY/MM/DD/slug
        if not re.search(r"/20\d{2}/\d{2}/\d{2}/", href):
            continue

        title = a_tag.get_text(strip=True)
        if not title or len(title) < 10:
            continue

        # Deduplicate within this batch
        if any(art["url"] == href for art in articles):
            continue

        # Extract date from URL
        date_match = re.search(r"/(20\d{2})/(\d{2})/(\d{2})/", href)
        published_at = ""
        if date_match:
            published_at = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"

        articles.append({
            "title": title,
            "description": "",
            "url": href,
            "source": "TechCrunch",
            "published_at": published_at,
            "category": "AI・テクノロジー",
            "content": "",
        })

        if len(articles) >= max_articles:
            break

    return articles


def scrape_wired(max_articles: int = 15) -> List[Dict[str, Any]]:
    """Scrape WIRED for articles."""
    articles = []
    soup = _fetch_page("https://www.wired.com")
    if not soup:
        return articles

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]

        # Normalize relative URLs
        if href.startswith("/"):
            href = "https://www.wired.com" + href

        if not href.startswith("https://www.wired.com/story/"):
            continue

        title = a_tag.get_text(strip=True)
        if not title or len(title) < 10:
            continue

        if any(art["url"] == href for art in articles):
            continue

        articles.append({
            "title": title,
            "description": "",
            "url": href,
            "source": "WIRED",
            "published_at": datetime.now().strftime("%Y-%m-%d"),
            "category": "AI・テクノロジー",
            "content": "",
        })

        if len(articles) >= max_articles:
            break

    return articles


def scrape_arstechnica(max_articles: int = 15) -> List[Dict[str, Any]]:
    """Scrape Ars Technica for articles."""
    articles = []
    soup = _fetch_page("https://arstechnica.com")
    if not soup:
        return articles

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]

        if href.startswith("/"):
            href = "https://arstechnica.com" + href

        if not href.startswith("https://arstechnica.com/"):
            continue

        # Ars article URLs have category/YYYY/MM/slug pattern
        if not re.search(r"/20\d{2}/\d{2}/", href):
            continue

        title = a_tag.get_text(strip=True)
        if not title or len(title) < 10:
            continue

        if any(art["url"] == href for art in articles):
            continue

        # Extract date
        date_match = re.search(r"/(20\d{2})/(\d{2})/", href)
        published_at = ""
        if date_match:
            published_at = f"{date_match.group(1)}-{date_match.group(2)}"

        articles.append({
            "title": title,
            "description": "",
            "url": href,
            "source": "Ars Technica",
            "published_at": published_at,
            "category": "AI・テクノロジー",
            "content": "",
        })

        if len(articles) >= max_articles:
            break

    return articles


def scrape_mittr(max_articles: int = 15) -> List[Dict[str, Any]]:
    """Scrape MIT Technology Review for articles."""
    articles = []
    soup = _fetch_page("https://www.technologyreview.com")
    if not soup:
        return articles

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]

        if href.startswith("/"):
            href = "https://www.technologyreview.com" + href

        if not href.startswith("https://www.technologyreview.com/"):
            continue

        # MIT TR article URLs typically end with a slug after a date or category path
        parsed = urlparse(href)
        path = parsed.path.strip("/")
        segments = [s for s in path.split("/") if s]

        # Skip non-article pages
        if len(segments) < 2:
            continue
        if segments[0] in ("topic", "collection", "author", "podcast", "video",
                          "newsletter", "events", "about", "privacy"):
            continue

        title = a_tag.get_text(strip=True)
        if not title or len(title) < 10:
            continue

        if any(art["url"] == href for art in articles):
            continue

        articles.append({
            "title": title,
            "description": "",
            "url": href,
            "source": "MIT Technology Review",
            "published_at": datetime.now().strftime("%Y-%m-%d"),
            "category": "AI・テクノロジー",
            "content": "",
        })

        if len(articles) >= max_articles:
            break

    return articles


def scrape_cnbc(max_articles: int = 15) -> List[Dict[str, Any]]:
    """Scrape CNBC for economy/finance articles."""
    articles = []
    soup = _fetch_page("https://www.cnbc.com")
    if not soup:
        return articles

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]

        if href.startswith("/"):
            href = "https://www.cnbc.com" + href

        if not href.startswith("https://www.cnbc.com/"):
            continue

        # CNBC article URLs: /YYYY/MM/DD/slug.html
        if not re.search(r"/20\d{2}/\d{2}/\d{2}/", href):
            continue

        title = a_tag.get_text(strip=True)
        if not title or len(title) < 10:
            continue

        if any(art["url"] == href for art in articles):
            continue

        # Extract date
        date_match = re.search(r"/(20\d{2})/(\d{2})/(\d{2})/", href)
        published_at = ""
        if date_match:
            published_at = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"

        articles.append({
            "title": title,
            "description": "",
            "url": href,
            "source": "CNBC",
            "published_at": published_at,
            "category": "経済・金融",
            "content": "",
        })

        if len(articles) >= max_articles:
            break

    return articles


def scrape_nikkei(max_articles: int = 15) -> List[Dict[str, Any]]:
    """Scrape Nikkei (日経新聞) for Japanese economy articles."""
    articles = []
    soup = _fetch_page("https://www.nikkei.com")
    if not soup:
        return articles

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]

        if href.startswith("/"):
            href = "https://www.nikkei.com" + href

        if not href.startswith("https://www.nikkei.com/article/"):
            continue

        title = a_tag.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        if any(art["url"] == href for art in articles):
            continue

        articles.append({
            "title": title,
            "description": "",
            "url": href,
            "source": "日本経済新聞",
            "published_at": datetime.now().strftime("%Y-%m-%d"),
            "category": "経済・金融",
            "content": "",
        })

        if len(articles) >= max_articles:
            break

    return articles


def scrape_anthropic_news(max_articles: int = 15) -> List[Dict[str, Any]]:
    """Scrape Anthropic News for official announcements (recent only)."""
    articles = []
    soup = _fetch_page("https://www.anthropic.com/news")
    if not soup:
        return articles

    cutoff = _get_recent_cutoff()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]

        if href.startswith("/"):
            href = "https://www.anthropic.com" + href

        # Only match /news/slug pattern (not /news itself)
        if not re.match(r"https://www\.anthropic\.com/news/[a-z0-9]", href):
            continue

        full_text = a_tag.get_text(strip=True)
        if not full_text or len(full_text) < 10:
            continue

        # Extract real date from link text (e.g. "AnnouncementsFeb 20, 2026Making frontier...")
        published_at = _parse_anthropic_date(full_text)

        # Skip articles without a date or older than cutoff
        if not published_at or published_at < cutoff:
            continue

        # Remove date/category prefix from title
        title = re.sub(
            r"^(Announcements|Product|Policy|Research|Economic Research|Interpretability|Alignment|Societal Impacts|Frontier Red Team)"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}",
            "", full_text
        ).strip()
        if not title or len(title) < 10:
            title = full_text

        if any(art["url"] == href for art in articles):
            continue

        articles.append({
            "title": title,
            "description": "",
            "url": href,
            "source": "Anthropic",
            "published_at": published_at,
            "category": "AI・テクノロジー",
            "content": "",
        })

        if len(articles) >= max_articles:
            break

    return articles


def scrape_anthropic_research(max_articles: int = 15) -> List[Dict[str, Any]]:
    """Scrape Anthropic Research for research publications (recent only)."""
    articles = []
    soup = _fetch_page("https://www.anthropic.com/research")
    if not soup:
        return articles

    cutoff = _get_recent_cutoff()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]

        if href.startswith("/"):
            href = "https://www.anthropic.com" + href

        # Only match /research/slug pattern (not /research itself or team pages)
        if not re.match(r"https://www\.anthropic\.com/research/[a-z0-9]", href):
            continue
        if "/research/team/" in href:
            continue

        full_text = a_tag.get_text(strip=True)
        if not full_text or len(full_text) < 10:
            continue

        # Extract real date from link text
        published_at = _parse_anthropic_date(full_text)

        # Skip articles without a date or older than cutoff
        if not published_at or published_at < cutoff:
            continue

        # Remove date/category prefix from title
        title = re.sub(
            r"^(Announcements|Product|Policy|Research|Economic Research|Interpretability|Alignment|Societal Impacts|Frontier Red Team)"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}",
            "", full_text
        ).strip()
        if not title or len(title) < 10:
            title = full_text

        if any(art["url"] == href for art in articles):
            continue

        articles.append({
            "title": title,
            "description": "",
            "url": href,
            "source": "Anthropic Research",
            "published_at": published_at,
            "category": "AI・テクノロジー",
            "content": "",
        })

        if len(articles) >= max_articles:
            break

    return articles


def scrape_gemini_releases(max_articles: int = 15) -> List[Dict[str, Any]]:
    """Scrape Gemini Release Notes for official Gemini updates (recent only)."""
    articles = []
    soup = _fetch_page("https://gemini.google/release-notes/")
    if not soup:
        return articles

    cutoff = _get_recent_cutoff()

    # The page has h2 headers with dates (e.g., "2026.02.19")
    # followed by h3 headers with release titles
    current_date = ""
    for tag in soup.find_all(["h2", "h3"]):
        text = tag.get_text(strip=True)
        if not text:
            continue

        if tag.name == "h2":
            # Check if it looks like a date: YYYY.MM.DD
            date_match = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", text)
            if date_match:
                current_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
            continue

        if tag.name == "h3" and current_date:
            # Skip dates older than cutoff
            if current_date < cutoff:
                continue

            title = text
            if len(title) < 5:
                continue

            # Create a stable URL from the release notes page + date + title slug
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
            url = f"https://gemini.google/release-notes/#{current_date}-{slug}"

            if any(art["url"] == url for art in articles):
                continue

            articles.append({
                "title": title,
                "description": "",
                "url": url,
                "source": "Gemini Release Notes",
                "published_at": current_date,
                "category": "AI・テクノロジー",
                "content": "",
            })

            if len(articles) >= max_articles:
                break

    return articles


def scrape_openai(max_articles: int = 15) -> List[Dict[str, Any]]:
    """Scrape OpenAI product updates via sitemap XML (recent only)."""
    articles = []
    try:
        resp = requests.get(
            "https://openai.com/sitemap.xml/product/",
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"  [WARN] Failed to fetch OpenAI sitemap: {e}")
        return articles

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as e:
        print(f"  [WARN] Failed to parse OpenAI sitemap XML: {e}")
        return articles

    cutoff = _get_recent_cutoff()
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    for url_elem in root.findall("s:url", ns):
        loc = url_elem.findtext("s:loc", default="", namespaces=ns)
        lastmod = url_elem.findtext("s:lastmod", default="", namespaces=ns)

        if not loc or not loc.startswith("https://openai.com/index/"):
            continue

        # Extract date from lastmod (e.g., "2026-02-20T07:01:23.805Z")
        published_at = ""
        if lastmod:
            date_match = re.match(r"(\d{4}-\d{2}-\d{2})", lastmod)
            if date_match:
                published_at = date_match.group(1)

        # Skip articles without a date or older than cutoff
        if not published_at or published_at < cutoff:
            continue

        # Generate title from URL slug (e.g., "introducing-gpt-5-2" -> "Introducing Gpt 5 2")
        slug = loc.rstrip("/").split("/")[-1]
        title = slug.replace("-", " ").title()

        if not title or len(title) < 5:
            continue

        if any(art["url"] == loc for art in articles):
            continue

        articles.append({
            "title": title,
            "description": "",
            "url": loc,
            "source": "OpenAI",
            "published_at": published_at,
            "category": "AI・テクノロジー",
            "content": "",
        })

        if len(articles) >= max_articles:
            break

    return articles


# =============================================================================
# Site scraper registry
# =============================================================================

SCRAPER_FUNCTIONS = {
    "techcrunch": scrape_techcrunch,
    "wired": scrape_wired,
    "arstechnica": scrape_arstechnica,
    "mittr": scrape_mittr,
    "cnbc": scrape_cnbc,
    "nikkei": scrape_nikkei,
    "anthropic_news": scrape_anthropic_news,
    "anthropic_research": scrape_anthropic_research,
    "gemini_releases": scrape_gemini_releases,
    "openai": scrape_openai,
}


# =============================================================================
# Main collection function (replaces collect_multi_category_articles)
# =============================================================================

def collect_site_articles(
    preferences: Dict[str, Any],
    total_articles: int = 30
) -> List[Dict[str, Any]]:
    """Collect articles from 10 curated sites.

    Drop-in replacement for gnews_client.collect_multi_category_articles.
    Returns articles in the same format.

    Args:
        preferences: User preferences dict (used for category distribution)
        total_articles: Target number of articles

    Returns:
        List of article dicts with: title, description, url, source,
        published_at, category, content
    """
    search_config = preferences.get("search_config", {})
    category_distribution = search_config.get("category_distribution", {})

    # Determine which sites to scrape based on category distribution
    ai_ratio = category_distribution.get("ai", 0.6)
    finance_ratio = category_distribution.get("finance", 0.4)

    ai_target = max(8, round(total_articles * ai_ratio))
    finance_target = max(5, round(total_articles * finance_ratio))

    # Per-site article limits (generous to allow for post-filtering)
    ai_per_site = max(8, ai_target // 4 + 3)  # 8 AI sites, over-fetch
    finance_per_site = max(8, finance_target + 3)  # 2 finance sites

    all_raw_articles = []

    # Scrape all sites in parallel
    print(f"Scraping 10 sites (AI: ~{ai_target}, Economy: ~{finance_target})...")

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {}

        # AI sites
        for site_id in ["techcrunch", "wired", "arstechnica", "mittr",
                        "anthropic_news", "anthropic_research",
                        "gemini_releases", "openai"]:
            fn = SCRAPER_FUNCTIONS[site_id]
            futures[executor.submit(fn, ai_per_site)] = site_id

        # Finance sites
        for site_id in ["cnbc", "nikkei"]:
            fn = SCRAPER_FUNCTIONS[site_id]
            futures[executor.submit(fn, finance_per_site)] = site_id

        for future in as_completed(futures):
            site_id = futures[future]
            try:
                site_articles = future.result()
                print(f"  {SITES[site_id]['name']}: {len(site_articles)} articles")
                all_raw_articles.extend(site_articles)
            except Exception as e:
                print(f"  [ERROR] {SITES[site_id]['name']}: {e}")

    # --- AI keyword filtering ---
    # AI-focused sources: keep all articles without keyword filtering
    # General tech sites (WIRED, Ars): apply keyword filter
    AI_FOCUSED_SOURCES = {
        "TechCrunch", "MIT Technology Review",
        "Anthropic", "Anthropic Research",
        "Gemini Release Notes", "OpenAI",
    }

    filtered = []
    for article in all_raw_articles:
        if article["category"] == "AI・テクノロジー":
            # AI-focused sites: keep everything
            if article["source"] in AI_FOCUSED_SOURCES:
                filtered.append(article)
            else:
                # General tech sites (WIRED, Ars): keyword filter
                text = (article["title"] + " " + article.get("description", "")).lower()
                if _text_matches_keywords(text, AI_KEYWORDS_EN + AI_KEYWORDS_JA):
                    filtered.append(article)
                elif "/ai/" in article["url"].lower():
                    filtered.append(article)
        else:
            # Economy articles: keep all from CNBC/Nikkei
            filtered.append(article)

    # --- Deduplication (URL + title prefix) ---
    seen_urls = set()
    seen_title_prefixes = set()
    deduped = []

    for article in filtered:
        url = article["url"]
        if url in seen_urls:
            continue

        title_prefix = article["title"].strip()[:25].strip()
        if title_prefix and title_prefix in seen_title_prefixes:
            continue

        seen_urls.add(url)
        if title_prefix:
            seen_title_prefixes.add(title_prefix)
        deduped.append(article)

    # --- Post-filter: remove articles older than 2 days ---
    cutoff = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    before_date_filter = len(deduped)
    deduped = [
        a for a in deduped
        if not a.get("published_at") or a["published_at"] >= cutoff
    ]
    removed = before_date_filter - len(deduped)
    if removed > 0:
        print(f"Removed {removed} articles older than {cutoff}")

    # Limit to target count
    if len(deduped) > total_articles:
        # Ensure balanced categories
        ai_articles = [a for a in deduped if a["category"] == "AI・テクノロジー"]
        econ_articles = [a for a in deduped if a["category"] == "経済・金融"]

        final = ai_articles[:ai_target] + econ_articles[:finance_target]
        # Fill remaining slots
        remaining = total_articles - len(final)
        if remaining > 0:
            used_urls = {a["url"] for a in final}
            extras = [a for a in deduped if a["url"] not in used_urls]
            final.extend(extras[:remaining])
        deduped = final

    print(f"Total after filtering: {len(deduped)} articles")
    ai_count = len([a for a in deduped if a["category"] == "AI・テクノロジー"])
    econ_count = len([a for a in deduped if a["category"] == "経済・金融"])
    print(f"  AI: {ai_count}, Economy: {econ_count}")

    return deduped


# =============================================================================
# CLI test
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Site Scraper Test")
    print("=" * 60)

    preferences = {
        "search_config": {
            "category_distribution": {"ai": 0.6, "finance": 0.4},
        }
    }

    articles = collect_site_articles(preferences, total_articles=30)

    print(f"\n{'=' * 60}")
    print(f"Results: {len(articles)} articles")
    print(f"{'=' * 60}")

    for i, a in enumerate(articles, 1):
        print(f"\n{i}. [{a['category']}] {a['title']}")
        print(f"   Source: {a['source']} | Date: {a['published_at']}")
        print(f"   URL: {a['url'][:80]}...")
