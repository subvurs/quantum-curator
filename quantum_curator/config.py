"""Configuration for Quantum Curator."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Curator identity
    curator_name: str = Field(default="Mark Eatherly", description="Name shown as curator")
    curator_title: str = Field(default="Quantum Computing Researcher", description="Curator's title")
    curator_bio: str = Field(
        default="Passionate about quantum information science and its applications. "
        "Curating the latest developments in quantum computing, quantum physics, and quantum information theory.",
        description="Short bio for about page",
    )
    curator_twitter: str = Field(default="", description="Twitter/X handle for curator")
    curator_linkedin: str = Field(default="", description="LinkedIn URL for curator")
    curator_website: str = Field(default="", description="Personal website URL")

    # Site settings
    site_name: str = Field(default="Quantum Crier", description="Site name/title")
    site_tagline: str = Field(
        default="Daily curated insights from the quantum frontier",
        description="Site tagline/subtitle",
    )
    site_url: str = Field(default="https://quantumcrier.com", description="Published site URL")
    site_description: str = Field(
        default="A daily curated collection of the latest news, research, and developments "
        "in quantum computing, quantum physics, and quantum information science.",
        description="Site meta description",
    )

    @property
    def social_links(self) -> dict[str, str]:
        """Build social links from individual settings."""
        links = {}
        if self.curator_twitter:
            links["Twitter"] = f"https://twitter.com/{self.curator_twitter}"
        if self.curator_linkedin:
            links["LinkedIn"] = self.curator_linkedin
        if self.curator_website:
            links["Website"] = self.curator_website
        return links

    # Paths
    data_dir: Path = Field(default=Path("data"), description="Directory for database and cache")
    output_dir: Path = Field(default=Path("site_output"), description="Generated site output directory")

    # API keys
    anthropic_api_key: str = Field(default="", description="Anthropic API key for commentary generation")
    news_api_key: str = Field(default="", description="NewsAPI key for news aggregation")
    unsplash_api_key: str = Field(default="", description="Unsplash API key for stock photo search")

    # Content freshness
    max_article_age_days: int = Field(default=60, description="Maximum article age in days — older articles are dropped during fetch and excluded from the site")

    # Image generation
    generate_images: bool = Field(default=True, description="Auto-generate images for articles without one")

    # GitHub deployment
    github_token: str = Field(default="", description="GitHub PAT for deployment")
    github_repo: str = Field(default="quantum-pulse", description="GitHub repo name for Pages")
    github_username: str = Field(default="", description="GitHub username")
    github_branch: str = Field(default="gh-pages", description="Branch for GitHub Pages")
    custom_domain: str = Field(default="quantumcrier.com", description="Custom domain for GitHub Pages")

    # Qrater settings
    qrater_output_dir: Path = Field(default=Path("qrater_output"), description="Qrater site output directory")
    qrater_github_repo: str = Field(default="qrater", description="GitHub repo name for Qrater Pages")
    qrater_site_url: str = Field(default="https://qrater.org", description="Qrater published site URL")
    buttondown_username: str = Field(default="", description="Buttondown newsletter username for Qrater email signup")

    # Aggregation settings
    max_posts_per_day: int = Field(default=15, description="Maximum posts to curate per day")
    max_articles_per_day: int = Field(default=30, description="Maximum articles to fetch per day")
    min_relevance_score: float = Field(default=0.3, description="Minimum relevance score to include")
    fetch_timeout: int = Field(default=30, description="HTTP timeout in seconds")

    # Commentary settings
    generate_commentary: bool = Field(default=True, description="Generate AI commentary for posts")
    commentary_style: str = Field(
        default="insightful",
        description="Commentary style: insightful, technical, accessible, brief",
    )
    claude_model: str = Field(default="claude-sonnet-4-20250514", description="Claude model for commentary")
    generate_subvurs_notes: bool = Field(default=True, description="Generate internal Subvurs research connection notes during curation")

    @property
    def database_path(self) -> Path:
        """Path to SQLite database."""
        return self.data_dir / "curator.db"

    @property
    def has_anthropic(self) -> bool:
        """Check if Anthropic API is configured."""
        return bool(self.anthropic_api_key)

    @property
    def has_news_api(self) -> bool:
        """Check if NewsAPI is configured."""
        return bool(self.news_api_key)

    @property
    def has_github(self) -> bool:
        """Check if GitHub deployment is configured."""
        return bool(self.github_token and self.github_username)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Quantum-related keywords for relevance filtering
QUANTUM_KEYWORDS = [
    # Core terms
    "quantum computing",
    "quantum computer",
    "quantum information",
    "quantum physics",
    "quantum mechanics",
    "quantum technology",
    "quantum algorithm",
    "quantum supremacy",
    "quantum advantage",
    # Specific concepts
    "qubit",
    "qubits",
    "superposition",
    "entanglement",
    "quantum entanglement",
    "decoherence",
    "quantum error correction",
    "quantum cryptography",
    "quantum key distribution",
    "qkd",
    "quantum sensing",
    "quantum simulation",
    "quantum machine learning",
    "quantum neural network",
    "variational quantum",
    "vqe",
    "qaoa",
    # Hardware
    "superconducting qubit",
    "trapped ion",
    "photonic quantum",
    "topological qubit",
    "quantum processor",
    "quantum chip",
    # Companies/Labs
    "ibm quantum",
    "google quantum",
    "ionq",
    "rigetti",
    "d-wave",
    "honeywell quantum",
    "quantinuum",
    "amazon braket",
    "azure quantum",
    "xanadu",
    "pasqal",
    "atom computing",
    # Research
    "arxiv quant-ph",
    "quantum research",
    "quantum paper",
    "quantum breakthrough",
]

# Topics for categorization
QUANTUM_TOPICS = {
    "hardware": ["processor", "chip", "qubit", "superconducting", "trapped ion", "photonic", "topological"],
    "algorithms": ["algorithm", "qaoa", "vqe", "grover", "shor", "variational", "optimization"],
    "error_correction": ["error correction", "fault tolerant", "surface code", "logical qubit"],
    "cryptography": ["cryptography", "qkd", "key distribution", "post-quantum", "encryption"],
    "machine_learning": ["machine learning", "neural network", "quantum ml", "qml"],
    "simulation": ["simulation", "chemistry", "materials", "drug discovery", "molecular"],
    "sensing": ["sensing", "metrology", "measurement", "precision"],
    "industry": ["startup", "funding", "investment", "commercial", "enterprise", "partnership"],
    "research": ["research", "paper", "arxiv", "publication", "discovery", "breakthrough"],
    "policy": ["policy", "regulation", "government", "national", "initiative", "strategy"],
}
