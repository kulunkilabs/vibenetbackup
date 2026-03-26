import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.modules.destinations.base import DestinationBackend

logger = logging.getLogger(__name__)


class ForgejoDestination(DestinationBackend):
    """Commit configs to a local git repo, optionally push to Forgejo remote."""

    async def save(self, hostname: str, config_text: str, config: dict[str, Any]) -> str:
        repo_path = config.get("repo_path", "./repos/device-configs")
        branch = config.get("branch", "main")

        def _git_save() -> str:
            import git

            # Init or open repo
            if not os.path.exists(os.path.join(repo_path, ".git")):
                os.makedirs(repo_path, exist_ok=True)
                repo = git.Repo.init(repo_path)
                # Create initial commit if empty
                readme = os.path.join(repo_path, "README.md")
                if not os.path.exists(readme):
                    with open(readme, "w") as f:
                        f.write("# Device Configuration Backups\n")
                    repo.index.add(["README.md"])
                    repo.index.commit("Initial commit")
            else:
                repo = git.Repo(repo_path)

            # Write config file (sanitize hostname to prevent path traversal)
            safe_hostname = os.path.basename(hostname.replace("\\", "/")) or "unknown"
            cfg_filename = f"{safe_hostname}.cfg"
            cfg_path = os.path.join(repo_path, cfg_filename)
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write(config_text)

            # Stage and commit
            repo.index.add([cfg_filename])
            if repo.is_dirty(index=True):
                timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                repo.index.commit(f"Backup: {hostname} - {timestamp}")
                logger.info("Forgejo: committed config for %s", hostname)
            else:
                logger.info("Forgejo: no changes for %s, skipping commit", hostname)

            # Push to remote if configured
            remote_url = config.get("remote_url")
            if remote_url:
                try:
                    if "origin" not in [r.name for r in repo.remotes]:
                        repo.create_remote("origin", remote_url)
                    origin = repo.remotes.origin
                    origin.push(refspec=f"HEAD:{branch}")
                    logger.info("Forgejo: pushed to %s", remote_url)
                except Exception as e:
                    logger.warning("Forgejo: push failed: %s", e)

            return cfg_path

        path = await asyncio.to_thread(_git_save)
        return path

    async def delete(self, path: str, config: dict[str, Any]) -> None:
        # For git destinations, we don't delete individual files by default
        logger.info("Forgejo: retention delete for %s (no-op for git)", path)
