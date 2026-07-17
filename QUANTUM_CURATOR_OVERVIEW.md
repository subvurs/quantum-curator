# Quantum Curator: Project Overview

**Version**: 1.4.0
**Created**: March 16, 2026
**Author**: Mark Eatherly
**Repository**: https://github.com/subvurs/quantum-curator
**Live Site**: https://subvurs.github.io/quantum-curator/
**Qrater Dashboard**: https://subvurs.github.io/qrater/

---

## Executive Summary

Quantum Curator is an automated news aggregation and curation platform that collects, filters, analyzes, and publishes daily quantum computing news. The system pulls from 19 authoritative sources, scores articles for relevance, generates AI-powered expert commentary using Claude, auto-generates images for articles without them, and publishes a beautiful static site to GitHub Pages—all automatically, once daily.

The platform has two public faces:
- **Quantum Crier** — the main editorial site with magazine-style layout, article pages, and daily digests
- **Qrater** — an interactive dashboard where users can filter, sort, and explore all curated content by topic, date, source, and relevance

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
│   ├── cli.py               # Command-line interface (13 commands)
│   ├── config.py            # Configuration management with pydantic-settings
│   ├── models.py            # Data models (Source, Article, Post, Digest)
│   ├── db.py                # SQLite database layer
│   ├── sources/
│   │   ├── registry.py      # 19 built-in quantum news sources
│   │   ├── rss.py           # RSS/Atom feed parser (follows redirects, sets UA)
│   │   ├── arxiv.py         # arXiv API integration
│   │   └── news.py          # NewsAPI integration (extracts images)
│   └── site/
│       ├── builder.py       # Quantum Crier static site generator with tier-splitting logic
│       ├── qrater_builder.py # Qrater interactive dashboard generator
│       ├── templates/       # Jinja2 HTML templates (9 Crier + 1 Qrater)
│       ├── static/css/      # Magazine-style dark-theme stylesheet (Crier)
│       └── static/qrater/   # Qrater CSS and JS (client-side filtering)
├── .github/workflows/
│   └── daily-curator.yml    # Automated daily pipeline (Crier + Qrater)
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

### 8. Qrater Interactive Dashboard

**Live at**: https://subvurs.github.io/qrater/

Qrater is a single-page dashboard that presents all curated content in a filterable, sortable interface. It is built from the same database as Quantum Crier but serves a different use case — interactive exploration rather than editorial presentation.

**Architecture**:
- `QraterBuilder` generates a static single-page app at build time
- All article data is exported to `data/articles.json` (title, summary, topics, source, date, relevance score, commentary, URLs)
- Client-side JavaScript handles all filtering and sorting — no server required
- Deployed to its own GitHub repo (`subvurs/qrater`) on the `gh-pages` branch

**Features**:
- **Topic filtering**: Checkbox list with per-topic article counts; color-coded topic tags matching Quantum Crier's palette. Select All / Clear All buttons.
- **Date range**: Preset buttons (Today, This Week, This Month, All Time) plus custom date range inputs
- **Source filtering**: Dropdown menu listing all active sources
- **Sort options**: Newest First (default), Oldest First, Relevance Score
- **Article cards**: Image, topic tags, title (links to original article), summary, curator commentary (italic, bordered), source, date, and relevance badge
- **Email signup**: Buttondown-powered form with topic checkboxes for personalized subscriptions (when configured)
- **Mobile responsive**: Filter sidebar collapses to a slide-out panel with toggle button on mobile (<768px)

**Content policy**: Qrater includes ALL published posts regardless of age (no freshness window), sorted newest first by default. This lets users explore the full archive while keeping fresh content prominent. The Quantum Crier editorial site uses the 60-day freshness window for its pages.

**Cross-links**:
- Quantum Crier header nav includes a "Qrater" link
- Qrater header nav links back to "Quantum Crier"
- Each article card in Qrater links to both the original source URL and the Quantum Crier post page

**Footer**: "Powered by Quantum Crier — A Subvurs Project — Founded by Mark Eatherly"

### 9. Automated Deployment

GitHub Actions runs the full pipeline once daily:
1. Fetch articles from all 19 sources
2. Score and filter for relevance
3. Generate AI commentary + fetch Unsplash images for articles without one
4. Create daily digest
5. Build Quantum Crier static site
6. Build Qrater dashboard
7. Deploy Quantum Crier to `subvurs/quantum-curator` gh-pages
8. Deploy Qrater to `subvurs/qrater` gh-pages (via `DEPLOY_TOKEN` PAT)

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
│                    ┌──────────┐    ┌──────────┐                  │
│                    │  DEPLOY  │    │  DEPLOY  │                  │
│                    │  CRIER   │    │  QRATER  │                  │
│                    └──────────┘    └──────────┘                  │
│                         │               │                        │
│                         ▼               ▼                        │
│                   GitHub Pages    GitHub Pages                   │
│            subvurs.github.io/    subvurs.github.io/              │
│              quantum-curator         qrater                      │
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

# Qrater interactive dashboard
quantum-curator build-qrater           # Build the Qrater dashboard
quantum-curator build-qrater --output ./qrater_public
quantum-curator deploy-qrater          # Deploy Qrater to its GitHub repo
quantum-curator deploy-qrater --verify

# Run full pipeline (builds both Crier and Qrater)
quantum-curator run                    # fetch → curate → build both
quantum-curator run --deploy           # Include deployment of both sites

