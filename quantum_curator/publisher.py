"""GitHub Pages deployment for Quantum Curator."""

from __future__ import annotations

import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .config import get_settings


class GitHubPagesPublisher:
    """Deploy static site to GitHub Pages."""

    def __init__(self):
        self.settings = get_settings()

    def deploy(
        self,
        site_dir: Path,
        repo_url: str | None = None,
        branch: str = "gh-pages",
        commit_message: str | None = None,
    ) -> bool:
        """Deploy site directory to GitHub Pages.

        Args:
            site_dir: Path to built site directory
            repo_url: GitHub repo URL (default from settings)
            branch: Branch to deploy to
            commit_message: Custom commit message

        Returns:
            True if deployment successful
        """
        repo_url = repo_url or self.settings.github_repo

        if not repo_url:
            print("Error: No GitHub repository URL configured")
            return False

        if not site_dir.exists():
            print(f"Error: Site directory not found: {site_dir}")
            return False

        if commit_message is None:
            commit_message = f"Deploy: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"

        try:
            # Create temporary directory for git operations
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)

                # Clone the repo (shallow, specific branch)
                result = subprocess.run(
                    ["git", "clone", "--depth", "1", "-b", branch, repo_url, str(tmp_path)],
                    capture_output=True,
                    text=True,
                )

                if result.returncode != 0:
                    # Branch might not exist, create orphan
                    subprocess.run(
                        ["git", "clone", "--depth", "1", repo_url, str(tmp_path)],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    subprocess.run(
                        ["git", "-C", str(tmp_path), "checkout", "--orphan", branch],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    subprocess.run(
                        ["git", "-C", str(tmp_path), "rm", "-rf", "."],
                        capture_output=True,
                        text=True,
                    )

                # Clear existing content (except .git)
                for item in tmp_path.iterdir():
                    if item.name != ".git":
                        if item.is_dir():
                            import shutil
                            shutil.rmtree(item)
                        else:
                            item.unlink()

                # Copy new site content
                import shutil
                for item in site_dir.iterdir():
                    if item.is_dir():
                        shutil.copytree(item, tmp_path / item.name)
                    else:
                        shutil.copy2(item, tmp_path / item.name)

                # Configure git
                subprocess.run(
                    ["git", "-C", str(tmp_path), "config", "user.email", "curator@quantum-curator.com"],
                    capture_output=True,
                    check=True,
                )
                subprocess.run(
                    ["git", "-C", str(tmp_path), "config", "user.name", "Quantum Curator Bot"],
                    capture_output=True,
                    check=True,
                )

                # Add and commit
                subprocess.run(
                    ["git", "-C", str(tmp_path), "add", "-A"],
                    capture_output=True,
                    check=True,
                )

                # Check if there are changes
                result = subprocess.run(
                    ["git", "-C", str(tmp_path), "diff", "--staged", "--quiet"],
                    capture_output=True,
                )

                if result.returncode == 0:
                    print("No changes to deploy")
                    return True

                subprocess.run(
                    ["git", "-C", str(tmp_path), "commit", "-m", commit_message],
                    capture_output=True,
                    check=True,
                )

                # Push
                subprocess.run(
                    ["git", "-C", str(tmp_path), "push", "origin", branch],
                    capture_output=True,
                    check=True,
                )

                print(f"Successfully deployed to {repo_url} ({branch})")
                return True

        except subprocess.CalledProcessError as e:
            print(f"Deployment error: {e}")
            print(f"stdout: {e.stdout}")
            print(f"stderr: {e.stderr}")
            return False
        except Exception as e:
            print(f"Deployment failed: {e}")
            return False

    def verify_deployment(self, site_url: str | None = None) -> bool:
        """Verify the deployment is accessible.

        Args:
            site_url: URL to check (default from settings)

        Returns:
            True if site is accessible
        """
        import httpx

        site_url = site_url or self.settings.site_url

        try:
            response = httpx.get(f"{site_url}/", follow_redirects=True, timeout=10)
            if response.status_code == 200:
                print(f"Site verified at {site_url}")
                return True
            else:
                print(f"Site returned status {response.status_code}")
                return False
        except Exception as e:
            print(f"Verification failed: {e}")
            return False


def deploy_site(site_dir: Path, repo_url: str | None = None) -> bool:
    """Convenience function to deploy site."""
    publisher = GitHubPagesPublisher()
    return publisher.deploy(site_dir, repo_url)
