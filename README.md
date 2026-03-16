# Quantum Curator

Daily quantum computing news aggregation and curation with AI-powered commentary.

## Features

- **Multi-Source Aggregation**: Pulls from 17+ quantum computing news sources including arXiv, IBM Quantum, Google AI, Microsoft Quantum, AWS, and more
- **Intelligent Relevance Scoring**: Filters and ranks articles based on quantum computing relevance
- **AI-Powered Commentary**: Uses Claude to generate expert commentary on each article
- **Daily Digests**: Automatically creates daily summary digests
- **Static Site Generation**: Builds a modern, responsive static site
- **GitHub Pages Deployment**: One-command deployment to GitHub Pages
- **Automated Pipeline**: GitHub Actions workflow for daily updates

## Installation

```bash
pip install -e .
```

## Configuration

Create a `.env` file or set environment variables:

```bash
# Required for AI commentary
ANTHROPIC_API_KEY=your_key_here

# Optional - enables NewsAPI source
NEWS_API_KEY=your_key_here

# Site configuration
CURATOR_NAME="Mark Eatherly"
SITE_NAME="Quantum Computing Daily"
SITE_URL="https://quantum.example.com"
GITHUB_REPO="https://github.com/username/quantum-news"
```

## Usage

### Initialize

```bash
quantum-curator init
```

### Fetch Articles

```bash
quantum-curator fetch
quantum-curator fetch --force  # Force fetch even if not due
```

### Curate Content

```bash
quantum-curator curate
quantum-curator curate --limit 30  # Curate more articles
```

### Build Site

```bash
quantum-curator build
quantum-curator build --output ./public
```

### Deploy

```bash
quantum-curator deploy
quantum-curator deploy --verify  # Verify after deployment
```

### Full Pipeline

```bash
quantum-curator run  # fetch -> curate -> build
quantum-curator run --deploy  # With deployment
```

### Status & Info

```bash
quantum-curator status
quantum-curator sources
quantum-curator posts
quantum-curator config
```

## Project Structure

```
quantum_curator/
├── aggregator.py      # Multi-source fetching and scoring
├── curator.py         # AI commentary generation
├── publisher.py       # GitHub Pages deployment
├── cli.py             # Command-line interface
├── config.py          # Configuration management
├── models.py          # Data models
├── db.py              # SQLite database layer
├── sources/
│   ├── registry.py    # Built-in source definitions
│   ├── rss.py         # RSS feed fetcher
│   ├── arxiv.py       # arXiv API fetcher
│   └── news.py        # NewsAPI fetcher
└── site/
    ├── builder.py     # Static site generator
    ├── templates/     # Jinja2 HTML templates
    └── static/css/    # Stylesheets
```

## Built-in Sources

### Academic
- arXiv Quantum Physics (quant-ph)
- arXiv Quantum Information (cs.QI)

### Industry Blogs
- IBM Quantum Blog
- Google AI Blog
- Microsoft Quantum Blog
- AWS Quantum Computing Blog
- IonQ Blog

### News & Publications
- Quantum Computing Report
- The Quantum Insider
- Quanta Magazine
- Phys.org Quantum
- Nature Physics
- Science Daily - Quantum
- Ars Technica - Science
- MIT Technology Review
- Wired Science

## Automated Daily Updates

The included GitHub Actions workflow runs twice daily:
- 6:00 AM UTC
- 6:00 PM UTC

To enable:
1. Push to a GitHub repository
2. Add secrets: `ANTHROPIC_API_KEY`, `NEWS_API_KEY`
3. Enable GitHub Pages from the `gh-pages` branch

## License

MIT License
