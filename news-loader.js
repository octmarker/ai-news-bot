/**
 * News Loader - Fetches and parses AI News Bot candidates JSON files
 * Falls back to previous days if today's file is not yet available.
 */

class NewsLoader {
    constructor() {
        this.categoryMap = {
            'AI・テクノロジー': { label: 'テクノロジー', color: 'bg-primary' },
            '経済・金融': { label: '経済', color: 'bg-charcoal' },
            '政治・政策': { label: '政治', color: 'bg-primary/80' },
            '科学': { label: '科学', color: 'bg-primary/80' }
        };
    }

    /**
     * Get date string in YYYY-MM-DD format for N days ago
     */
    getDateString(daysAgo = 0) {
        const d = new Date();
        d.setDate(d.getDate() - daysAgo);
        return d.toISOString().split('T')[0];
    }

    /**
     * Fetch candidates JSON file from GitHub (try today, then fall back up to 3 days)
     */
    async fetchCandidates() {
        const baseUrl = 'https://raw.githubusercontent.com/octmarker/ai-news-bot/main/news';

        for (let daysAgo = 0; daysAgo <= 3; daysAgo++) {
            const dateStr = this.getDateString(daysAgo);

            // Try JSON format first (current format since Feb 12)
            try {
                const jsonUrl = `${baseUrl}/${dateStr}-candidates.json`;
                const response = await fetch(jsonUrl);
                if (response.ok) {
                    const data = await response.json();
                    console.log(`Loaded candidates from ${dateStr} (JSON)`);
                    return { data, date: dateStr, format: 'json' };
                }
            } catch (e) {
                // JSON fetch failed, try MD
            }

            // Fallback to MD format (legacy format before Feb 12)
            try {
                const mdUrl = `${baseUrl}/${dateStr}-candidates.md`;
                const response = await fetch(mdUrl);
                if (response.ok) {
                    const text = await response.text();
                    console.log(`Loaded candidates from ${dateStr} (Markdown)`);
                    return { data: text, date: dateStr, format: 'md' };
                }
            } catch (e) {
                // MD fetch failed too, try next day
            }
        }

        throw new Error('No candidates files found for the past 3 days');
    }

    /**
     * Parse JSON candidates data to article array
     */
    parseJSON(data) {
        if (!data.articles || !Array.isArray(data.articles)) return [];

        return data.articles.map(article => {
            const summary = article.summary || {};
            return {
                number: article.number,
                title: article.title,
                source: article.source || 'ニュースソース',
                description: summary.summary_ja || summary.summary || article.description || '',
                url: article.url || '#',
                category: article.category || '科学',
                relevance: this.calculateRelevance(article.number),
                publishedAt: article.published_at || ''
            };
        });
    }

    /**
     * Parse markdown content to extract articles (legacy fallback)
     */
    parseMarkdown(markdown) {
        const articles = [];
        let currentCategory = '科学';
        const lines = markdown.split('\n');

        let i = 0;
        while (i < lines.length) {
            const line = lines[i].trim();

            if (line.startsWith('## ') && !line.includes('📰')) {
                const categoryText = line.substring(3).trim();
                for (const [key] of Object.entries(this.categoryMap)) {
                    if (categoryText.includes(key.split('・')[0])) {
                        currentCategory = key;
                        break;
                    }
                }
                i++;
                continue;
            }

            const articleMatch = line.match(/^(\d+)\.\s+(.+)$/);
            if (articleMatch) {
                const articleNum = parseInt(articleMatch[1]);
                const title = articleMatch[2].trim();

                i++;
                const metaLine = lines[i]?.trim() || '';
                const sourceMatch = metaLine.match(/📰\s+([^|]+)\s*\|\s*💡\s+(.+)/);

                let source = 'ニュースソース';
                let description = '';

                if (sourceMatch) {
                    source = sourceMatch[1].trim();
                    description = sourceMatch[2].trim();
                }

                i++;
                const urlLine = lines[i]?.trim() || '';
                const urlMatch = urlLine.match(/URL:\s*\[?([^\]]+)\]?/);
                const url = urlMatch ? urlMatch[1].trim() : '#';

                articles.push({
                    number: articleNum,
                    title,
                    source,
                    description,
                    url,
                    category: currentCategory,
                    relevance: this.calculateRelevance(articleNum)
                });
            }

            i++;
        }

