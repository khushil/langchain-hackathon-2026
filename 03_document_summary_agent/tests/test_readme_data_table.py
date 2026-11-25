"""Tests that the README's data table lists every data file the repository holds."""

import os
import re
import subprocess

from utils import PROJECT_ROOT

REPO = PROJECT_ROOT.parent
README = REPO / "README.md"
DATA_PLACES = (
    "03_document_summary_agent/data",
    "03_document_summary_agent/evals/data",
    "03_document_summary_agent/recordings",
    "fsi_common/fsi_common/examples",
    "fsi_common/fsi_common/schemas",
)
_PATH = re.compile(r"`([^`]+)`")


def table_paths(readme: str) -> list[str]:
    """Return the paths the data table's first column names.

    A cell may name several paths separated by commas; one with no slash is in the folder of the
    path before it. A path that ends with a slash names a folder and everything in it.

    Args:
        readme: The README's text.

    Returns:
        The paths, relative to the repository's root.
    """
    section = readme.split("## The data and its terms", 1)[1].split("\n## ", 1)[0]
    paths: list[str] = []
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        folder = ""
        for name in _PATH.findall(line.split(" | ")[0]):
            path = name if "/" in name.rstrip("/") else folder + name
            folder = path.rsplit("/", 1)[0] + "/" if "/" in path.rstrip("/") else folder
            paths.append(path)
    return paths


def data_files() -> list[str]:
    """Return every data file in the repository that git does not ignore, as a path from its root.

    Returns:
        The files under the data places, from ``git ls-files`` where the tree is a git work tree
        and from the file system in a copy without git.
    """
    try:
        listed = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "-co", "--exclude-standard", "--", *DATA_PLACES],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        listed = walked_files(REPO, DATA_PLACES)
    return sorted(p for p in listed if "__pycache__" not in p)


def _ignores_everything(folder: str) -> bool:
    ignore = os.path.join(folder, ".gitignore")
    if not os.path.isfile(ignore):
        return False
    with open(ignore, encoding="utf-8") as handle:
        rules = [line.strip() for line in handle if line.strip() and not line.startswith("#")]
    return rules == ["*"]


def walked_files(repo, places) -> list[str]:
    """Return the files under each place, walking the file system as a copy without git must.

    A folder whose own ``.gitignore`` holds only ``*`` is left out with everything below it, as
    git leaves it out, because such a folder holds what a build fetched or wrote, such as the
    regulations' cache.

    Args:
        repo: The repository's root.
        places: The folders to walk, relative to the root.

    Returns:
        The files as paths from the root, sorted.
    """
    found = []
    for place in places:
        for root, folders, names in os.walk(os.path.join(repo, place)):
            if _ignores_everything(root):
                folders[:] = []
                continue
            found += [os.path.relpath(os.path.join(root, name), repo) for name in names]
    return sorted(found)


def covered(path: str, listed: list[str]) -> bool:
    """Say whether a table path names a file or a folder that holds it."""
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in listed)


def test_every_data_file_is_in_the_readme_data_table():
    listed = table_paths(README.read_text(encoding="utf-8"))
    files = data_files()
    assert files
    missing = [f for f in files if not covered(f, listed)]
    assert not missing, f"{len(missing)} of {len(files)} data files are not in the table: {missing}"


def test_every_path_the_table_names_exists():
    for path in table_paths(README.read_text(encoding="utf-8")):
        assert (REPO / path).exists(), path


def test_table_paths_reads_folders_and_comma_lists():
    readme = (
        "## The data and its terms\n\n| Path | What | Terms |\n| --- | --- | --- |\n"
        "| `a/b/c.json`, `D.md` | x | y |\n| `a/e/` | x | y |\n\n## Next\n| `z/q` | no | no |\n"
    )
    assert table_paths(readme) == ["a/b/c.json", "a/b/D.md", "a/e/"]
    assert covered("a/e/f/g.txt", ["a/e/"]) and not covered("a/ef.txt", ["a/e/"])


def test_walked_files_leave_out_a_folder_whose_own_ignore_file_is_a_star(tmp_path):
    data = tmp_path / "03_document_summary_agent" / "data"
    (data / "cache").mkdir(parents=True)
    (data / "kept").mkdir()
    (data / "table.jsonl").write_text("{}\n", encoding="utf-8")
    (data / "cache" / ".gitignore").write_text("*\n", encoding="utf-8")
    (data / "cache" / "fetched.pdf").write_bytes(b"%PDF fetched")
    (data / "kept" / ".gitignore").write_text("fetched/\n", encoding="utf-8")
    (data / "kept" / "manifest.json").write_text("{}\n", encoding="utf-8")
    assert walked_files(tmp_path, ["03_document_summary_agent/data"]) == [
        "03_document_summary_agent/data/kept/.gitignore",
        "03_document_summary_agent/data/kept/manifest.json",
        "03_document_summary_agent/data/table.jsonl",
    ]