# Status and information
quantum-curator status                 # Show statistics
quantum-curator sources                # List configured sources
quantum-curator posts                  # List curated posts
quantum-curator config                 # Show configuration (includes Qrater settings)
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
| Content freshness window | ✅ Operational (60-day default on Crier, no limit on Qrater) |
| Subvurs research notes | ✅ Operational (Haiku-powered, file + DB storage) |
| Qrater dashboard | ✅ Live (topic/date/source filtering, client-side JS) |
| Qrater deployment | ✅ Operational (separate repo, DEPLOY_TOKEN PAT) |
| Cross-site links | ✅ Operational (Crier ↔ Qrater header nav) |
| Bluesky sharing | ✅ Live (@markeatherly.bsky.social, up to 5 posts/day) |
| Twitter/X sharing | ✅ Live (@MarkEatherly, up to 5 posts/day) |
| Daily insights email | ✅ Operational (Subvurs connections emailed to subvurs@gmail.com) |
| Automated pipeline | ✅ Configured (once daily at 6 AM UTC, deploys both sites + social sharing + insights email) |

### Content Capacity

- **19 sources** across arXiv, RSS feeds, and NewsAPI
- **228 articles** from 12 different sources in a single fetch (test run)
- Relevance filtering reduces to quantum-specific articles only
- AI commentary generated per article, daily digest per day

### Live Sites

- **Quantum Crier**: https://subvurs.github.io/quantum-curator/
- **Qrater Dashboard**: https://subvurs.github.io/qrater/
- **Qrater Repo**: https://github.com/subvurs/qrater

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

1. ~~**Social Media Integration**~~ (done — see Social Sharing section below)
   - ~~Auto-post to Twitter/X with article highlights~~
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

## Qrater Interactive Dashboard (v1.4.0 — March 18, 2026)

### What Is Qrater

Qrater is an interactive single-page dashboard that presents all curated quantum computing content in a filterable, sortable interface. It complements Quantum Crier (the editorial site) by giving users full control over what they see — filter by topic, narrow by date range, choose a source, sort by relevance or recency.

**Live at**: https://subvurs.github.io/qrater/
**Repository**: https://github.com/subvurs/qrater

### How It Works

The `QraterBuilder` class generates a static single-page application at build time:

1. Queries all published posts from the database (no freshness limit — content accumulates over time)
2. Exports article data to `data/articles.json` (title, summary, topics, source, date, relevance score, commentary, URLs)
3. Renders `index.html` from a Jinja2 template with server-side topic counts, source lists, and build timestamp
4. Copies `qrater.css` and `qrater.js` as static assets
5. Adds `.nojekyll` for GitHub Pages compatibility

All filtering and sorting happens client-side in JavaScript — no server, no API, no database at runtime.

### Content Strategy

| Aspect | Quantum Crier | Qrater |
|--------|--------------|--------|
| Content window | 60-day freshness cutoff | All published posts, no limit |
| Default sort | Editorial layout (hero → featured → topics) | Newest first |
| User control | Browse by topic page or search | Filter by topic, date range, source; sort by date or relevance |
| Growth | Rolling 60-day window | Accumulates all content over time |

This means Qrater's article count will grow with every daily pipeline run. Users who want to explore older content can do so; users who want only the latest can use the date range presets.

### Files Created

| File | Purpose |
|------|---------|
| `quantum_curator/site/qrater_builder.py` | Static site generator (131 lines) — builds index.html, articles.json, copies assets |
| `quantum_curator/site/templates/qrater/index.html` | Jinja2 template — header, filter sidebar, article grid, email signup, footer |
| `quantum_curator/site/static/qrater/qrater.css` | Full stylesheet (579 lines) — dark theme, responsive grid, topic colors, card design |
| `quantum_curator/site/static/qrater/qrater.js` | Client-side logic (292 lines) — fetch JSON, filter/sort/render, event binding |

### Files Modified

| File | Change |
|------|--------|
| `quantum_curator/site/__init__.py` | Added `QraterBuilder` and `build_qrater` exports |
| `quantum_curator/config.py` | Added Qrater settings: `qrater_output_dir`, `qrater_github_repo`, `qrater_site_url`, `buttondown_username` |
| `quantum_curator/cli.py` | Added `build-qrater` and `deploy-qrater` commands; integrated Qrater into `run` pipeline and `config` output |
| `quantum_curator/site/templates/base.html` | Added "Qrater" link in Quantum Crier header nav |
| `.github/workflows/daily-curator.yml` | Added Qrater build step and cross-repo deploy step using `DEPLOY_TOKEN` |

### Config Settings

| Setting | Default | Env Var | Purpose |
|---------|---------|---------|---------|
| `qrater_output_dir` | `qrater_output` | `QRATER_OUTPUT_DIR` | Build output directory |
| `qrater_github_repo` | `qrater` | `QRATER_GITHUB_REPO` | GitHub repo name for deployment |
| `qrater_site_url` | `https://subvurs.github.io/qrater` | `QRATER_SITE_URL` | Published URL |
| `buttondown_username` | `""` | `BUTTONDOWN_USERNAME` | Newsletter signup (optional) |

### CLI Commands

```bash
quantum-curator build-qrater                 # Build dashboard to qrater_output/
quantum-curator build-qrater --output ./dir  # Custom output directory
quantum-curator build-qrater --no-clean      # Don't wipe output first
quantum-curator deploy-qrater                # Deploy to subvurs/qrater gh-pages
quantum-curator deploy-qrater --verify       # Verify deployment is accessible
```

Both commands are also integrated into the `run` pipeline — `quantum-curator run --deploy` builds and deploys both Quantum Crier and Qrater.

