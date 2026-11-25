"""The offline file of one topic when two or more are built: each is read in its own process."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from app_probe_topic import make_broken_topic, make_probe_topic
from app_shell_support import FSI_COMMON


def export(tmp_path, folders, topic, *extra):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(
        APP_TOPICS=os.pathsep.join(str(f) for f in folders),
        PYTHONPATH=str(FSI_COMMON),
        LANGSMITH_TRACING="false",
    )
    out = tmp_path / f"{topic}.html"
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "fsi_common.app.offline",
            "--topic",
            topic,
            "--out",
            str(out),
            *extra,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return done, out


@pytest.fixture()
def two(tmp_path):
    return (
        make_probe_topic(tmp_path, "01_alpha_agent", name="alpha", value="alpha-value"),
        make_probe_topic(tmp_path, "02_beta_agent", name="beta", value="beta-value"),
    )


@pytest.mark.parametrize(
    ("topic", "wanted", "other"),
    [
        ("alpha", "Value is alpha-value.", "beta-value"),
        ("beta", "Value is beta-value.", "alpha-value"),
    ],
)
def test_each_topics_offline_file_is_made_from_that_topic_alone(
    tmp_path, two, topic, wanted, other
):
    done, out = export(tmp_path, two, topic)
    assert done.returncode == 0, done.stderr
    assert f"Wrote {out}" in done.stdout
    page = out.read_text()
    assert wanted in page and other not in page


def test_a_topic_that_is_not_built_is_refused_naming_every_topic_there_is(tmp_path, two):
    done, out = export(tmp_path, two, "gamma")
    assert done.returncode == 1
    assert "There is no offline topic 'gamma'; there is: alpha, beta." in done.stderr
    assert not out.exists()


def broken_hook(tmp_path):
    broken = make_probe_topic(tmp_path, "00_gamma_agent", name="gamma", value="g")
    (broken / "review_app" / "offline.py").write_text("import a_module_that_does_not_exist\n")
    return broken


def test_a_topic_whose_hook_cannot_be_imported_does_not_stop_another_topics_export(tmp_path, two):
    done, out = export(tmp_path, [broken_hook(tmp_path), *two], "alpha")
    assert done.returncode == 0, done.stderr
    assert "Value is alpha-value." in out.read_text()


def test_the_topic_whose_hook_cannot_be_imported_is_refused_with_its_reason(tmp_path, two):
    done, out = export(tmp_path, [broken_hook(tmp_path), *two], "gamma")
    assert done.returncode == 1
    assert "The offline file was not written." in done.stderr
    assert "a_module_that_does_not_exist" in done.stderr
    assert not out.exists()


def test_a_folder_with_no_offline_part_is_left_out_of_the_choice(tmp_path, two):
    plain = make_broken_topic(tmp_path, "04_plain_agent")
    done, _ = export(tmp_path, [*two, plain], "beta")
    assert done.returncode == 0, done.stderr


def test_a_worker_is_given_its_own_folder_and_the_shared_package_on_its_path_and_no_secret(
    tmp_path, two
):
    from fsi_common.app.children import worker_environment

    env = worker_environment(two[0])
    assert env["PYTHONPATH"].split(os.pathsep) == [str(FSI_COMMON), str(two[0])]
    assert "APP_SECRET" not in env and "APP_TOPICS" not in env
