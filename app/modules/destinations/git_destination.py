import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.modules.destinations.base import DestinationBackend

logger = logging.getLogger(__name__)


class GitDestination(DestinationBackend):
    """Commit configs to a local git repo, optionally push to a remote.

    Supports GitHub, Gitea, Forgejo, and any Git-compatible remote.

    Auth methods (set via config_json):
      - Token (HTTPS):  {"remote_url": "https://github.com/org/repo.git", "auth_method": "token", "token": "ghp_..."}
      - SSH:            {"remote_url": "git@github.com:org/repo.git", "auth_method": "ssh", "ssh_key_path": "/app/ssh_keys/id_ed25519"}
      - Username/Pass:  {"remote_url": "https://gitea.local/org/repo.git", "auth_method": "password", "username": "user", "password": "pass"}
      - None:           {"remote_url": "https://github.com/org/public-repo.git"}  (public repos only)
    """

    async def save(self, hostname: str, config_text: str, config: dict[str, Any]) -> str:
        repo_path = config.get("repo_path", "./repos/device-configs")
        branch = config.get("branch", "main")

        def _git_save() -> str:
            import git

            # Init or open repo
            if not os.path.exists(os.path.join(repo_path, ".git")):
                os.makedirs(repo_path, exist_ok=True)
                repo = git.Repo.init(repo_path)
                readme = os.path.join(repo_path, "README.md")
                if not os.path.exists(readme):
                    with open(readme, "w") as f:
                        f.write("# Device Configuration Backups\n")
                    repo.index.add(["README.md"])
                    repo.index.commit("Initial commit")
            else:
                repo = git.Repo(repo_path)

            # Write config file
            cfg_filename = f"{hostname}.cfg"
            cfg_path = os.path.join(repo_path, cfg_filename)
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write(config_text)

            # Stage and commit
            repo.index.add([cfg_filename])
            if repo.is_dirty(index=True):
                timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                repo.index.commit(f"Backup: {hostname} - {timestamp}")
                logger.info("Git: committed config for %s", hostname)
            else:
                logger.info("Git: no changes for %s, skipping commit", hostname)

            # Push to remote if configured
            remote_url = config.get("remote_url")
            if remote_url:
                push_url = self._build_push_url(remote_url, config)
                try:
                    if "origin" not in [r.name for r in repo.remotes]:
                        repo.create_remote("origin", push_url)
                    else:
                        repo.remotes.origin.set_url(push_url)

                    push_env = self._build_push_env(config)
                    with repo.git.custom_environment(**push_env):
                        repo.remotes.origin.push(refspec=f"HEAD:{branch}")
                    logger.info("Git: pushed to %s", remote_url)
                except Exception as e:
                    logger.warning("Git: push failed: %s", e)

            return cfg_path

        path = await asyncio.to_thread(_git_save)
        return path

    async def delete(self, path: str, config: dict[str, Any]) -> None:
        logger.info("Git: retention delete for %s (no-op for git)", path)

    @staticmethod
    def _build_push_url(remote_url: str, config: dict[str, Any]) -> str:
        """Embed credentials into HTTPS URL if needed."""
        auth_method = config.get("auth_method", "")

        if auth_method == "token":
            token = config.get("token", "")
            if token and remote_url.startswith("https://"):
                # https://github.com/org/repo.git → https://token@github.com/org/repo.git
                return remote_url.replace("https://", f"https://x-access-token:{token}@", 1)

        elif auth_method == "password":
            username = config.get("username", "")
            password = config.get("password", "")
            if username and remote_url.startswith("https://"):
                from urllib.parse import quote
                return remote_url.replace(
                    "https://",
                    f"https://{quote(username, safe='')}:{quote(password, safe='')}@",
                    1,
                )

        # SSH or no auth — return as-is
        return remote_url

    @staticmethod
    def _build_push_env(config: dict[str, Any]) -> dict[str, str]:
        """Build environment variables for git push (SSH key, etc.)."""
        env: dict[str, str] = {}
        auth_method = config.get("auth_method", "")

        if auth_method == "ssh":
            ssh_key_path = config.get("ssh_key_path", "")
            if ssh_key_path:
                env["GIT_SSH_COMMAND"] = (
                    f"ssh -i {ssh_key_path} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
                )

        return env