### Deployment

Qrater is deployed to a separate GitHub repository (`subvurs/qrater`) on its `gh-pages` branch.

**CI deployment** uses a Personal Access Token stored as the `DEPLOY_TOKEN` secret on the `quantum-curator` repo. The workflow step:
1. Builds Qrater to `./qrater_public`
2. Initializes a git repo in the output directory
3. Force-pushes to `subvurs/qrater` gh-pages using the PAT

**Manual deployment**: `quantum-curator deploy-qrater` uses the `GitHubPagesPublisher` class, which clones the target repo, replaces content, commits, and pushes.

### Design

**Dark theme** matching Quantum Crier's palette:
- Background: `#0f172a` (slate-900)
- Cards: `#1e293b` (slate-800)
- Primary: `#6366f1` (indigo)
- Secondary: `#06b6d4` (cyan)

**11 topic colors** for tags and sidebar labels: hardware (amber), algorithms (violet), error correction (red), cryptography (teal), machine learning (pink), simulation (blue), sensing (emerald), industry (orange), research (indigo), policy (slate), general (gray).

**Responsive**: Desktop shows a 280px sticky sidebar + article grid. Mobile (<768px) collapses sidebar to a slide-out panel with a filter toggle button in the header.

**Footer**: "Powered by Quantum Crier — A Subvurs Project — Founded by Mark Eatherly"

---

## Social Sharing — Bluesky & Twitter/X (v1.5.0 — April 2, 2026)

### What Was Added

Automated social media posting to Bluesky and Twitter/X. After each daily curation run, newly published articles are shared to both platforms as @markeatherly with title, commentary excerpt, hashtags, and a link card.

### Architecture

Two new modules follow the same pattern:

| Module | Platform | Auth Method | Char Limit | Library |
|--------|----------|-------------|------------|---------|
| `bluesky.py` | Bluesky | AT Protocol (handle + app password) | 300 | `httpx` (raw AT Protocol API) |
| `twitter.py` | Twitter/X | OAuth 1.0a (4 keys) | 280 | `tweepy` |

Both modules include:
- `*Sharer` class with `is_configured`, `share_post()`, `share_pending()`
- Text builder that formats title + commentary excerpt + topic hashtags within platform limits
- Database table to track which posts have been shared (prevents duplicates)
- Graceful degradation — returns False/empty if not configured

### Post Format

**Bluesky** (300 chars + link card with thumbnail):
```
Probing many-body localization crossover in quasiperiodic Floquet circuits

An interesting development in hardware.

#QuantumHardware #QuantumSimulation #QuantumSensing

[Link Card: title, description, thumbnail — outside char limit]
```

**Twitter/X** (280 chars, URL counts as 23):
```
Probing many-body localization crossover in quasiperiodic Floquet circuits

An interesting development in hardware.

#QuantumHardware #QuantumSimulation #QuantumSensing

https://arxiv.org/abs/2603.12675v1
```

Twitter auto-generates a link card from the URL. Bluesky embeds are built explicitly with optional thumbnail upload (images >1MB are skipped).

### CLI Commands

```bash
# Bluesky
quantum-curator share                    # Share up to 5 pending posts
quantum-curator share --limit 3          # Share up to 3
quantum-curator share --dry-run          # Preview what would be shared

# Twitter/X
quantum-curator tweet                    # Tweet up to 5 pending posts
quantum-curator tweet --limit 3          # Tweet up to 3
quantum-curator tweet --dry-run          # Preview what would be tweeted
```

Both commands are also integrated into the `run` pipeline — `quantum-curator run --deploy` shares to both platforms after deployment (when configured).

### Database

Two new tables track share history:

```sql
-- Bluesky
CREATE TABLE bluesky_shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL UNIQUE,
    bsky_uri TEXT NOT NULL,
    bsky_cid TEXT NOT NULL,
    shared_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Twitter/X
CREATE TABLE twitter_shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL UNIQUE,
    tweet_id TEXT NOT NULL,
    shared_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Posts are queried via `LEFT JOIN` to find published posts not yet shared to each platform.

### Configuration

```bash
# .env
BLUESKY_HANDLE=markeatherly.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx

TWITTER_CONSUMER_KEY=...
TWITTER_CONSUMER_SECRET=...
TWITTER_ACCESS_TOKEN=...
TWITTER_ACCESS_TOKEN_SECRET=...
```

Config properties `has_bluesky` and `has_twitter` gate all social features — if credentials are missing, the pipeline skips sharing silently.

### GitHub Actions Integration

The daily workflow (`.github/workflows/daily-curator.yml`) includes two share steps after deployment:

```yaml
- name: Share to Bluesky
  continue-on-error: true
  run: quantum-curator share --limit 5

- name: Share to Twitter/X
  continue-on-error: true
  run: quantum-curator tweet --limit 5
