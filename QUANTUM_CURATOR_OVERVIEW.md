# Quantum Curator: Project Overview

**Version**: 1.3.0
**Created**: March 16, 2026
**Author**: Mark Eatherly
**Repository**: https://github.com/subvurs/quantum-curator
**Live Site**: https://subvurs.github.io/quantum-curator/

---

## Executive Summary

Quantum Curator is an automated news aggregation and curation platform that collects, filters, analyzes, and publishes daily quantum computing news. The system pulls from 19 authoritative sources, scores articles for relevance, generates AI-powered expert commentary using Claude, auto-generates images for articles without them, and publishes a beautiful static site to GitHub Pages—all automatically, twice daily.

The result: **Mark Eatherly** is positioned as a trusted curator and thought leader in the quantum computing space, with fresh, insightful content published consistently without manual effort.

---

## Purpose & Goals

### Primary Objectives

1. **Establish Authority**: Position Mark Eatherly as a knowledgeable voice in quantum computing by consistently curating and commenting on the latest developments.

2. **Automate Content Creation**: Eliminate the manual work of finding, reading, summarizing, and publishing quantum news while maintaining quality and authenticity.

3. **Build an Audience**: Create a valuable resource that researchers, engineers, investors, and enthusiasts will bookmark, subscribe to, and share.

4. **SEO & Reputation Building**: Every curated post attributes Mark Eatherly as the curator, building search presence and professional reputation over time.

### Strategic Value

- **Consistency**: Automated twice-daily updates ensure the site always has fresh content
- **Quality**: AI commentary adds genuine insight, not just aggregation
- **Credibility**: Sources include arXiv, Nature, IBM, Google, and other authoritative outlets
- **Scalability**: The system can handle hundreds of articles daily without additional effort

---

## What Was Built

### Core Components

```
quantum-curator/
├── quantum_curator/
│   ├── aggregator.py        # Multi-source fetching, deduplication, relevance scoring
│   ├── curator.py           # AI commentary generation using Claude
│   ├── image_extractor.py   # OG image extraction for article thumbnails
│   ├── image_generator.py   # Unsplash image search for articles without images
│   ├── publisher.py         # GitHub Pages deployment
│   ├── cli.py               # Command-line interface (10 commands)
│   ├── config.py            # Configuration management with pydantic-settings
│   ├── models.py            # Data models (Source, Article, Post, Digest)
│   ├── db.py                # SQLite database layer
│   ├── sources/
│   │   ├── registry.py      # 19 built-in quantum news sources
│   │   ├── rss.py           # RSS/Atom feed parser (follows redirects, sets UA)
│   │   ├── arxiv.py         # arXiv API integration
│   │   └── news.py          # NewsAPI integration (extracts images)
│   └── site/
│       ├── builder.py       # Static site generator with tier-splitting logic
│       ├── templates/       # Jinja2 HTML templates (9 templates)
│       └── static/css/      # Magazine-style dark-theme stylesheet
├── .github/workflows/
│   └── daily-curator.yml    # Automated twice-daily pipeline
├── pyproject.toml           # Package configuration
└── README.md                # Usage documentation
```

### Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Language | Python 3.11+ | Core application |
| CLI Framework | Click + Rich | Beautiful command-line interface |
| AI | Anthropic Claude | Expert commentary generation |
| Database | SQLite | Article and post storage |
| HTTP | httpx | Async HTTP client |
| Templating | Jinja2 | Static site generation |
| Parsing | feedparser, BeautifulSoup | RSS/HTML parsing |
| Config | pydantic-settings | Type-safe configuration |
| Deployment | GitHub Pages | Free static hosting |
| Automation | GitHub Actions | Scheduled pipeline execution |

---

## Features

### 1. Multi-Source Aggregation

The system pulls from 19 carefully selected quantum computing news sources:

**Academic Research**
- arXiv Quantum Physics (quant-ph)
- arXiv Quantum Information (cs.QI)

**Industry Leaders**
- Qiskit Blog (IBM) — via Medium feed
- Google Research Blog — covers Quantum AI under Research
- Microsoft Quantum Blog
- AWS Quantum Computing Blog
- IonQ Blog

**Science Publications**
- Nature Physics
- Quanta Magazine
- Phys.org Quantum Physics
- Science Daily - Quantum
- Physics World - Quantum
- New Scientist - Physics

**Quantum-Focused News**
- Quantum Computing Report
- The Quantum Insider

**Tech News**
- Ars Technica - Science
- MIT Technology Review
- Wired Science

**News Aggregation**
- NewsAPI (when configured)

### 2. Intelligent Relevance Scoring

Each article is scored (0.0 to 1.0) based on:

- **Keyword density**: Presence of 50+ quantum-specific terms
- **High-value terms**: Extra weight for "quantum computing", "qubit", "quantum advantage", etc.
- **Source quality**: arXiv articles receive a boost
- **Title relevance**: Keywords in titles score higher

Articles below the threshold (default: 0.3) are filtered out automatically.

### 3. AI-Powered Commentary

Claude generates 2-4 sentence expert commentary for each article:

