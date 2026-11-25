"""Tests of the README's build history: the sentence built from git and the check against it."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from fsi_common.readme_history import (
    CheckStatus,
    HistoryError,
    build_sentence,
    check_readme,
    main,
    refresh_readme,
)

GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "T",
    "GIT_AUTHOR_EMAIL": "t@example.test",
    "GIT_COMMITTER_NAME": "T",
    "GIT_COMMITTER_EMAIL": "t@example.test",
}


def git(folder: Path, *args: str, when: str | None = None) -> str:
    env = dict(GIT_ENV)
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    done = subprocess.run(
        ["git", "-C", str(folder), *args], env=env, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository of four commits, over two days."""
    git(tmp_path, "init", "-q")
    for stamp, subject in [
        ("2026-11-24T18:37:10+00:00", "feat(core): the layout"),
        ("2026-11-24T19:00:00+00:00", "fix(core): a mistake"),
        ("2026-11-24T20:55:20+00:00", "feat(app): the application"),
        ("2026-11-25T09:00:00+00:00", "docs: a later change"),
    ]:
        git(tmp_path, "commit", "-q", "--allow-empty", "-m", subject, when=stamp)
    return tmp_path


def short(repo: Path, rev: str = "HEAD") -> str:
    return git(repo, "rev-parse", "--short=7", rev)


def sentence_at_head(repo: Path) -> str:
    return (
        f"The build up to commit `{short(repo)}` ran from 18:37 UTC on 24 November "
        "2026 to 09:00 UTC "
        "on 25 November 2026, 14 hours 23 minutes, in 4 commits (2 feat, 1 docs, 1 fix)."
    )


def write_readme(folder: Path, sentence: str) -> Path:
    readme = folder / "README.md"
    readme.write_text(
        f"# Title\n\nIntro.\n\n## How it was built\n\n{sentence} More words.\n\n## Next\n\nText.\n",
        encoding="utf-8",
    )
    return readme


def commit_readme(repo: Path) -> None:
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "docs(readme): refresh", when="2026-11-25T10:00:00+00:00")


def test_the_sentence_covers_the_commits_up_to_the_revision_given(repo):
    assert build_sentence(repo, "HEAD") == sentence_at_head(repo)
    assert build_sentence(repo, "HEAD~1") == (
        f"The build up to commit `{short(repo, 'HEAD~1')}` ran from 18:37 to 20:55 UTC on "
        "24 November 2026, 2 hours 18 minutes, in 3 commits (2 feat, 1 fix)."
    )


def test_a_readme_that_holds_the_sentence_at_head_passes(repo):
    readme = write_readme(repo, sentence_at_head(repo))
    assert check_readme(readme, repo).status is CheckStatus.OK


def test_a_commit_that_changes_only_the_readme_after_it_leaves_it_current(repo):
    readme = write_readme(repo, sentence_at_head(repo))
    commit_readme(repo)
    assert check_readme(readme, repo, strict=True).status is CheckStatus.OK


def test_a_later_commit_of_anything_else_makes_it_stale_and_says_how_many(repo):
    readme = write_readme(repo, sentence_at_head(repo))
    commit_readme(repo)
    (repo / "code.py").write_text("x = 1\n")
    git(repo, "add", "code.py")
    git(repo, "commit", "-q", "-m", "feat(app): more", when="2026-11-25T11:00:00+00:00")
    result = check_readme(readme, repo, strict=True)
    assert result.status is CheckStatus.STALE
    assert "1 commit" in result.message and "README.md:7" in result.message
    assert check_readme(readme, repo).status is CheckStatus.OK
    assert main(["--check", str(readme), "--root", str(repo), "--strict"]) == 1
    assert main(["--check", str(readme), "--root", str(repo)]) == 0


def test_a_later_empty_commit_makes_it_stale(repo):
    readme = write_readme(repo, sentence_at_head(repo))
    git(
        repo,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "chore: empty",
        when="2026-11-25T11:00:00+00:00",
    )
    assert check_readme(readme, repo, strict=True).status is CheckStatus.STALE