```

Both use `continue-on-error: true` so social posting failures don't break the pipeline. All six secrets (`BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD`, `TWITTER_CONSUMER_KEY`, `TWITTER_CONSUMER_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_TOKEN_SECRET`) are configured as GitHub Actions secrets.

### Posting Schedule

Up to 5 posts per platform, once daily at 6:00 AM UTC (2 AM EST), in a single batch after the curation pipeline completes.

### Cost

- **Bluesky**: Free (no API fees)
- **Twitter/X**: Pay-per-use credits (as of February 2026). ~$5 lasts months at 5 tweets/day

### Files Created

| File | Purpose |
|------|---------|
| `quantum_curator/bluesky.py` | Bluesky sharing module (BlueskySharer + DB helpers) |
| `quantum_curator/twitter.py` | Twitter/X sharing module (TwitterSharer + DB helpers) |

### Files Modified

| File | Change |
|------|--------|
| `quantum_curator/config.py` | Added Bluesky + Twitter settings and `has_bluesky` / `has_twitter` properties; added Bluesky to `social_links` |
| `quantum_curator/db.py` | Added `bluesky_shares` and `twitter_shares` tables to schema |
| `quantum_curator/cli.py` | Added `share` and `tweet` commands; added Step 5 (social sharing) to `run` pipeline |
| `pyproject.toml` | Added `atproto>=0.0.46` and `tweepy>=4.14.0` dependencies |
| `.github/workflows/daily-curator.yml` | Added 6 secrets to env block; added Bluesky and Twitter share steps |

### Current Status

| Platform | Status | Profile |
|----------|--------|---------|
| Bluesky | ✅ Live and posting | [@markeatherly.bsky.social](https://bsky.app/profile/markeatherly.bsky.social) |
| Twitter/X | ✅ Live and posting | [@MarkEatherly](https://x.com/MarkEatherly) |

---

## Daily Insights Email & Subvurs Notes Fix (v1.5.1 — April 2, 2026)

### Bug Fix: Subvurs Notes Not Generating

The Subvurs research connection notes feature (v1.3.0) was silently failing since it was deployed. Two issues:

1. **Invalid model ID**: The code referenced `claude-haiku-4-20250514`, a model that doesn't exist. Every API call returned a 404 error, which was caught and silently produced empty notes. Fixed to use `claude-3-haiku-20240307`.

2. **Incomplete "None" filtering**: When the AI found no connection, it returned responses starting with "None" followed by an explanation (e.g., "None\n\nThis article does not..."). The code only checked `if notes.lower() == "none"`, missing these multi-line responses. Fixed to `if notes.lower().startswith("none")`.

After fixing, a backfill of all 28 existing posts found **5 articles with genuine Subvurs connections** (noise-enhanced computation, T=0.857 time symmetry, Hamiltonian simulation, IQAS hybrid architectures, and inverse scaling).

### Daily Insights Email

A new daily email report sends Subvurs research connection findings to `subvurs@gmail.com` after each pipeline run. This ensures research connections are never missed.

**Module**: `quantum_curator/email_report.py`

**What the email contains**:
- Header with date, article count, and connection count
- Table of articles with Subvurs connections: article title (linked), source, date, and the connection notes
- List of other curated articles with no connections (for reference)
- Styled HTML matching the Quantum Crier dark theme

**CLI Command**:

```bash
quantum-curator email-insights              # Send today's report
quantum-curator email-insights --days 7     # Look back 7 days
quantum-curator email-insights --dry-run    # Preview without sending
```

Also integrated into the `run` pipeline as Step 6 (after social sharing), gated on `settings.has_email`.

### Configuration

```bash
# .env
SMTP_EMAIL=subvurs@gmail.com
SMTP_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx    # Gmail app password
```

Uses Python's built-in `smtplib` with Gmail SMTP over SSL (port 465). No additional dependencies.

### GitHub Actions Integration

```yaml
- name: Email Subvurs insights report
  continue-on-error: true
  run: quantum-curator email-insights