```
"This breakthrough in superconducting qubit coherence times represents
a significant step toward fault-tolerant quantum computing. The Beta
Tantalum approach addresses one of the key challenges in scaling
quantum processors—maintaining quantum states long enough for
meaningful computation."
```

The commentary:
- Explains why the article matters
- Puts findings in broader context
- Highlights practical implications
- Uses accessible but technically accurate language

### 4. Daily Digests

Each day, the system generates a digest summary:

```
Quantum News Digest - March 16, 2026

Today's quantum computing news features significant developments in
superconducting qubit technology and quantum algorithm optimization...
```

### 5. Article Image Pipeline

The system ensures every article has a visual through a four-tier strategy:

1. **Feed-level extraction**: RSS feeds provide images via `media_content`, `media_thumbnail`, or `enclosures`. NewsAPI provides images via `urlToImage`. These are captured during the initial fetch.
2. **OG image fallback**: For articles where the feed didn't supply an image, the `image_extractor.py` module fetches the article's HTML page and extracts the `og:image` or `twitter:image` meta tag, falling back to the first reasonably-sized `<img>` in the page content.
3. **Unsplash image generation**: During curation, articles still lacking an image (common for arXiv papers) trigger the `image_generator.py` module. It searches Unsplash with an article-specific query built from title keywords and topics. If no result, it retries with a broader topic-based fallback query (e.g., "quantum computer processor chip technology" for hardware articles). Downloaded images are saved to `data/images/` for persistence across rebuilds and copied into `site_output/static/images/generated/` during the build step.
4. **CSS gradient placeholders**: Articles without any image after all extraction attempts display a topic-colored gradient background instead of a broken image.

Image extraction runs automatically during the fetch pipeline for non-arXiv sources. Unsplash generation runs during curation for any article still missing an image. Feed-level and OG images are referenced by external URL; Unsplash images are downloaded and served as static assets. All images use `loading="lazy"` for performance.

### 6. Magazine-Style Front-End

The homepage uses a tiered magazine layout inspired by Paper.li, designed to present many articles in a dense but scannable format without endless scrolling:

**Three-Tier Article Hierarchy**:
- **Hero article**: The most recent article displayed as a prominent card at the top of the page. When an image is available, it renders as a 3:2 split (text left, image right). When no image is available, the card collapses to a compact text-only block — no wasted space.
- **Featured row**: The next 3 articles displayed in a responsive grid with thumbnail images, topic tags, truncated summaries, and source attribution. Articles with images are prioritized for these slots.
- **Topic sections**: Remaining articles grouped by their primary topic (Hardware, Algorithms, Cryptography, etc.) and displayed as compact horizontal rows — small thumbnail, title, source, and date. Each section has a colored accent bar matching its topic color.

**Design System**:
- Dark theme palette (`--bg: #0f172a`, `--primary: #6366f1`, `--secondary: #06b6d4`)
- 11 topic-specific accent colors for tags, section headers, and gradient placeholders
- Responsive breakpoints at 1024px (tablet) and 768px (mobile)
- Image hover zoom on featured cards, translate-up hover on all cards
- Line-clamped text overflow for consistent card heights
- Compact daily digest with fade-out gradient truncation

**Topic and Individual Article Pages**:
- Topic pages use a featured+compact layout: first article as a wide featured card with commentary, remaining articles as compact rows
- Individual post pages show a hero image (when available) above the article body, with `og:image` and `twitter:card` meta tags for social sharing previews

### 7. Static Site Generation

The system generates a complete static website with:

- **Home page**: Magazine-style layout with hero, featured grid, and topic sections
- **Post pages**: Individual article pages with hero image and full commentary
- **Topic pages**: Featured article + compact list per topic
- **Archive**: Monthly article archives
- **About page**: Curator bio and site information
- **RSS feed**: For subscribers

### 8. Automated Deployment

GitHub Actions runs the full pipeline twice daily:
1. Fetch articles from all 19 sources
2. Score and filter for relevance
3. Generate AI commentary + fetch Unsplash images for articles without one
4. Create daily digest
5. Build static site (copies generated images into output)
6. Deploy to GitHub Pages

---

## How It Works

### The Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                     QUANTUM CURATOR PIPELINE                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │  FETCH   │───▶│  SCORE   │───▶│  CURATE  │───▶│  BUILD   │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│       │               │               │               │         │
│       ▼               ▼               ▼               ▼         │
│  19 Sources      Relevance       Claude AI       Static HTML    │
│  RSS, arXiv,     0.0 - 1.0      Commentary +    Jinja2 + CSS    │
│  NewsAPI         Filtering       Unsplash Imgs   Generation     │
│                                                                  │
│                           │                                      │
│                           ▼                                      │
│                    ┌──────────┐                                  │
│                    │  DEPLOY  │                                  │
│                    └──────────┘                                  │
│                         │                                        │
│                         ▼                                        │
│                   GitHub Pages                                   │
│            subvurs.github.io/quantum-curator                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Command Reference

