"""Command-line interface for Quantum Curator."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from .config import get_settings
from . import db
from .models import PostStatus

console = Console()


@click.group()
@click.version_option()
def cli():
    """Quantum Curator - Daily quantum computing news aggregation."""
    pass


# --- Initialization ---

@cli.command()
def init():
    """Initialize the database and register sources."""
    console.print("[bold blue]Initializing Quantum Curator...[/]")

    # Initialize database
    db.init_db()
    console.print("[green]Database initialized[/]")

    # Register built-in sources
    from .sources import register_builtin_sources
    sources = register_builtin_sources()
    console.print(f"[green]Registered {len(sources)} built-in sources[/]")

    console.print("\n[bold green]Initialization complete![/]")
    console.print("Run [bold]quantum-curator fetch[/] to start aggregating content.")


# --- Fetching ---

@cli.command()
@click.option("--force", "-f", is_flag=True, help="Force fetch even if not due")
@click.option("--source", "-s", help="Fetch from specific source (by name)")
def fetch(force: bool, source: str | None):
    """Fetch articles from all configured sources."""
    from .aggregator import Aggregator

    async def run_fetch():
        aggregator = Aggregator()

        sources = None
        if source:
            all_sources = db.list_sources()
            sources = [s for s in all_sources if source.lower() in s.name.lower()]
            if not sources:
                console.print(f"[red]No source found matching '{source}'[/]")
                return

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Fetching articles...", total=None)
            articles, counts = await aggregator.fetch_all_sources(sources=sources, force=force)
            progress.update(task, completed=True)

        console.print(
            f"\n[green]Fetched {len(articles)} articles:[/] "
            f"{counts['inserted']} inserted, "
            f"{counts['updated']} updated, "
            f"{counts['fk_blocked']} fk_blocked, "
            f"{counts['other_error']} other_errors"
        )

        # Per-source fetch outcomes (instrumentation added 2026-05-25 to
        # surface the silent fetcher-failure mode that hid 12 of 19
        # zero-yield sources for a week). sources_ok / sources_empty /
        # sources_error / sources_skipped_interval sum to the number of
        # sources actually attempted this run.
        console.print(
            f"[cyan]Sources:[/] "
            f"{counts['sources_ok']} ok, "
            f"{counts['sources_empty']} empty, "
            f"{counts['sources_error']} errored, "
            f"{counts['sources_skipped_interval']} skipped (interval)"
        )

        # Make silent save failures loud — but NOT fatal. Non-zero exit
        # here would cancel the downstream curate/build/deploy/email-insights
        # steps in GH Actions, which is the exact "surprise breakage" rule
        # this fetch instrumentation was meant to PREVENT, not cause. The
        # WARNING line is still grep-able in the run log for monitoring.
        if counts["fk_blocked"] > 0 or counts["other_error"] > 0:
            console.print(
                f"[bold red]WARNING:[/] {counts['fk_blocked']} fk_blocked + "
                f"{counts['other_error']} other_errors during save. "
                "These articles were NOT persisted to the database. "
                "Continuing pipeline with the articles that did persist."
            )

        # Surface per-source failures and persistent empties. Both are
        # warnings (not fatal) for the same GH-Actions-pipeline reason
        # as the save-failure WARNING above — a flaky feed should not
        # block curate/build/deploy/email-insights.
        if counts["source_failures"]:
            failures_table = Table(title="Source Fetch Errors")
            failures_table.add_column("Source", style="yellow")
            failures_table.add_column("Error Type", style="red")
            failures_table.add_column("Message", style="dim")
            for f in counts["source_failures"]:
                failures_table.add_row(
                    f["source"],
                    f["error_type"],
                    f["error"][:100] + ("..." if len(f["error"]) > 100 else ""),
                )
            console.print(failures_table)
            console.print(
                f"[bold red]WARNING:[/] {len(counts['source_failures'])} source(s) "
                "failed to fetch this run. Continuing with the rest."
            )

        if counts["empty_sources"]:
            console.print(
                f"[yellow]Empty sources this run:[/] "
                f"{', '.join(counts['empty_sources'])}"
            )

        if articles:
            table = Table(title="Recent Articles")
            table.add_column("Title", style="cyan", max_width=50)
            table.add_column("Source", style="yellow")
            table.add_column("Score", justify="right")

            for article in articles[:10]:
                table.add_row(
                    article.title[:50] + "..." if len(article.title) > 50 else article.title,
                    article.source_name,
                    f"{article.relevance_score:.2f}",
                )

            console.print(table)

    asyncio.run(run_fetch())


# --- Curation ---

@cli.command()
@click.option("--limit", "-l", default=500, help="Maximum articles to curate")
@click.option("--auto-publish", "-p", is_flag=True, default=True, help="Auto-publish high-quality posts")
@click.option("--create-digest", "-d", is_flag=True, default=True, help="Create daily digest")
def curate(limit: int, auto_publish: bool, create_digest: bool):
    """Curate articles with AI commentary."""
    from .curator import Curator
    from .aggregator import Aggregator

    settings = get_settings()
    if not settings.anthropic_api_key:
        console.print("[yellow]Warning: No Anthropic API key configured. Using fallback commentary.[/]")

    async def run_curate():
        # Get top articles
        aggregator = Aggregator()
        articles = await aggregator.get_top_articles(limit=limit)

        if not articles:
            console.print("[yellow]No articles to curate[/]")
            return

        console.print(f"[blue]Curating {len(articles)} articles...[/]")

        curator = Curator()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Generating commentary...", total=None)
            posts = await curator.curate_batch(articles)
            progress.update(task, completed=True)

        console.print(f"[green]Created {len(posts)} curated posts[/]")

        # Auto-publish
        if auto_publish:
            published = await curator.auto_publish(posts)
            console.print(f"[green]Published {len(published)} posts[/]")

        # Create digest
        if create_digest:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Creating daily digest...", total=None)
                digest = await curator.create_daily_digest(posts=posts)
                progress.update(task, completed=True)

            console.print(f"[green]Created digest: {digest.title}[/]")

    asyncio.run(run_curate())


# --- Site Building ---

@cli.command()
@click.option("--output", "-o", type=click.Path(), help="Output directory")
@click.option("--no-clean", is_flag=True, help="Don't clean output directory first")
def build(output: str | None, no_clean: bool):
    """Build the static site."""
    from .site import build_site

    output_path = Path(output) if output else None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Building site...", total=None)
        site_path = build_site(output_dir=output_path, clean=not no_clean)
        progress.update(task, completed=True)

    console.print(f"\n[green]Site built at:[/] {site_path}")
    console.print(f"\nPreview with: [bold]python -m http.server -d {site_path}[/]")


# --- Deployment ---

@cli.command()
@click.option("--site-dir", "-s", type=click.Path(exists=True), help="Site directory to deploy")
@click.option("--repo", "-r", help="GitHub repository URL")
@click.option("--branch", "-b", default="gh-pages", help="Branch to deploy to")
@click.option("--verify", "-v", is_flag=True, help="Verify deployment after push")
def deploy(site_dir: str | None, repo: str | None, branch: str, verify: bool):
    """Deploy site to GitHub Pages."""
    from .publisher import GitHubPagesPublisher

    settings = get_settings()
    site_path = Path(site_dir) if site_dir else Path(settings.output_dir)

    if not site_path.exists():
        console.print(f"[red]Site directory not found: {site_path}[/]")
        console.print("Run [bold]quantum-curator build[/] first.")
        return

    publisher = GitHubPagesPublisher()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Deploying to GitHub Pages...", total=None)
        success = publisher.deploy(site_path, repo_url=repo, branch=branch)
        progress.update(task, completed=True)

    if success:
        console.print("[green]Deployment successful![/]")
        if verify:
            publisher.verify_deployment()
    else:
        console.print("[red]Deployment failed[/]")


# --- Full Pipeline ---

@cli.command()
@click.option("--force-fetch", "-f", is_flag=True, help="Force fetch even if not due")
@click.option("--deploy", "-d", "do_deploy", is_flag=True, help="Deploy after building")
def run(force_fetch: bool, do_deploy: bool):
    """Run full pipeline: fetch -> curate -> build -> (deploy)."""
    from .aggregator import Aggregator
    from .curator import Curator
    from .site import build_site
    from .site.qrater_builder import build_qrater as _build_qrater
    from .publisher import GitHubPagesPublisher

    settings = get_settings()

    async def run_pipeline():
        # Step 1: Fetch
        console.print(Panel("[bold blue]Step 1: Fetching articles[/]"))
        aggregator = Aggregator()
        articles, counts = await aggregator.fetch_all_sources(force=force_fetch)
        console.print(
            f"[green]Fetched {len(articles)} new articles[/] "
            f"({counts['inserted']} inserted, {counts['updated']} updated, "
            f"{counts['fk_blocked']} fk_blocked, {counts['other_error']} other_errors)\n"
        )
        if counts["fk_blocked"] > 0 or counts["other_error"] > 0:
            console.print(
                f"[bold red]WARNING:[/] {counts['fk_blocked']} fk_blocked + "
                f"{counts['other_error']} other_errors during save. "
                "These articles were NOT persisted to the database. "
                "Continuing pipeline with the articles that did persist."
            )

        # Step 2: Curate
        console.print(Panel("[bold blue]Step 2: Curating content[/]"))
        top_articles = await aggregator.get_top_articles(limit=20)

        if top_articles:
            curator = Curator()
            posts = await curator.curate_batch(top_articles)
            await curator.auto_publish(posts)
            await curator.create_daily_digest(posts=posts)
            console.print(f"[green]Curated {len(posts)} articles[/]\n")
        else:
            console.print("[yellow]No new articles to curate[/]\n")

        # Step 3: Build both sites
        console.print(Panel("[bold blue]Step 3: Building sites[/]"))
        site_path = build_site()
        console.print(f"[green]Quantum Crier built at {site_path}[/]")
        qrater_path = _build_qrater()
        console.print(f"[green]Qrater built at {qrater_path}[/]\n")

        # Step 4: Deploy (optional)
        if do_deploy:
            console.print(Panel("[bold blue]Step 4: Deploying[/]"))
            publisher = GitHubPagesPublisher()
            if publisher.deploy(site_path):
                console.print("[green]Quantum Crier deployed![/]")
            else:
                console.print("[red]Quantum Crier deployment failed[/]")

            if publisher.deploy(
                qrater_path,
                repo_url=f"https://github.com/{settings.github_username}/{settings.qrater_github_repo}",
                branch="gh-pages",
            ):
                console.print("[green]Qrater deployed![/]")
            else:
                console.print("[red]Qrater deployment failed[/]")

        # Step 5: Social sharing (optional)
        if settings.has_bluesky or settings.has_twitter:
            console.print(Panel("[bold blue]Step 5: Social sharing[/]"))

            if settings.has_bluesky:
                from .bluesky import BlueskySharer, init_bluesky_table
                init_bluesky_table()
                sharer = BlueskySharer()
                shared = sharer.share_pending(limit=5)
                if shared:
                    console.print(f"[green]Shared {len(shared)} posts to Bluesky[/]")
                else:
                    console.print("[dim]No new posts to share to Bluesky[/]")

            if settings.has_twitter:
                from .twitter import TwitterSharer, init_twitter_table
                init_twitter_table()
                tweeter = TwitterSharer()
                tweeted = tweeter.share_pending(limit=5)
                if tweeted:
                    console.print(f"[green]Tweeted {len(tweeted)} posts to Twitter/X[/]")
                else:
                    console.print("[dim]No new posts to tweet[/]")

        # Step 6: Email insights report (optional)
        if settings.has_email:
            console.print(Panel("[bold blue]Step 6: Emailing insights report[/]"))
            from .email_report import send_insights_email
            if send_insights_email(days=1):
                console.print("[green]Insights email sent[/]")
            else:
                console.print("[dim]Failed to send insights email[/]")

    asyncio.run(run_pipeline())
    console.print("\n[bold green]Pipeline complete![/]")


# --- Bluesky Sharing ---

@cli.command()
@click.option("--limit", "-l", default=5, help="Maximum posts to share")
@click.option("--dry-run", is_flag=True, help="Show what would be shared without posting")
def share(limit: int, dry_run: bool):
    """Share published posts to Bluesky."""
    from .bluesky import BlueskySharer, init_bluesky_table, get_posts_not_shared_to_bluesky

    init_bluesky_table()

    if dry_run:
        posts = get_posts_not_shared_to_bluesky(limit=limit)
        if not posts:
            console.print("[dim]No pending posts to share[/]")
            return

        console.print(Panel(f"[bold]Dry Run: {len(posts)} posts would be shared to Bluesky[/]"))

        sharer = BlueskySharer()
        table = Table(title="Pending Bluesky Shares")
        table.add_column("Title", style="cyan", max_width=50)
        table.add_column("Post Text", style="white", max_width=60)

        for post in posts:
            text = sharer._build_post_text(post)
            table.add_row(
                post.title[:50] + "..." if len(post.title) > 50 else post.title,
                text,
            )

        console.print(table)
        return

    sharer = BlueskySharer()
    if not sharer.is_configured:
        console.print("[red]Bluesky not configured.[/]")
        console.print("Set BLUESKY_HANDLE and BLUESKY_APP_PASSWORD in .env")
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Sharing to Bluesky...", total=None)
        shared = sharer.share_pending(limit=limit)
        progress.update(task, completed=True)

    if shared:
        console.print(f"[green]Shared {len(shared)} posts to Bluesky[/]")
    else:
        console.print("[dim]No new posts to share[/]")


# --- Email Report ---

@cli.command("email-insights")
@click.option("--days", "-d", default=1, help="Look back this many days for articles")
@click.option("--dry-run", is_flag=True, help="Show report without sending email")
def email_insights(days: int, dry_run: bool):
    """Email daily Subvurs research connection report."""
    from .email_report import build_insights_report, send_insights_email

    if dry_run:
        subject, html, count = build_insights_report(days=days)
        console.print(Panel(f"[bold]{subject}[/]"))
        console.print(f"[dim]{count} connections found — email would be sent to configured address[/]")
        return

    settings = get_settings()
    if not settings.has_email:
        console.print("[red]Email not configured.[/]")
        console.print("Set SMTP_EMAIL and SMTP_APP_PASSWORD in .env")
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Sending insights email...", total=None)
        success = send_insights_email(days=days)
        progress.update(task, completed=True)

    if success:
        console.print(f"[green]Insights email sent to {settings.smtp_email}[/]")
    else:
        console.print("[red]Failed to send insights email[/]")


# --- Twitter/X Sharing ---

@cli.command()
@click.option("--limit", "-l", default=5, help="Maximum posts to tweet")
@click.option("--dry-run", is_flag=True, help="Show what would be tweeted without posting")
def tweet(limit: int, dry_run: bool):
    """Share published posts to Twitter/X."""
    from .twitter import TwitterSharer, init_twitter_table, get_posts_not_shared_to_twitter

    init_twitter_table()

    if dry_run:
        posts = get_posts_not_shared_to_twitter(limit=limit)
        if not posts:
            console.print("[dim]No pending posts to tweet[/]")
            return

        console.print(Panel(f"[bold]Dry Run: {len(posts)} posts would be tweeted[/]"))

        sharer = TwitterSharer()
        table = Table(title="Pending Tweets")
        table.add_column("Title", style="cyan", max_width=50)
        table.add_column("Tweet Text", style="white", max_width=60)

        for post in posts:
            text = sharer._build_tweet_text(post)
            table.add_row(
                post.title[:50] + "..." if len(post.title) > 50 else post.title,
                text,
            )

        console.print(table)
        return

    sharer = TwitterSharer()
    if not sharer.is_configured:
        console.print("[red]Twitter/X not configured.[/]")
        console.print("Set TWITTER_CONSUMER_KEY, TWITTER_CONSUMER_SECRET, TWITTER_ACCESS_TOKEN, and TWITTER_ACCESS_TOKEN_SECRET in .env")
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Tweeting...", total=None)
        shared = sharer.share_pending(limit=limit)
        progress.update(task, completed=True)

    if shared:
        console.print(f"[green]Tweeted {len(shared)} posts to Twitter/X[/]")
    else:
        console.print("[dim]No new posts to tweet[/]")


# --- Qrater ---

@cli.command("build-qrater")
@click.option("--output", "-o", type=click.Path(), help="Output directory")
@click.option("--no-clean", is_flag=True, help="Don't clean output directory first")
def build_qrater(output: str | None, no_clean: bool):
    """Build the Qrater interactive dashboard site."""
    from .site.qrater_builder import build_qrater as _build_qrater

    output_path = Path(output) if output else None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Building Qrater dashboard...", total=None)
        site_path = _build_qrater(output_dir=output_path, clean=not no_clean)
        progress.update(task, completed=True)

    console.print(f"\n[green]Qrater built at:[/] {site_path}")
    console.print(f"\nPreview with: [bold]python -m http.server -d {site_path}[/]")


@cli.command("deploy-qrater")
@click.option("--site-dir", "-s", type=click.Path(exists=True), help="Qrater site directory to deploy")
@click.option("--verify", "-v", is_flag=True, help="Verify deployment after push")
def deploy_qrater(site_dir: str | None, verify: bool):
    """Deploy Qrater dashboard to GitHub Pages."""
    from .publisher import GitHubPagesPublisher

    settings = get_settings()
    site_path = Path(site_dir) if site_dir else Path(settings.qrater_output_dir)

    if not site_path.exists():
        console.print(f"[red]Qrater directory not found: {site_path}[/]")
        console.print("Run [bold]quantum-curator build-qrater[/] first.")
        return

    publisher = GitHubPagesPublisher()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Deploying Qrater to GitHub Pages...", total=None)
        success = publisher.deploy(
            site_path,
            repo_url=f"https://github.com/{settings.github_username}/{settings.qrater_github_repo}",
            branch="gh-pages",
        )
        progress.update(task, completed=True)

    if success:
        console.print(f"[green]Qrater deployed to {settings.qrater_site_url}[/]")
        if verify:
            publisher.verify_deployment()
    else:
        console.print("[red]Qrater deployment failed[/]")


# --- Status & Info ---

@cli.command()
def status():
    """Show curator status and statistics."""
    # Sources
    sources = db.list_sources()
    enabled_sources = [s for s in sources if s.enabled]

    # Articles
    articles = db.list_raw_articles(limit=1000)
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_articles = [a for a in articles if a.fetched_at and a.fetched_at >= today]

    # Posts
    posts = db.list_curated_posts(limit=1000)
    published = [p for p in posts if p.status == PostStatus.PUBLISHED]
    drafts = [p for p in posts if p.status == PostStatus.DRAFT]

    # Digests
    digests = db.list_daily_digests(limit=7)

    console.print(Panel("[bold]Quantum Curator Status[/]"))

    table = Table(show_header=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Sources (enabled)", f"{len(enabled_sources)} / {len(sources)}")
    table.add_row("Total articles", str(len(articles)))
    table.add_row("Articles today", str(len(today_articles)))
    table.add_row("Published posts", str(len(published)))
    table.add_row("Draft posts", str(len(drafts)))
    table.add_row("Recent digests", str(len(digests)))

    console.print(table)

    if digests:
        console.print(f"\nLatest digest: [green]{digests[0].title}[/]")


@cli.command()
def sources():
    """List all configured sources."""
    all_sources = db.list_sources()

    table = Table(title="Configured Sources")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="yellow")
    table.add_column("Enabled", justify="center")
    table.add_column("Last Fetch")
    table.add_column("Interval")

    for source in all_sources:
        last_fetch = source.last_fetched_at.strftime("%Y-%m-%d %H:%M") if source.last_fetched_at else "Never"
        table.add_row(
            source.name,
            source.source_type.value,
            "[green]Yes[/]" if source.enabled else "[red]No[/]",
            last_fetch,
            f"{source.fetch_interval_hours}h",
        )

    console.print(table)


@cli.command()
@click.option("--limit", "-l", default=20, help="Number of posts to show")
@click.option("--status", "-s", type=click.Choice(["draft", "published", "all"]), default="all")
def posts(limit: int, status: str):
    """List curated posts."""
    post_status = None
    if status == "draft":
        post_status = PostStatus.DRAFT
    elif status == "published":
        post_status = PostStatus.PUBLISHED

    all_posts = db.list_curated_posts(status=post_status, limit=limit)

    table = Table(title=f"Curated Posts ({status})")
    table.add_column("Title", style="cyan", max_width=50)
    table.add_column("Source", style="yellow")
    table.add_column("Status")
    table.add_column("Score", justify="right")
    table.add_column("Date")

    for post in all_posts:
        status_str = "[green]Published[/]" if post.status == PostStatus.PUBLISHED else "[yellow]Draft[/]"
        date_str = post.published_at.strftime("%Y-%m-%d") if post.published_at else "N/A"
        table.add_row(
            post.title[:50] + "..." if len(post.title) > 50 else post.title,
            post.source_name,
            status_str,
            f"{post.relevance_score:.2f}",
            date_str,
        )

    console.print(table)


# --- Configuration ---

@cli.command()
def config():
    """Show current configuration."""
    settings = get_settings()

    console.print(Panel("[bold]Quantum Curator Configuration[/]"))

    table = Table(show_header=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Curator Name", settings.curator_name)
    table.add_row("Site Name", settings.site_name)
    table.add_row("Site URL", settings.site_url)
    table.add_row("Output Directory", str(settings.output_dir))
    table.add_row("GitHub Repo", settings.github_repo or "[dim]Not set[/]")
    table.add_row("Custom Domain", settings.custom_domain or "[dim]Not set[/]")
    table.add_row("Anthropic API", "[green]Configured[/]" if settings.anthropic_api_key else "[red]Not set[/]")
    table.add_row("NewsAPI", "[green]Configured[/]" if settings.news_api_key else "[dim]Not set[/]")
    table.add_row("Min Relevance Score", str(settings.min_relevance_score))
    table.add_row("Max Articles/Day", str(settings.max_articles_per_day))
    table.add_row("", "")
    table.add_row("[bold]Qrater[/]", "")
    table.add_row("Qrater URL", settings.qrater_site_url)
    table.add_row("Qrater Output", str(settings.qrater_output_dir))
    table.add_row("Qrater Repo", settings.qrater_github_repo)
    table.add_row("Buttondown", settings.buttondown_username or "[dim]Not set[/]")

    console.print(table)


@cli.command()
@click.option("--limit", "-l", default=50, help="Maximum posts to scan")
@click.option("--all", "show_all", is_flag=True, help="Show all posts, including those with no connections")
def insights(limit: int, show_all: bool):
    """Show Subvurs research connection notes for curated articles."""
    all_posts = db.list_curated_posts(limit=limit)

    if not all_posts:
        console.print("[yellow]No curated posts found. Run 'quantum-curator curate' first.[/]")
        return

    with_notes = [p for p in all_posts if p.subvurs_notes]
    display_posts = all_posts if show_all else with_notes

    console.print(Panel(f"[bold]Subvurs Research Connections[/]\n{len(with_notes)} of {len(all_posts)} curated articles have connections"))

    if not display_posts:
        console.print("[dim]No articles with Subvurs connections found.[/]")
        return

    table = Table(show_lines=True)
    table.add_column("Title", style="cyan", max_width=40)
    table.add_column("Date", style="dim", max_width=12)
    table.add_column("Subvurs Notes", style="green", max_width=80)

    for post in display_posts:
        date_str = post.published_at.strftime("%Y-%m-%d") if post.published_at else "N/A"
        title = post.title[:40] + "..." if len(post.title) > 40 else post.title
        notes = post.subvurs_notes if post.subvurs_notes else "[dim]None[/]"
        table.add_row(title, date_str, notes)

    console.print(table)


# --- Intel Migration (Phase 2) ---

@cli.command("synthesize-intel")
@click.option("--days", "-d", default=1, show_default=True,
              help="Use entries cataloged in the last N days as 'today'.")
@click.option("--max-briefs", default=5, show_default=True,
              help="Cap on briefs delivered in this run.")
@click.option("--model", default=None,
              help="Override the Anthropic model (defaults to synthesizer default).")
@click.option("--dry-run", is_flag=True,
              help="Run synth but do NOT write briefs to disk or stamp first_brief_at.")
def synthesize_intel(days: int, max_briefs: int, model: str | None, dry_run: bool):
    """Run the migrated Intel combinatorial-product synthesizer over Curator's intel entries."""
    from .intel import synthesizer

    settings = get_settings()
    if not settings.has_anthropic:
        console.print("[red]ANTHROPIC_API_KEY not configured — synth requires it.[/]")
        return

    from .intel import inventory_view
    new_entries = inventory_view.today_entries(days=days)
    inventory = inventory_view.load_inventory()

    if not new_entries:
        console.print(f"[yellow]No entries in the last {days}d — nothing to synthesize.[/]")
        return

    console.print(
        f"[blue]Synthesizing over {len(new_entries)} new entries "
        f"(inventory total: {len(inventory)})...[/]"
    )

    kwargs = {"max_briefs": max_briefs}
    if model:
        kwargs["model"] = model

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating concept briefs...", total=None)
        concepts = synthesizer.synthesize(new_entries, inventory=inventory, **kwargs)
        progress.update(task, completed=True)

    if not concepts:
        console.print("[yellow]Synthesis returned 0 concepts (LLM failure or no JSON).[/]")
        return

    console.print(f"[green]Synthesizer produced {len(concepts)} concepts[/]")

    if dry_run:
        console.print("[dim]--dry-run: briefs NOT delivered to disk.[/]")
        for c in concepts:
            title = c.get("product_name") or c.get("concept_title") or "untitled"
            conf = c.get("confidence", "?")
            console.print(f"  • {title}  (confidence: {conf})")
        return

    briefs = synthesizer.deliver(concepts)
    console.print(f"[green]Delivered {len(briefs)} briefs to disk[/]")
    for bp in briefs:
        console.print(f"  • {bp}")