```

Two secrets added: `SMTP_EMAIL`, `SMTP_APP_PASSWORD`.

### Files Created

| File | Purpose |
|------|---------|
| `quantum_curator/email_report.py` | HTML report builder + Gmail SMTP sender |

### Files Modified

| File | Change |
|------|--------|
| `quantum_curator/curator.py` | Fixed model ID (`claude-3-haiku-20240307`); fixed "None" detection (`startswith`) |
| `quantum_curator/config.py` | Added `smtp_email`, `smtp_app_password` settings and `has_email` property |
| `quantum_curator/cli.py` | Added `email-insights` command; added Step 6 (email report) to `run` pipeline |
| `.github/workflows/daily-curator.yml` | Added `SMTP_EMAIL` and `SMTP_APP_PASSWORD` to env block; added email step |

---

## SUBVURS_NOTES Prompt Refresh — 11 Commercial Paths (v1.6.0 — May 15, 2026)

### Why

The Subvurs Notes prompt last touched in v1.5.1 (April 2, 2026) was frozen
against the March 2026 snapshot of Subvurs research framing. Six weeks of
project evolution and two falsification events later, an audit of the
canonical CI-cached `data/curator.db` against the last 95 daily insights
emails surfaced a quantified drift problem:

| Framing in generated notes | Rate over last 95 emails | Status in Subvurs |
|----------------------------|--------------------------|-------------------|
| Pattern 67-69-76 triad as error-correction state machine | **38%** | Disproved March 2026 (5 hardware experiments on IBM Torino) |
| "Noise-enhanced computation" / noise resilience claims | **52%** | Reattributed to circuit simplicity (Pattern 76 finding, April 2026) |
| DMC3 / IQAS framing | **35%** | Stale codenames; superseded by Hive Keyboard + Qstruct + production paths |
| Any reference to active commercial paths (a–h) | **0%** | None of the 8 paths nor public-interest Qwashed surfaced once |

The prompt was producing notes that read as on-brand for legacy theory
but didn't connect any article to a project Mark could actually ship.

### What changed

The `SUBVURS_NOTES_SYSTEM_PROMPT` constant in `quantum_curator/curator.py`
(previously ~22 lines, March 18 vintage) was replaced with a ~70-line
four-block structure:

**Block 1 — CORE THEORY** (kept): Nyx equation, Chaos Valley as a band
[0.4, 0.6] with the cliff at d=0.6 (April 25, 2026 117k-trial sweep), the
T=0.857 73.4/26.6 split, inverse scaling, P51/P126, bidirectional
84% advantage. Reframed away from "peak at d=0.504" toward
"structured-emergence band with hard cliff at d=0.6."

**Block 2 — ACTIVE COMMERCIAL PATHS** (new): 11 surfaces each with anchor
papers, validation status (tests passing, backends used, hardware job
IDs where applicable), competitive context, and a "Relevant articles:"
trigger list to pattern-match incoming Curator articles:

1. **Qfabric** (path_a) — cross-vendor compute fabric; v0.3.0-dev, 249/252 tests, IBM Fez+Kingston two-Bell hardware run, wire-cut LCU Option B routing (γ²=25 per CX)
2. **NyxChem** (path_b) — quantum chemistry
3. **NyxNet** (path_c) — distributed quantum networking control plane; Werner-state EPR memory, Planner+Repeater+Distillation+Scheduler
4. **Questimator** (path_c sub) — γ-estimator; 9k-trial benchmark wins every cell, hardware pilot on ibm_marrakesh (job d7kn6ta8ui0s73b5fd30)
5. **QCert** (path_d) — classical info-theoretic BB84+MDI-QKD certification auditor; v0.1.0, 59/59 tests, EAT finite-key + Ed25519 signing, Nyx-free
6. **Qalyx** (path_e) — quantum hardware layer; v0.9.3, 550+ tests, QHAL v0.1.1 alignment, HERALDED_ERASE LER 2.00% → 0.70%
7. **QJobLake** (path_f) — quantum job lakehouse
8. **bioreg** (path_g) — biometric registry; v0.0.3, 236 tests, voice MFCC-128 + Merkle + Ed25519, fuzzy extractor through 16 byte errors
9. **NyxFiber** (path_h) — QKD-classical fiber coexistence scheduler; v0.0.3 literature pass complete, all three gating PDFs read, no code yet
10. **Qwashed** (public_interest) — HNDL auditor + hybrid-PQ vault; v0.1.0 alpha, 417 tests, X25519‖ML-KEM-768 + Ed25519‖ML-DSA-65, Apache-2.0, Nyx-free
11. **Hive Keyboard / Qstruct** — deterministic state addressing; 256/256 patterns at 100% fidelity, +1175× vs QAOA on MaxCut

**Block 3 — DO NOT USE** (new): explicit retirement list of 7 falsified
or stale framings, each labeled with the falsification event and date:

1. 67-69-76 triad as error-correction state machine — disproved March 2026
2. "Noise-enhanced computation" as a quantum mechanism — reattributed to circuit simplicity April 2026
3. DMC3 codename — stale, superseded by Hive/Qstruct
4. IQAS 144.9Q× quantum advantage — speculative single-trial result
5. "62× advantage of H2O ground-state vs VQE" — single-config result, not generalized
6. "21.3% bidirectional error mitigation" as a universal constant — application-specific
7. NyxSolver-as-SOTA on classical optimization — non-competitive vs Gurobi on knapsack despite the ridge tuning gain

**Block 4 — RULES** (new):
- Default to `None` when no genuine connection exists — false positives
  are worse than misses
- Prefer commercial-path connections over pure-theory connections when both apply
- Never invoke any DO NOT USE framing, even if the article superficially echoes it
- When connecting to a commercial path, name the specific module/test/job ID where possible

### Quantified expectation

If the next 95 emails show the same connection rate on legitimate
articles (~5%) but reroute the framing distribution toward commercial
paths and away from the DO NOT USE list, the refresh worked. The
canonical DB lands as a CI artifact each morning
(`actions/upload-artifact@v4` step added in commit b0612ee), so the
post-refresh distribution is auditable on the same axes as the pre-
refresh audit above.

### Files Modified

| File | Change |
|------|--------|
| `quantum_curator/curator.py` | Replaced `SUBVURS_NOTES_SYSTEM_PROMPT` (lines 37–58) with four-block 11-path refresh |

### Commits

- **7149b74** — `Refresh SUBVURS_NOTES prompt: 11 commercial paths, drop falsified framings`
- **b0612ee** — (previous) `daily-curator.yml: upload curator.db as artifact`

### Out of scope (intentional)

- No code changes outside `curator.py`. The note-generation loop, the
  None-detection logic (fixed in v1.5.1), and the model ID
  (`claude-3-haiku-20240307`, also fixed in v1.5.1) all remain.
- No prompt-evaluation harness yet. Verification is by reading the
  next ~2 weeks of daily insights emails plus an audit query against
  the cached `subvurs_notes` column. If drift recurs, a regression
  test that pattern-matches the DO NOT USE phrases against fresh
  generations would be the next step.

---

## Q-day Clock Manifest Export (v1.7.0 — June 19–27, 2026)

### What was added

Each daily Curator run now produces a **signed Ed25519 CuratorManifest**
and force-pushes it to a dedicated `manifest` branch on
`subvurs/quantum-curator`. Downstream, the Q-day Clock
(`subvurs/qday-clock`) workflow pulls that manifest, verifies the
signature against a pinned public key, and feeds the classified
articles into its 5-axis clock-score computation. This wires Curator's
accumulated quantum-computing corpus into Q-day Clock's
"how close are we to a cryptographically-relevant quantum computer"
reading.

### Components shipped

1. **`quantum_curator/qday_export.py` + `qday-export` CLI subcommand**
   (commits `7847250`, `55efcfa`). Filters `raw_articles` to the four
   Q-day-relevant `ContentTopic` values (HARDWARE, ALGORITHMS,
   ERROR_CORRECTION, CRYPTOGRAPHY), builds a `CuratorManifest`
   (Q-day Clock's pydantic schema imported directly so the signed
   shape cannot silently drift), signs with
   `qday_clock.core.signing.SigningKey.sign_payload()`.

2. **`qday-clock` dependency pin** in `pyproject.toml`:
   ```
   qday-clock @ git+https://github.com/subvurs/qday-clock.git@v0.2.5
   ```
   Tag-pinned so a signing-API bump can't silently break the daily
   export. `[tool.hatch.metadata] allow-direct-references = true`
   scoped narrowly to the qday-clock pin.

3. **K11 daily-pipeline wiring** (`subvurs_export/deploy/curator/`):
   - `env.daily.template`: `QDAY_SIGNING_KEY_PATH`,
     `QDAY_MANIFEST_PUSH_URL`, `QDAY_MANIFEST_BRANCH=manifest`.
   - `run_curator_daily.sh`: appended a qday-export step
     after the regular daily run that signs and force-pushes the
     manifest. If either the key path or push URL is unset, the
     step logs a skip and the rest of the daily run is unaffected.
   - Orphan-style force-push (single file `curator_manifest.json`
     on a single-commit branch — no history, no `.git` pollution
     of `gh-pages`).

4. **Server-side Ed25519 keygen on K11** (no key material left the
   box): generated via `SigningKey.generate()` inside the curator
   venv, written to `~/quantum-curator/.qday_signing_key` (mode
   0600). Public key
   `w2jrKwsAQoSBOq8wgqEVIQd0gzs56/KmMBLFuXUy+d0=` registered as
   `QDAY_CURATOR_PUBKEY_B64` GitHub repo secret on
   `subvurs/qday-clock`.

### End-to-end smoke (2026-06-27)

Verified live, all steps captured in
`subvurs_export/deploy/K11_DEPLOYMENT_STATUS.txt` items 8–9:

| Stage | Evidence |
|---|---|
| K11 `qday-export` | 167 articles, 240801 bytes, local `verify_payload=True` |
| Force-push → manifest branch | commit `33152bb` on `subvurs/quantum-curator` |
| `raw.githubusercontent.com` | HTTP 200, byte-identical 240801 bytes |
| Q-day Clock workflow | run [28272654436](https://github.com/subvurs/qday-clock/actions/runs/28272654436) — Install + Fetch + Recompute + Diff all green in 23s |
| Signature verified | log: `refresh: ingested manifest with 167 articles, commit=55efcfa5c591` |
| Clock state | `clock_score=0.4153 clock_hours=14.03` |
| Refresh PR | not opened — recomputed JSON byte-identical to current `main` (deterministic, expected) |

### Pre-existing bug found during smoke

The first workflow_dispatch attempt (run `28272363714`) failed at
`Install Q-day Clock` because `subvurs/qday-clock/.github/workflows/refresh.yml`
still had a `defaults: run: working-directory: public_interest/qday_clock`
block left over from when `qday-clock` was a subdirectory of the
Subvurs monorepo. The standalone repo has `qday_clock/` at the root.
PR CI had never caught this because PR CI only runs the tests job,
not the refresh job. Fixed in
[qday-clock PR #2](https://github.com/subvurs/qday-clock/pull/2)
(squash-merged as commit `cc320f8`); the re-run succeeded.

### What this changes for Curator's daily run

- Adds one new step at the end of `run_curator_daily.sh` (qday-export
  + force-push); skipped cleanly if either env var is unset.
- No Curator schema changes, no impact on the existing Crier or
  Qrater publish paths.
- Adds one repo-side dependency (`qday-clock`) pulled from GitHub at
  tag `v0.2.5`.
- No new cloud spend — the qday-export step runs entirely on K11
  with the local signing key; no LLM or API calls.

### What is intentionally NOT yet done

The Q-day Clock daily cron (08:00 UTC on
`subvurs/qday-clock` via `refresh.yml`) is enabled
([PR #1](https://github.com/subvurs/qday-clock/pull/1) merged
2026-06-27 as commit `d1bd6b6a`) but currently runs in **seeds-only
mode** because `inputs.curator_manifest_url` is empty under cron.
A follow-on PR will default that input to
`https://raw.githubusercontent.com/subvurs/quantum-curator/manifest/curator_manifest.json`
so the cron path actually consumes today's wiring. Two-PR split is
intentional per rigor §1 — each behavior change reviewable on its
own; the URL default waited until after the smoke proved the URL
is serving content.