```bash
# Initialize database and register sources
quantum-curator init

# Fetch articles from all sources
quantum-curator fetch
quantum-curator fetch --force          # Force fetch even if not due
quantum-curator fetch --source "arxiv" # Fetch from specific source

# Curate articles with AI commentary
quantum-curator curate
quantum-curator curate --limit 20      # Limit articles to curate

# Build the static site
quantum-curator build
quantum-curator build --output ./public

# Deploy to GitHub Pages
quantum-curator deploy
quantum-curator deploy --verify        # Verify after deployment

# Run full pipeline
quantum-curator run                    # fetch → curate → build
quantum-curator run --deploy           # Include deployment

# Status and information
quantum-curator status                 # Show statistics
quantum-curator sources                # List configured sources
quantum-curator posts                  # List curated posts
quantum-curator config                 # Show configuration
quantum-curator insights               # Show Subvurs research connections
quantum-curator insights --all         # Include posts with no connections
```

### Automation Schedule

The GitHub Actions workflow runs once daily at:
- **6:00 AM UTC** (11 PM PST, 2 AM EST)

---

## Current Status

### What's Working

| Feature | Status |
|---------|--------|
| arXiv fetching | ✅ Operational |
| RSS feed parsing | ✅ Operational (19 sources, follows redirects) |
| Relevance scoring | ✅ Operational |
| AI commentary | ✅ Operational |
| Daily digests | ✅ Operational |
| Article image extraction | ✅ Operational (RSS, NewsAPI, OG fallback) |
| Unsplash image generation | ✅ Operational (for articles without images) |
| Magazine-style front-end | ✅ Operational (hero, featured, topic sections) |
| Static site generation | ✅ Operational |
| GitHub Pages deployment | ✅ Operational |
| Content freshness window | ✅ Operational (60-day default, configurable) |
| Subvurs research notes | ✅ Operational (Haiku-powered, file + DB storage) |
| Automated pipeline | ✅ Configured (once daily at 6 AM UTC) |

### Content Capacity

- **19 sources** across arXiv, RSS feeds, and NewsAPI
- **228 articles** from 12 different sources in a single fetch (test run)
- Relevance filtering reduces to quantum-specific articles only
- AI commentary generated per article, daily digest per day

### Live Site

The site is live at: **https://subvurs.github.io/quantum-curator/**

---

## What Comes Next

### Phase 1: Content Expansion (Immediate)

1. **Add NewsAPI Key**
   - Enables the NewsAPI source for broader news coverage
   - Set `NEWS_API_KEY` in GitHub secrets and local `.env`

2. **Increase Fetch Frequency**
   - Consider adding more scheduled runs (4x daily)
   - Ensures breaking news is captured quickly

3. **Tune Relevance Scoring**
   - Adjust `MIN_RELEVANCE_SCORE` based on quality of results
   - Add source-specific boosting (Nature > random blog)

### Phase 2: Feature Enhancements (1-2 Weeks)

1. **Social Media Integration**
   - Auto-post to Twitter/X with article highlights
   - LinkedIn posting for professional audience
   - Generate social-optimized images

2. **Email Newsletter**
   - Daily/weekly email digest option
   - Integrate with Buttondown, Substack, or similar
   - Build subscriber list

3. **Enhanced Commentary**
   - Longer-form analysis for major breakthroughs
   - "Week in Review" summary posts
   - Trend analysis across multiple articles

4. **Search Functionality**
   - Add client-side search (Lunr.js or Pagefind)
   - Filter by date, topic, source

### Phase 3: Analytics & Optimization (2-4 Weeks)

1. **Analytics Integration**
   - Add Google Analytics or Plausible
   - Track popular articles and topics
   - Understand audience behavior

2. **Performance Optimization**
   - ~~Image optimization pipeline~~ (done — lazy loading, external URLs, CSS fallbacks)
   - ~~Lazy loading for archive pages~~ (done — `loading="lazy"` on all non-hero images)
   - PWA support for offline reading

3. **A/B Testing Commentary Styles**
   - Test different commentary tones
   - Measure engagement differences

### Phase 4: Monetization Options (Future)

1. **Premium Content**
   - In-depth analysis reports
   - Early access to commentary
   - Exclusive insights

2. **Sponsorships**
   - Quantum company sponsorship slots
   - Job board integration
   - Event promotion

3. **Consulting Funnel**
   - Position as lead generation for quantum consulting
   - "Contact the Curator" functionality

### Phase 5: SERP Shield Integration

The Quantum Curator can coordinate with SERP Shield for comprehensive reputation management:

```bash
# Future CLI bridge commands
serp-shield curator sync    # Sync curated posts to SERP Shield
serp-shield curator status  # Show cross-platform status
```

This would allow:
- Curated quantum content to feed into broader SEO strategy
- Unified dashboard for all Mark Eatherly content
- Cross-promotion between platforms

---

## Configuration Reference

### Environment Variables