@cli.command("intel-summary")
@click.option("--days", "-d", default=1, show_default=True,
              help="'Today' window for the summary.")
@click.option("--prior-days", default=7, show_default=True,
              help="Prior-window comparison length.")
@click.option("--format", "fmt",
              type=click.Choice(["text", "bluesky", "json"]), default="text",
              show_default=True,
              help="Render format.")
def intel_summary(days: int, prior_days: int, fmt: str):
    """Build today's structured Intel summary (TL;DR + implications + attention)."""
    from .intel import daily_summary, inventory_view

    settings = get_settings()
    if not settings.has_anthropic:
        console.print("[red]ANTHROPIC_API_KEY not configured.[/]")
        return

    new_entries = inventory_view.today_entries(days=days)
    payload = daily_summary.build_daily_summary(
        new_entries=new_entries,
        prior_days=prior_days,
    )

    if payload is None:
        console.print("[red]Daily summary unavailable (LLM failure or bad JSON).[/]")
        return

    if fmt == "json":
        import json as _json
        console.print(_json.dumps(payload, indent=2))
    elif fmt == "bluesky":
        console.print(daily_summary.render_bluesky(payload))
    else:
        console.print(daily_summary.render_text(payload))


@cli.command("intel-email")
@click.option("--days", "-d", default=1, show_default=True,
              help="'Today' window for entries + summary.")