def test_one_changed_count_fails_and_names_the_line(repo, capsys):
    readme = write_readme(repo, sentence_at_head(repo).replace("in 4 commits", "in 5 commits"))
    result = check_readme(readme, repo)
    assert result.status is CheckStatus.MISMATCH
    assert "README.md:7" in result.message
    assert "in 5 commits" in result.message and "in 4 commits" in result.message
    assert main(["--check", str(readme), "--root", str(repo)]) == 1
    assert "README.md:7" in capsys.readouterr().out


def test_a_readme_without_the_sentence_fails(repo):
    readme = write_readme(repo, "Some other opening.")
    result = check_readme(readme, repo)
    assert result.status is CheckStatus.MISMATCH
    assert "The build up to commit" in result.message


def test_a_commit_the_readme_names_that_is_not_in_the_history_fails(repo):
    readme = write_readme(repo, sentence_at_head(repo).replace(short(repo), "1111111"))
    result = check_readme(readme, repo)
    assert result.status is CheckStatus.MISSING_COMMIT
    assert "1111111" in result.message


def sentence_on_a_side_branch(repo: Path) -> str:
    """The correct sentence for a commit that is on another branch, not in HEAD's history."""
    git(repo, "checkout", "-q", "-b", "side", "HEAD~2")
    git(
        repo, "commit", "-q", "--allow-empty", "-m", "feat: aside", when="2026-11-25T08:00:00+00:00"
    )
    sentence = build_sentence(repo, "side")
    git(repo, "checkout", "-q", "-")
    return sentence


@pytest.mark.parametrize("strict", [False, True])
def test_a_commit_on_another_branch_fails_even_though_git_has_it(repo, strict):
    readme = write_readme(repo, sentence_on_a_side_branch(repo))
    result = check_readme(readme, repo, strict=strict)
    assert result.status is CheckStatus.MISSING_COMMIT
    assert "README.md:7" in result.message and "not in" in result.message
    argv = ["--check", str(readme), "--root", str(repo)]
    assert main(argv + (["--strict"] if strict else [])) == 1


def test_a_commit_in_the_history_of_head_passes_after_head_has_moved_on(repo):
    readme = write_readme(repo, build_sentence(repo, "HEAD~2"))
    assert check_readme(readme, repo).status is CheckStatus.OK


def test_the_length_agrees_with_the_times_shown_to_the_minute(tmp_path):
    """18:37:54 to 13:41:48 is 19 h 3 min 54 s, yet the times as printed are 19 h 4 min apart."""
    git(tmp_path, "init", "-q")
    for stamp in ("2026-11-24T18:37:54+00:00", "2026-11-25T13:41:48+00:00"):
        git(tmp_path, "commit", "-q", "--allow-empty", "-m", "feat: a", when=stamp)
    assert build_sentence(tmp_path, "HEAD") == (
        f"The build up to commit `{short(tmp_path)}` ran from 18:37 UTC on 24 November 2026 to "
        "13:41 UTC on 25 November 2026, 19 hours 4 minutes, in 2 commits (2 feat)."
    )


def test_a_folder_without_git_is_skipped_with_the_reason_stated(tmp_path, capsys):
    readme = write_readme(tmp_path, "A sentence that is wrong.")
    code = main(["--check", str(readme), "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("SKIPPED: ") and "no .git" in out


def test_a_shallow_clone_is_skipped_with_the_reason_stated(repo, tmp_path):
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", "--depth", "1", f"file://{repo}", str(clone))
    readme = write_readme(clone, "A sentence that is wrong.")
    result = check_readme(readme, clone)
    assert result.status is CheckStatus.SKIPPED
    assert "shallow" in result.message


def test_refresh_rewrites_the_sentence_at_head_and_keeps_the_rest_of_the_line(repo):
    old = sentence_at_head(repo).replace(
        "in 4 commits (2 feat, 1 docs, 1 fix)", "in 2 commits (2 feat)"
    )
    readme = write_readme(repo, old)
    assert check_readme(readme, repo).status is CheckStatus.MISMATCH
    refresh_readme(readme, repo)
    assert check_readme(readme, repo).status is CheckStatus.OK
    assert f"{sentence_at_head(repo)} More words." in readme.read_text(encoding="utf-8")


def test_refresh_of_a_readme_without_the_sentence_raises(repo):
    readme = write_readme(repo, "Some other opening.")
    with pytest.raises(HistoryError, match="The build up to commit"):
        refresh_readme(readme, repo)