```bash
# Curator Identity
CURATOR_NAME=Mark Eatherly
CURATOR_BIO=Your bio here...

# Site Settings
SITE_NAME=Quantum Pulse
SITE_URL=https://subvurs.github.io/quantum-curator
SITE_DESCRIPTION=Daily curated quantum computing news

# API Keys
ANTHROPIC_API_KEY=sk-ant-...
NEWS_API_KEY=your-newsapi-key          # Optional
UNSPLASH_API_KEY=your-unsplash-key     # Optional — enables image generation for articles without images

# GitHub Deployment
GITHUB_REPO=https://github.com/subvurs/quantum-curator
GITHUB_USERNAME=subvurs

# Aggregation Settings
MIN_RELEVANCE_SCORE=0.3
MAX_ARTICLES_PER_DAY=30
```

### Adding New Sources

Edit `quantum_curator/sources/registry.py`:

```python
BUILTIN_SOURCES.append({
    "name": "New Source Name",
    "source_type": SourceType.RSS,
    "url": "https://example.com",
    "feed_url": "https://example.com/feed.xml",
    "fetch_interval_hours": 6,
})
```

Then re-run `quantum-curator init` to register the new source.

---

## Maintenance

### Regular Tasks

| Task | Frequency | Command |
|------|-----------|---------|
| Check status | Daily | `quantum-curator status` |
| Verify site | Weekly | Visit live site |
| Review posts | Weekly | `quantum-curator posts --limit 50` |
| Update sources | Monthly | Edit `registry.py`, run `init` |

### Troubleshooting

**No articles fetched?**
- Check `quantum-curator sources` for last fetch times
- Run `quantum-curator fetch --force` to bypass interval check
- Verify network connectivity

**AI commentary failing?**
- Check `ANTHROPIC_API_KEY` is set correctly
- Verify API key has available credits
- Fallback commentary will be used if API fails

**Site not updating?**
- Check GitHub Actions for workflow failures
- Verify `ANTHROPIC_API_KEY` secret is set in repo
- Run pipeline manually: `quantum-curator run --deploy`

---

## Summary

Quantum Curator transforms Mark Eatherly from a passive reader of quantum news into an active, authoritative curator. The system:

1. **Saves time**: Automates the entire content pipeline
2. **Builds authority**: Consistent, high-quality curation with expert commentary
3. **Scales effortlessly**: Handles any volume of news without additional work
4. **Establishes presence**: Creates a growing archive of curated content
5. **Enables growth**: Foundation for newsletter, social media, and more

The platform is live, automated, and ready to grow Mark Eatherly's presence in the quantum computing community.

---

## Magazine Layout Redesign (v1.1.0 — March 17, 2026)

### Motivation

The original front-end presented articles as a flat, uniform card grid — every article the same size, no images, scrolling required to see more than a few articles. This was functional but lacked the visual density and editorial hierarchy that makes news sites like Paper.li engaging.

The redesign transforms the homepage into a magazine-style layout that presents 15-20+ articles in a scannable, visually differentiated hierarchy without endless scrolling.

### What Changed

#### Backend — Image Pipeline

| File | Change |
|------|--------|
| `curator.py` | Fixed bug: `image_url` was not being copied from `RawArticle` to `CuratedPost` during curation. Added `image_url=article.image_url` to the `CuratedPost` constructor. |
| `image_extractor.py` | New module. Async function `extract_og_image(url)` fetches article HTML and extracts `og:image`, `twitter:image`, or first large `<img>`. 10-second timeout, graceful failure returns `""`. Uses existing httpx + BeautifulSoup dependencies. |
| `aggregator.py` | After scoring articles, runs OG image extraction on non-arXiv articles that lack `image_url`. Results are stored in the database and carried through to the published site. |

#### Builder — Tier Splitting

| File | Change |
|------|--------|
| `site/builder.py` | `_build_index()` now splits posts into three tiers: `hero_post` (1st article), `featured_posts` (next 3, image-bearing articles prioritized), and `topic_sections` (remainder grouped by primary topic, sorted by section size). |
| `site/builder.py` | `_build_topics()` now passes `featured_post` and `remaining_posts` to individual topic page templates. |
| `site/builder.py` | Added `has_image` Jinja filter and test. |

#### Templates

| File | Change |
|------|--------|
| `index.html` | Full rewrite. Three-tier layout: hero article, featured 3-column grid, topic-grouped compact lists. Digest rendered in compact form with fade-out gradient. Topic cloud and curator card preserved. |
| `post.html` | Added conditional hero image above article body. Added `og:image` and `twitter:card` meta tags for social sharing previews. |
| `topic.html` | First article rendered as a wide featured card with commentary. Remaining articles rendered as compact rows with thumbnails. |
| `base.html` | Added inline `<script>` before `</body>` for image error handling — replaces broken `<img>` tags with CSS gradient fallbacks. |

#### CSS (additive — all original 822 lines preserved)