@click.option("--no-synth", is_flag=True,
              help="Skip the synthesis step; email entries + summary only.")
@click.option("--max-briefs", default=5, show_default=True,
              help="Cap on briefs included when synth runs.")
@click.option("--dry-run", is_flag=True,
              help="Build everything, render HTML, but do NOT send the email.")
def intel_email(days: int, no_synth: bool, max_briefs: int, dry_run: bool):
    """Send the daily Intel email (separate SMTP body, decision D6)."""
    import time as _time
    from .intel import inventory_view, daily_summary, synthesizer, emailer

    settings = get_settings()
    if not settings.has_email:
        console.print("[red]SMTP_EMAIL / SMTP_APP_PASSWORD not configured.[/]")
        return

    t0 = _time.monotonic()
    new_entries = inventory_view.today_entries(days=days)
    console.print(f"[blue]Window: {len(new_entries)} new entries (last {days}d)[/]")

    summary = None
    if settings.has_anthropic:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Building daily summary...", total=None)
            summary = daily_summary.build_daily_summary(new_entries=new_entries)
            progress.update(task, completed=True)
        if summary is None:
            console.print("[yellow]Summary unavailable — email will show stub.[/]")
    else:
        console.print("[yellow]No ANTHROPIC_API_KEY — skipping summary.[/]")

    briefs: list[Path] = []
    if not no_synth and settings.has_anthropic and new_entries:
        inventory = inventory_view.load_inventory()
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Running synthesizer...", total=None)
            concepts = synthesizer.synthesize(
                new_entries, inventory=inventory, max_briefs=max_briefs
            )
            progress.update(task, completed=True)
        if concepts:
            briefs = synthesizer.deliver(concepts)
            console.print(f"[green]Synthesizer delivered {len(briefs)} briefs[/]")

    elapsed = _time.monotonic() - t0

    if dry_run:
        html = emailer.build_html(
            new_entries=new_entries,
            briefs=briefs,
            summary=summary,
            inventory_total=len(inventory_view.load_inventory()),
            elapsed_seconds=elapsed,
        )
        console.print(Panel(
            f"[bold]Dry-run:[/] would send email to {settings.smtp_email}\n"
            f"entries={len(new_entries)}  briefs={len(briefs)}  "
            f"summary={'yes' if summary else 'no'}  elapsed={elapsed:.1f}s\n"
            f"html length: {len(html)} chars"
        ))
        return

    ok = emailer.send_intel_email(
        new_entries=new_entries,
        briefs=briefs,
        summary=summary,
        elapsed_seconds=elapsed,
    )
    if ok:
        console.print(f"[green]Intel email sent to {settings.smtp_email}[/]")
    else:
        console.print("[red]Intel email failed (see [intel.emailer] log line)[/]")