### Distribution rationale (one repo, one secret, one auth boundary)

The manifest is published to the **manifest** branch of
`subvurs/quantum-curator` rather than to a new repo because:
1. one auth token (the curator deploy token) already has push rights
   to the curator repo;
2. `gh-pages` deploy is unaffected — different branch, different
   workflow, no contention;
3. `raw.githubusercontent.com` serves the JSON immediately on push,
   no Pages build delay; and
4. force-pushing a single-file orphan branch keeps the manifest
   branch's history at exactly one commit, which is what the
   pubkey-pinned consumer expects.

---

## Context Realignment, Site Redesign & Bluesky Fixes (v1.8.0 — July 14, 2026)

Three independent workstreams shipped as three separately revertible
commits (context realignment / site redesign / Bluesky fixes), plus a
production diagnostic on K11 that preceded any code change.

### Phase 0 — TL;DR-post outage root cause (K11, diagnosed first)

The daily Bluesky TL;DR summary had stopped appearing. Journal +
`bluesky_daily_summaries` inspection on K11 confirmed the root cause
was **router failure, not the share path**: `LLM call failed: router
returned empty answer (tier=unavailable)` → `build_daily_summary()`
returns None → CLI logs "Summary unavailable — aborting share" and the
`soft()` wrapper keeps the rest of the pipeline green. Fix applied to
`~/quantum-curator/.env.daily` on K11 (backup
`.env.daily.bak-20260714`): `ROUTER_TIMEOUT_SEC=1500`,
`ROUTER_OLLAMA_READ_TIMEOUT=1200`, `ROUTER_OLLAMA_CLOUD_ENABLED=true`,
`ROUTER_CLOUD_PRIMARY=ollama`. Verification dry-run on K11
(`share-intel-summary --days 1 --dry-run`, commit state `b40ff7f`)
completed exit 0 with a rendered summary. The latent recording bug on
the single-post share path (Bug A below) was fixed regardless.