| Section | Description |
|---------|-------------|
| Image fallback backgrounds | Per-topic CSS gradient placeholders with subtle gear icon. Applied when images are missing or fail to load. |
| Magazine hero | Full-width card, single-column when no image, 3:2 grid when image present (`has-image` class). Clamped summary and commentary (3 lines each). |
| Featured grid | 3-column responsive grid. Cards with 180px image area, topic tags, truncated summary. Image zoom on hover. `no-image` variant skips the image area. |
| Topic sections | Colored accent bar per topic. Section headers link to full topic pages. |
| Compact article list | Horizontal rows with 80x60 thumbnail (or 8px colored dot when no image), 2-line clamped title, source, date. 1px dividers between rows. |
| Post hero image | Full-width image on individual article pages, 400px max height, rounded corners. |
| Compact digest | Truncated with fade-out gradient overlay. |
| Responsive | Tablet (1024px): hero stacks, featured goes to 2-column. Mobile (768px): everything single-column, reduced thumbnail sizes. |

### Design Principles

1. **No wasted space**: When an article has no image, the layout adapts — hero collapses to text-only, featured cards skip the image area, compact rows show a small colored dot instead of an empty placeholder.
2. **Information density**: Hero shows commentary, featured shows summary, compact shows title only. Three tiers of detail let readers scan quickly.
3. **External images only**: No downloading, caching, or processing. Images are `<img src="...">` to external URLs. `loading="lazy"` on all non-hero images. Broken images gracefully fall back to CSS gradients.
4. **Topic color system**: 11 topic-specific colors applied consistently to tags, section accent bars, and gradient placeholders. Creates visual variety even with text-only articles.
5. **Progressive enhancement**: The site works without JavaScript. The inline script only provides image error recovery.

### Local Preview

```bash
# Build the site
quantum-curator build --output ./site_output

# Serve locally (CSS requires a web server due to absolute paths)
cd site_output && python -m http.server 8080
# Open http://localhost:8080
```

---

## SERP Shield Integration — markeatherly.com

**Deployed**: March 16, 2026
**Repo**: https://github.com/subvurs/markeatherly.com
**GitHub Pages**: https://subvurs.github.io/markeatherly.com/
**Custom domain** (pending DNS): https://markeatherly.com/

### What Was Built

The Quantum Curator's content and design now serve as the homepage for `markeatherly.com` — an exact-match personal domain that will rank for "Mark Eatherly" search queries. This connects the Quantum Curator's authority-building function directly to the SERP Shield reputation management system.

**Site structure**:

```
markeatherly.com/
├── index.html                          ← Quantum Curator homepage
│   ├── Hero: "Quantum Computing, Curated"
│   ├── Daily digest banner (March 16 digest)
│   ├── 6 latest curated quantum articles (cards with topic tags + commentary)
│   ├── Writing section (links to Nashville articles)
│   └── About card (links to full Quantum Pulse archive)
├── style.css                           ← Dark theme matching Quantum Curator
├── writing/                            ← SERP Shield backlink articles
│   ├── index.html
│   ├── community-engagement.html       ← 15 backlinks to .gov pages
│   ├── community-gardens.html          ← 9 backlinks
│   ├── language-access.html            ← 9 backlinks
│   └── public-records.html             ← 16 backlinks
├── CNAME, sitemap.xml, robots.txt
```

**Design**: Uses the Quantum Curator's exact dark theme palette (`--bg: #0f172a`, `--primary: #6366f1`, `--secondary: #06b6d4`), gradient text hero, card-based post grid with topic color coding, and responsive layout. The design language is consistent between the Quantum Pulse site and markeatherly.com so visitors moving between them experience a unified identity.

### How the Projects Connect

```
Quantum Curator (subvurs/quantum-curator)
│   Automated pipeline: fetch → score → curate → build → deploy
│   Live at: subvurs.github.io/quantum-curator/
│   Purpose: Build authority in quantum computing
│
├──► markeatherly.com (subvurs/markeatherly.com)
│       Homepage: Showcases latest Quantum Curator content
│       /writing/: Hosts SERP Shield backlink articles
│       Purpose: Exact-match domain for "Mark Eatherly" queries
│       Schema.org Person JSON-LD with sameAs links
│
SERP Shield (local, /Users/mvm/Desktop/serp-shield)
│   Manages: SERP scanning, discovery, content generation, publishing
│   Campaign: Mark Eatherly crisis response (60 days)
│   Purpose: Surface positive .gov pages, suppress negative results
│
└──► markeatherly.com /writing/ subpages
        49 backlinks to nashville.gov pages and media sources
        4 articles targeting different keyword clusters
```

**Data flow**:
- Quantum Curator generates curated quantum articles → featured on markeatherly.com homepage
- SERP Shield generates backlink articles → published to markeatherly.com/writing/ subpages
- Both projects deploy to repos under the `subvurs` GitHub account
- Schema.org `sameAs` on markeatherly.com links to both Quantum Pulse and GitHub profiles

### SERP Shield Context

The SERP Shield project (`/Users/mvm/Desktop/serp-shield`) is a reputation management tool that scans Google results, identifies threats, discovers positive existing pages (government meeting minutes, media coverage), and builds backlinks to surface them. The `markeatherly.com/writing/` articles each contain 9-16 links to Nashville .gov pages and media sources, creating the backlink infrastructure needed to improve those pages' search rankings.

Full details: `/Users/mvm/Desktop/serp-shield/SERP_SHIELD_OVERVIEW.md`

