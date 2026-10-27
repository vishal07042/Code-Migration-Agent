"""Git helper: per-file commits (free rollback) via GitPython."""

from __future__ import annotations

import hashlib
from pathlib import Path

from git import Repo
from git.exc import InvalidGitRepositoryError


def ensure_repo(path: str | Path) -> Repo:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    try:
        return Repo(str(p))
    except InvalidGitRepositoryError:
        repo = Repo.init(str(p))
        # Ensure at least one commit so revert paths work.
        keep = p / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")
        repo.index.add([str(keep.relative_to(p))])
        repo.index.commit("chore: init migration repo")
        return repo


def hash_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def commit_file(repo: Repo, workdir: str | Path, rel_path: str, message: str) -> str:
    workdir = Path(workdir)
    repo.index.add([rel_path])
    commit = repo.index.commit(message)
    return commit.hexsha


def revert_file(repo: Repo, rel_path: str, ref: str = "HEAD") -> None:
    """Restore one file from a git ref (default HEAD). Raises if file not in ref."""
    repo.git.checkout(ref, "--", rel_path)


def file_at_ref(repo: Repo, rel_path: str, ref: str = "HEAD") -> bytes:
    out: str = repo.git.show(f"{ref}:{rel_path}")
    return out.encode("utf-8")