### Workstream 1 — Subvurs context realignment (prompt truth restored)

The Subvurs notes prompt had drifted from the research record: it
still presented pre-July-2026 core-theory claims as live findings.
Root cause was a **drifted inline duplicate** of the shared catalog
prompt in `curator.py`.

Canonical scorer first (`subvurs/blackbox/shared/subvurs_impact/`,
commit `ea32c96`, 64/64 tests green), then re-vendored to
`quantum_curator/_vendor/subvurs_impact/`:

- **`path_catalog.py` → `v0.2.0-20260714`**: `CORE_THEORY` rewritten
  as a "HISTORICAL CORE THEORY — falsified/retracted, do not cite as
  findings" block (0.504 BUILT_IN per the Jul 2026 out-of-sample test;
  d=0.6 cliff tautological in static dynamics; decorative classifier
  gates per CV_MAX; Apr 25 cross-c band retracted Jun 16; Impax 43x ≠
  sensing advantage — real primitive is the tanh nonlinearity in
  impulsive noise, Kassam 1988; Pattern 51 ZPE unsupported; T=0.857
  retained as parameter/context only). New `CROSS_CORPUS_INTERSECTIONS`
  block rendered by `build_prompt()`: notes now connect items to what
  the intersection *opens up* (experiment, audit, transferable
  technique), not what it "validates". RULES updated: commercial-path
  connection first, corpus-intersection second, core theory only as
  historical context, evidence class stated.
- **`donotuse.py` → `v0.2.0-20260714`**: July 2026 phrases added
  ("chaos valley discovered", "d=0.504 discovered", "43x sensing",
  "zero-point energy extraction", "consensus coupling advantage",
  etc.) with new concept tags (`chaos_valley_discovered`,
  `death_cliff_static`, `impax_43x_sensing`, `p51_zpe`,
  `emergence_classifier_validated`).
- **`scorer.py`**: core_theory 0.4 match tier reframed — "score the
  intersection, not the claim". Weights unchanged (frozen, sum=1.0).
- **`curator.py`**: inline `SUBVURS_NOTES_SYSTEM_PROMPT` (49 lines)
  deleted; the prompt is now `_SUBVURS_NOTES_FORMAT_PREAMBLE +
  path_catalog.build_prompt()` — single source of truth with the
  impact scorer. Fail-closed: if the vendored import fails the prompt
  is None and note generation is skipped (no notes beats stale-theory
  notes). Locked by two new tests in
  `tests/test_curator_subvurs_impact.py`.
- **`email_report.py`**: subject → "Quantum Curator: {n} corpus
  intersections worth a look — {date}"; table header → "Top Corpus
  Intersections (commercial-path relevance)"; footer notes catalog
  v0.2.0 + the July 2026 core-theory re-scope.

### Workstream 2 — Editorial site redesign + honest copy

Full visual overhaul of both the news site and the Qrater dashboard
to an editorial/newspaper direction: paper background `#faf9f6`, ink
`#1a1a1a`, single brick-red accent `#8b2e2e`, serif masthead and
headlines, thin rules. Removed: all gradients, glassmorphism
(`backdrop-filter`), pastel topic pills, the ⚛ emoji logo, dark-slate
panels.

- `site/static/css/style.css` and `site/static/qrater/qrater.css`
  rewritten on the new token set; topic tags are now small-caps
  thin-ruled text labels; Qrater tables restyled dense/agate.
- `base.html`: serif text masthead with rules + dateline; nav as a
  thin rule bar; typographic ruled placeholder replaces the
  gear-emoji image fallback.
- **`about.html` honesty fix**: replaced the false "hand-selected…
  expert commentary" copy. The page now states plainly that articles
  are gathered and scored by an automated pipeline, commentary is
  AI-generated against a documented rubric, and the site is an
  experiment in transparent automated curation.
- `post.html` / `index.html`: explicit small-caps "AI Commentary"
  kicker above every `curator_commentary` block.
- `archive.html`: while the site spans ≤ 2 distinct months the
  archive renders one flowing list ("Since {month} — N articles")
  instead of a near-empty month grid.
- Verified: `quantum-curator build` + `build-qrater` render clean.

### Workstream 3 — Bluesky share fixes (Bugs A & B)