### What's Next for Integration

| Step | Action | Impact |
|------|--------|--------|
| 1 | **Configure DNS** for markeatherly.com | Enables the exact-match domain to start ranking |
| 2 | **Automate homepage updates** — Quantum Curator pipeline writes latest posts to markeatherly.com | Keeps homepage fresh without manual intervention |
| 3 | **Unified deployment** — Quantum Curator's `deploy` command updates both sites | Single pipeline maintains both Quantum Pulse and markeatherly.com |
| 4 | **Social integration** — Share quantum articles from markeatherly.com URLs | Builds domain authority through social signals |
| 5 | **Analytics** — Track which domain drives more engagement | Informs strategy for where to publish future content |

### DNS Setup Required

The domain registrar for markeatherly.com needs these records:

| Type | Name | Value |
|------|------|-------|
| A | @ | 185.199.108.153 |
| A | @ | 185.199.109.153 |
| A | @ | 185.199.110.153 |
| A | @ | 185.199.111.153 |
| CNAME | www | subvurs.github.io |

---

## Source Diversity & Image Generation (v1.2.0 — March 17, 2026)

### Problem

Despite having 17 registered sources, only arXiv papers were appearing in the curated feed. The RSS sources had never successfully fetched a single article. Most arXiv papers also had no images, leaving the magazine layout visually sparse.

### Root Causes Identified

Three separate issues prevented RSS sources from producing articles:

1. **No redirect following**: The RSS fetcher used `httpx.AsyncClient` with default `follow_redirects=False`. Sources like Microsoft Quantum Blog (301 → azure.microsoft.com) and IonQ Blog (301 → www.ionq.com) silently failed on every fetch.

2. **No User-Agent header**: The Quantum Insider returned 403 Forbidden because the default Python user agent was blocked. Phys.org returned 400 Bad Request for the same reason.

3. **Stale feed URLs**: IBM Quantum Blog removed their RSS feed entirely (404). Google AI Blog moved from Blogger to blog.google (404). Phys.org changed their RSS URL path structure (400).

### Changes Made

#### RSS Fetcher Fix (`sources/rss.py`)

Added `follow_redirects=True` and a descriptive `User-Agent` header to the httpx client:

```python
async with httpx.AsyncClient(
    timeout=self.timeout,
    follow_redirects=True,
    headers={"User-Agent": "QuantumCurator/1.0 (+https://quantum-pulse.github.io)"},
) as client:
```

This single change fixed Microsoft Quantum (301), IonQ (301), The Quantum Insider (403), and Phys.org (400).

#### Feed URL Fixes (`sources/registry.py`)

| Source | Old URL (broken) | New URL (working) |
|--------|-----------------|-------------------|
| IBM Quantum | `ibm.com/quantum/blog/rss` (404) | `medium.com/feed/qiskit` — IBM's quantum team publishes via Qiskit Medium |
| Google AI | `ai.googleblog.com/atom.xml` (404) | `blog.google/technology/research/rss/` — Google Research (includes Quantum AI) |
| Phys.org | `phys.org/rss-feed/physics-news/quantum-physics/` (400) | `phys.org/rss-feed/breaking/physics-news/quantum-physics/` — corrected path |

#### New Sources Added

| Source | Feed URL | Content |
|--------|----------|---------|
| Physics World - Quantum | `physicsworld.com/c/quantum/feed/` | Quantum-focused physics journalism |
| New Scientist - Physics | `newscientist.com/subject/physics/feed/` | General physics (filtered by relevance scoring) |

#### Source Registration Fix (`sources/registry.py`)

`register_builtin_sources()` previously created new database rows with fresh UUIDs on every `init` call, causing duplicates. Now uses source name as a stable key — existing sources are updated in place (e.g., fixed feed URLs), new sources are inserted.

#### Image Generation Module (`image_generator.py` — new)

For articles that still have no image after feed-level and OG extraction (common for arXiv papers), the curation step now searches Unsplash for a relevant stock photo:

1. **Article-specific query**: Builds a search query from the article's primary topic and title keywords (e.g., "algorithms Quantum Error Correction Surface Code")
2. **Topic fallback query**: If the specific query returns nothing, retries with a broad topic-based query (e.g., "quantum computer processor chip technology" for hardware articles)
3. **Persistent storage**: Downloaded images are saved to `data/images/{article_id[:8]}.jpg` and survive rebuilds. The build step copies them to `site_output/static/images/generated/`.

No additional API keys or dependencies required beyond Unsplash (free, 50 req/hour). The feature is enabled by default but gracefully degrades — without an `UNSPLASH_API_KEY`, articles simply fall through to the existing CSS gradient placeholders.

#### Config Changes (`config.py`)

| Setting | Type | Default | Purpose |
|---------|------|---------|---------|
| `unsplash_api_key` | str | `""` | Unsplash API access key for image search |
| `generate_images` | bool | `True` | Feature toggle for auto-image generation |

#### Curator Integration (`curator.py`)