        return articles;
    }

    /**
     * Calculate relevance score based on article position
     */
    calculateRelevance(position) {
        if (position <= 3) return 95 + (4 - position);
        if (position <= 6) return 90 + (7 - position);
        return Math.max(85, 95 - position);
    }

    /**
     * Get category badge info
     */
    getCategoryInfo(category) {
        return this.categoryMap[category] || { label: '科学', color: 'bg-primary/80' };
    }

    /**
     * Calculate reading time (estimate based on description length)
     */
    calculateReadingTime(description) {
        const words = description.length;
        const minutes = Math.max(2, Math.ceil(words / 200));
        return minutes;
    }

    /**
     * Format published date or relative time
     */
    formatTimeAgo(article) {
        if (article.publishedAt) {
            try {
                const d = new Date(article.publishedAt);
                if (!isNaN(d.getTime())) {
                    const now = new Date();
                    const diffMs = now - d;
                    const diffH = Math.floor(diffMs / (1000 * 60 * 60));
                    if (diffH < 1) return '1時間以内';
                    if (diffH < 24) return `${diffH}時間前`;
                    const diffD = Math.floor(diffH / 24);
                    return `${diffD}日前`;
                }
            } catch (e) { /* fall through */ }
        }
        // Fallback based on position
        const n = article.number;
        if (n <= 2) return `${n * 5}分前`;
        if (n <= 5) return `${n * 10}分前`;
        return `${n}時間前`;
    }

    /**
     * Load and render articles
     */
    async loadAndRender(containerId = 'news-articles-container', dateElementId = 'current-date') {
        try {
            console.log('Loading news candidates...');

            const result = await this.fetchCandidates();

            let articles;
            if (result.format === 'json') {
                articles = this.parseJSON(result.data);
            } else {
                articles = this.parseMarkdown(result.data);
            }
            console.log(`Parsed ${articles.length} articles from ${result.date}`);

            this.renderArticles(articles, containerId);
            this.updateDate(dateElementId, result.date);

            return articles;
        } catch (error) {
            console.error('Error loading news:', error);
            this.renderError(containerId);
            throw error;
        }
    }

    /**
     * Render articles to DOM
     */
    renderArticles(articles, containerId) {
        const container = document.getElementById(containerId);
        if (!container) {
            console.error(`Container #${containerId} not found`);
            return;
        }

        container.innerHTML = articles.map((article, index) => {
            const categoryInfo = this.getCategoryInfo(article.category);
            const readingTime = this.calculateReadingTime(article.description);
            const timeAgo = this.formatTimeAgo(article);
            const borderClass = index > 0 ? 'pt-10 border-t border-paper-border' : '';

            return `
                <article class="group relative ${borderClass}">
                    <a class="block" href="${article.url}" target="_blank" rel="noopener noreferrer">
                        <div class="flex flex-col gap-4">
                            <div class="flex items-center justify-between">
                                <div class="flex items-center gap-3">
                                    <span class="px-2 py-0.5 rounded-sm text-[10px] font-bold ${categoryInfo.color} text-paper-bg tracking-widest uppercase">${categoryInfo.label}</span>
                                    <span class="text-charcoal-muted text-xs font-bold serif-font">${article.source} • ${timeAgo}</span>
                                </div>
                                <span class="material-symbols-outlined text-paper-border group-hover:text-primary transition-colors">north_east</span>
                            </div>
                            <h3 class="text-charcoal text-2xl font-bold leading-tight group-hover:text-primary transition-colors japanese-tracking">${article.title}</h3>
                            <div class="flex gap-6">
                                <div class="w-0.5 bg-primary/30 rounded-full"></div>
                                <p class="text-charcoal-muted text-base leading-relaxed line-clamp-3 font-medium">
                                    ${article.description}
                                </p>
                            </div>
                            <div class="flex items-center gap-6 mt-2 pt-4 border-t border-paper-border">
                                <div class="flex items-center gap-1.5 text-[11px] font-bold text-charcoal-muted uppercase tracking-wider">
                                    <span class="material-symbols-outlined text-base">schedule</span>
                                    読了時間：${readingTime}分
                                </div>
                                <div class="flex items-center gap-1.5 text-[11px] font-bold text-primary uppercase tracking-wider">
                                    <span class="material-symbols-outlined text-base">psychology</span>
                                    関連度 ${article.relevance}%
                                </div>
                            </div>
                        </div>
                    </a>
                </article>
            `;
        }).join('');
    }

    /**
     * Render error message
     */
    renderError(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        container.innerHTML = `
            <div class="flex flex-col items-center justify-center py-20 gap-6">
                <span class="material-symbols-outlined text-6xl text-charcoal-muted">error_outline</span>
                <h3 class="text-2xl font-bold text-charcoal">ニュースの読み込みに失敗しました</h3>
                <p class="text-charcoal-muted">最新のニュース候補ファイルが見つかりませんでした。</p>
                <button onclick="location.reload()" class="px-6 py-3 bg-primary text-paper-bg font-bold rounded-sm hover:bg-charcoal transition-colors">
                    再読み込み
                </button>
            </div>
        `;
    }

    /**
     * Update date display
     */
    updateDate(elementId, dateStr) {
        const dateElement = document.getElementById(elementId);
        if (dateElement) {
            const d = dateStr ? new Date(dateStr + 'T00:00:00+09:00') : new Date();
            const options = { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' };
            dateElement.textContent = d.toLocaleDateString('ja-JP', options);
        }
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
    const loader = new NewsLoader();
    try {
        await loader.loadAndRender();
    } catch (error) {
        console.error('Failed to load news:', error);
    }
});