# --- Q-day Clock export ---

@cli.command("qday-export")
@click.option(
    "--output", "-o",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Output JSON path for the signed manifest.",
)
@click.option(
    "--signing-key",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Path to a base64-encoded 32-byte Ed25519 private key. "
        "If omitted the manifest is written unsigned (Q-day Clock will "
        "refuse to ingest unsigned input)."
    ),
)
@click.option(
    "--min-relevance",
    type=float,
    default=0.0,
    show_default=True,
    help="Drop articles with relevance_score below this threshold.",
)
@click.option(
    "--limit",
    type=int,
    default=5000,
    show_default=True,
    help="Cap on number of articles considered.",
)
def qday_export(
    output: Path,
    signing_key: Path | None,
    min_relevance: float,
    limit: int,
):
    """Export a signed Curator manifest for the Q-day Clock.

    The output JSON matches the CuratorManifest schema in
    qday_clock.core.schemas. The Q-day Clock package must be importable
    for signing to work.
    """
    from .qday_export import write_manifest

    final = write_manifest(
        output_path=output,
        signing_key_path=signing_key,
        min_relevance=min_relevance,
        limit=limit,
    )

    n_articles = len(final.get("articles", []))
    signed = "signing_pubkey" in final
    console.print(
        f"[green]Wrote manifest:[/] {output} "
        f"({n_articles} articles, "
        f"{'signed' if signed else '[red]UNSIGNED[/]'})"
    )
    if signed:
        fingerprint = final["signing_pubkey"][:16]
        console.print(f"[dim]Signing pubkey (first 16): {fingerprint}…[/]")


if __name__ == "__main__":
    cli()