`curate_article()` now calls `ensure_article_image()` after generating commentary, before saving the post. Only runs when `generate_images` is enabled and the article has no `image_url`.

#### Builder Integration (`site/builder.py`)

`_copy_static_assets()` now copies `data/images/*` into `site_output/static/images/generated/` so generated images are included in deployments.

### Verification Results

Test fetch with all fixes applied:

```
Total articles passing relevance filter: 228

Articles by source:
  Physics World - Quantum              120 articles  (79 with images)
  IonQ Blog                             44 articles  (44 with images)
  AWS Quantum Computing Blog            10 articles  (10 with images)
  Quantum Computing Report              10 articles  (10 with images)
  The Quantum Insider                   10 articles  (10 with images)
  Qiskit Blog (IBM)                      9 articles  (0 with images)
  Microsoft Quantum Blog                 8 articles  (8 with images)
  Phys.org Quantum                       8 articles  (8 with images)
  New Scientist - Physics                5 articles  (5 with images)
  Google Research Blog                   2 articles  (2 with images)
  Ars Technica - Science                 1 articles  (1 with images)
  MIT Technology Review                  1 articles  (1 with images)
```

Previously: 32 articles from arXiv only. Now: 228 articles from 12 different sources, most with native images.

### Files Changed

| File | Change |
|------|--------|
| `quantum_curator/image_generator.py` | **New** — Unsplash search with article-specific and topic fallback queries |
| `quantum_curator/config.py` | Added `unsplash_api_key` and `generate_images` settings |
| `quantum_curator/curator.py` | Calls `ensure_article_image()` during curation when image is missing |
| `quantum_curator/site/builder.py` | Copies `data/images/` into build output during `_copy_static_assets()` |
| `quantum_curator/sources/rss.py` | Added `follow_redirects=True` and `User-Agent` header to httpx client |
| `quantum_curator/sources/registry.py` | Fixed 3 broken feed URLs, added 2 new sources, fixed `register_builtin_sources()` to upsert by name |

---

## 60-Day Freshness Window & Schedule Change (v1.2.1 — March 17-18, 2026)

### Problem

The site accumulated stale articles over time. Old content from weeks or months ago appeared alongside fresh news on the homepage, topic pages, archive, search, and RSS feed. There was no mechanism to age out content. Separately, the twice-daily automation schedule (6 AM and 6 PM UTC) was more frequent than needed.

### Changes Made

#### Content Freshness Enforcement

**Config** (`config.py`):
- Added `max_article_age_days: int = 60` setting (env: `MAX_ARTICLE_AGE_DAYS`)
- Articles older than this window are dropped during fetch and excluded from all site pages

**Aggregator** (`aggregator.py`):
- After relevance scoring, articles with `published_at` older than `max_article_age_days` are filtered out before saving to the database
- Logs how many articles were dropped (e.g., "Dropped 12 articles older than 60 days")

**Database** (`db.py`):
- Fixed `list_posts()` `since` filter — previously used `OR` logic (`published_at >= ? OR curated_at >= ?`) which let old articles through if they were recently curated
- Now uses `COALESCE(published_at, curated_at) >= ?` which correctly checks the article's actual publication date

**Site Builder** (`site/builder.py`):
- Added `freshness_cutoff` computed once at build time from `max_article_age_days`
- Added `_get_fresh_posts()` helper that queries published posts within the freshness window
- All page-building methods now use `_get_fresh_posts()` instead of raw `db.list_curated_posts()`:
  - Homepage (`_build_index`)
  - Individual post pages (`_build_posts`)
  - Archive pages (`_build_archive`)
  - Topic pages (`_build_topics`)
  - RSS feed (`_build_rss_feed`)
  - Search index (`_build_search`)
  - Topic counts (`_get_topic_counts`)

This ensures every page on the site only shows content from the last 60 days, and old content naturally falls off without manual cleanup.

#### Schedule Change

**Workflow** (`.github/workflows/daily-curator.yml`):
- Changed from twice-daily (`0 6,18 * * *`) to once-daily (`0 6 * * *`)
- Runs at 6:00 AM UTC (11 PM PST / 2 AM EST)

### Files Changed

| File | Change |
|------|--------|
| `quantum_curator/config.py` | Added `max_article_age_days` setting (default: 60) |
| `quantum_curator/aggregator.py` | Added age filter after relevance scoring |
| `quantum_curator/db.py` | Fixed `list_posts()` since filter to use COALESCE |
| `quantum_curator/site/builder.py` | Added `freshness_cutoff`, `_get_fresh_posts()`, replaced all raw queries with freshness-filtered queries |
| `.github/workflows/daily-curator.yml` | Changed cron from `0 6,18 * * *` to `0 6 * * *` |

---

## Subvurs Research Connection Notes (v1.3.0 — March 18, 2026)

### Motivation

The Quantum Curator ingests dozens of quantum computing articles daily, many of which touch on concepts directly relevant to the Subvurs/Quasmology research program — phase transitions, noise-enhanced computation, variational algorithm improvements, error mitigation techniques, etc. Manually scanning every curated article for research connections is impractical.