**Bug A — single-post fast path never recorded the share.**
`share_daily_summary`'s single-post path posted and returned True
without calling `record_daily_summary_share()`, so
`is_daily_summary_shared()` never fired and a same-day re-run could
double-post. The fast path now posts with `return_cid=True` and
records `(date_key, root_uri, root_cid, text)` before returning —
mirroring the threaded path. Regression test:
`test_share_daily_summary_single_post_records_share` (row persisted,
`is_thread=0`, second same-day invocation is a no-op).

**Bug B — mid-sentence commentary fragments.** `_build_post_text`'s
fallback word-wrapped the first sentence mid-sentence when no full
sentence fit alongside the hashtags — the same class of artifact the
earlier no-ellipsis fix removed. New policy (module docstring, dated
2026-07-14): **a post body never contains a partial sentence.**
Degradation order when zero full sentences fit: (i) drop hashtags and
re-pack into the freed budget; (ii) else drop commentary entirely
(title + hashtags only). Title word-wrap exception stands (a title is
not a sentence stream). The legacy custom-caller `[:300]` hard slice
is routed through the same `_pack_sentences` helper (word-boundary
wrap survives only as the last resort for text with no sentence
structure at all — unreachable from the production renderer).

**Accepted trade-off (user-visible)**: some posts will now be
hashtag-less and some title+hashtags-only where the old code posted a
dangling fragment. `test_over_budget_first_sentence_word_wraps_not_title_only`
is superseded by `test_over_budget_first_sentence_drops_hashtags_then_commentary`
(docstring documents the policy change per rigor §7 — documented
supersession, not silent weakening).

### Test status

`tests/` suite: **132 passed** (129 baseline − 1 superseded + 2
Bluesky regressions + 2 prompt-lock). Canonical
`subvurs_impact` suite: 64/64. Golden fixtures unchanged beyond
version strings.

### Deployment

K11 picks up the three commits via `git pull --ff-only` on the next
timer run. Rollback: each workstream is a single revertible commit;
the K11 env fix is independent (restore `.env.daily.bak-20260714`).

---

## TL;DR Retry, Summary-Fallback Posts & Photo-Space Collapse (v1.8.1 — July 17, 2026)

Three production issues observed after the v1.8.0 deploy, each
diagnosed from K11 journal + `curator.db` evidence and fixed with a
separately revertible commit.

### 1. TL;DR daily summary intermittently dropped (LLM retry)

**Symptom**: TL;DR Bluesky thread posted 07-13/15/17 but not
07-14/16. **Root cause** (K11 journal): the local router intermittently
returns `RouterError: router returned empty answer (tier=unavailable)`;
`build_daily_summary()` caught it once, returned None, and the CLI
aborted the share ("Summary unavailable — aborting share"). On success
days a *second* invocation ~30–40 min later succeeded — the failure is
transient.

**Fix** (`quantum_curator/intel/daily_summary.py`): the LLM call +
JSON parse + required-keys validation now run inside a retry loop —
`LLM_RETRY_ATTEMPTS = 3` with doubling backoff (`LLM_RETRY_WAIT_SEC =
90`: 90 s, then 180 s). All bad-output modes (raised exception,
unparseable reply, non-dict, missing keys) retry with a fresh
completion. Fail-closed contract preserved: None only after the final
attempt; the "no new entries" branch still makes zero LLM calls.
`_sleep` is module-level so tests stub it. New
`tests/test_daily_summary_retry.py` (6 tests).

### 2. Bluesky posts restating the title with no description (summary fallback)

**Symptom**: most per-article posts were bare "title + hashtags".
**Root cause** (measured on production rows): gpt-oss:120b commentary
opens with 196–286-char first sentences against packing budgets of
~190–240, so the v1.8.0 no-mid-sentence policy's drop-commentary
branch fired on nearly every post. Meanwhile every sampled article
*summary* first sentence (71–204 chars) fit.

**Fix** (`quantum_curator/bluesky.py` `_build_post_text`): body-source
ladder — try `curator_commentary`, then fall back to `post.summary`;
for each source prefer keeping hashtags, drop hashtags only if no full
sentence fits; title+hashtags only when neither source yields a full
sentence. All v1.8.0 invariants preserved (≤300 chars, no ellipsis,
no mid-sentence fragments). 4 new tests in
`tests/test_bluesky_post_text.py`.

### 3. Empty photo spaces on Quantum Crier (collapse, not stock photos)

**Symptom**: posts without images rendered a reserved placeholder box
(faint serif "Q" watermark) on index, topic, and search pages.
**Fix**: collapse the space entirely. `.image-fallback` is now
`display: none` (kept as a safety net); the "Q" watermark rules,
`.topic-bg-*` compatibility block, and explicit fallback `<div>`s in
`topic.html`/`search.html` are removed. Broken-image `onerror`
handlers (and the generic `base.html` listener) now hide the image
container *and* repair layout classes so text reflows full-width:
hero loses `has-image` (grid 3fr/2fr → 1fr), featured cards gain
`no-image`, and a new `.featured-card--wide.no-image
{ grid-template-columns: 1fr; }` rule covers topic-page featured
cards. `post.html` and Qrater already collapsed correctly — untouched.

### Verification

`tests/` suite: **142 passed** (132 baseline + 6 retry + 4
summary-fallback). Local `build` renders clean; zero `image-fallback`
markup in generated pages; Jinja parse check green on all four edited
templates.

### Deployment

Three commits (one per fix); K11 picks them up via `git pull
--ff-only` on the next timer run. Rollback: revert the individual
commit.

---

*Document updated: July 17, 2026*
*Quantum Curator v1.8.1 — TL;DR LLM retry with backoff; Bluesky summary-fallback body ladder; empty photo spaces collapsed site-wide*