This feature adds an automated internal research annotation layer: during curation, each article is analyzed for genuine connections to Subvurs concepts. The notes are stored in the database and saved as individual files, but never appear on the public site.

### What Changed

#### Model (`models.py`)

Added `subvurs_notes: str = ""` field to the `CuratedPost` model, after `meta_description`. This stores the AI-generated connection notes (or empty string if no connection found).

#### Config (`config.py`)

| Setting | Type | Default | Env Var | Purpose |
|---------|------|---------|---------|---------|
| `generate_subvurs_notes` | bool | `True` | `GENERATE_SUBVURS_NOTES` | Toggle Subvurs notes generation during curation |

#### Database (`db.py`)

| Change | Detail |
|--------|--------|
| CREATE TABLE | Added `subvurs_notes TEXT DEFAULT ''` column to `curated_posts` |
| Migration | `init_db()` runs `ALTER TABLE curated_posts ADD COLUMN subvurs_notes TEXT DEFAULT ''` in try/except — safe for both new and existing databases |
| INSERT | `save_post()` now includes `subvurs_notes` in column list and values tuple |
| SELECT | `_row_to_post()` reads `subvurs_notes` with safe fallback to `""` if column missing |

#### Curator (`curator.py`)

**New system prompt** — `SUBVURS_NOTES_SYSTEM_PROMPT` provides a concise summary of key Subvurs/Quasmology concepts for the AI to match against:

- Nyx equation and Chaos Valley (d=0.504)
- Inverse scaling / barren plateau avoidance
- Bidirectional coupling for error mitigation
- T=0.857 time symmetry split
- Pattern 51/69/76 triad
- DMC3 optimization, IQAS pipeline
- VQE/QAOA outperformance results
- Noise-enhanced computation
- Impax classical sensing advantage

The prompt instructs the model to return 1-3 specific sentences if a genuine connection exists, or exactly "None" if not. Speculation and forced connections are explicitly prohibited.

**New method** — `_generate_subvurs_notes(article)`:
- Uses `claude-haiku-4-20250414` for cost efficiency (~200 tokens prompt + ~100 tokens response per call)
- Returns empty string if API key is missing or if the model responds "None"
- Gated behind `settings.generate_subvurs_notes`

**New method** — `_save_subvurs_notes_file(article, notes)`:
- Saves each non-empty note as an individual markdown file in `data/subvurs_notes/`
- Filename format: `{YYYY-MM-DD}_{article-title-slug}.md`
- File contains article title, source, URL, date, and the connection notes
- Only called when notes are non-empty (articles with no connection produce no file)

**Integration** — `curate_article()` now generates Subvurs notes after commentary, saves the file if notes are non-empty, and includes `subvurs_notes` in the `CuratedPost` constructor.

#### CLI (`cli.py`)

**New command** — `quantum-curator insights`:

```bash
quantum-curator insights              # Show only posts with Subvurs connections
quantum-curator insights --all        # Show all posts, including those with no connections
quantum-curator insights --limit 50   # Scan more posts (default: 50)
```

Output: Rich table with Title, Date, and Subvurs Notes columns. Header panel shows count: "X of Y curated articles have connections."

### Storage

Subvurs notes are stored in two places:

1. **Database**: `subvurs_notes` column in `curated_posts` table at `data/curator.db`
2. **Files**: Individual markdown files in `data/subvurs_notes/` with date-prefixed filenames

```
data/
├── curator.db                              # subvurs_notes column in curated_posts
└── subvurs_notes/
    ├── 2026-03-18_quantum-error-correction-breakthrough.md
    ├── 2026-03-18_noise-enhanced-variational-algorithms.md
    └── ...
```

Each file contains:

```markdown
# Article Title

**Source:** Source Name
**URL:** https://...
**Date:** 2026-03-18

## Subvurs Connection

1-3 sentences describing the specific connection to Subvurs research.
```

### Cost

- Uses `claude-haiku-4-20250414` (not Sonnet) — approximately $0.001 per article
- ~200 tokens input + ~100 tokens output per call
- At 20 articles/day: ~$0.02/day, ~$0.60/month
- Can be disabled via `GENERATE_SUBVURS_NOTES=false` in `.env` or GitHub secrets

### Files Changed

| File | Change |
|------|--------|
| `quantum_curator/models.py` | Added `subvurs_notes` field to `CuratedPost` |
| `quantum_curator/config.py` | Added `generate_subvurs_notes` setting |
| `quantum_curator/db.py` | Added column to schema, migration, INSERT, and SELECT |
| `quantum_curator/curator.py` | Added `SUBVURS_NOTES_SYSTEM_PROMPT`, `_generate_subvurs_notes()`, `_save_subvurs_notes_file()`, integrated into `curate_article()` |
| `quantum_curator/cli.py` | Added `insights` command |

### Workflow Impact

No changes needed to `.github/workflows/daily-curator.yml` — the notes are generated during the existing `curate` step. The `insights` command is for local use only; it is not part of the automated pipeline.

---

*Document updated: March 18, 2026*
*Quantum Curator v1.3.0 — Subvurs research connection notes*
