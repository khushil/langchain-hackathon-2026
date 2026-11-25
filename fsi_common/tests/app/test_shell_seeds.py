"""APP_SEED as a list of topic names, in a shell and in the processes it starts."""

from __future__ import annotations

from pathlib import Path

from app_probe_topic import make_probe_topic, two_probes
from app_shell_support import carrying, running_shell, start_shell, wait_gone

from fsi_common.app import AppConfig
from fsi_common.app.children import TopicChild, child_environment
from fsi_common.app.topic_info import TopicInfo


def seeded(run, name: str) -> bool:
    with run.client() as http:
        return http.get(f"/{name}/state").json()["seeded"]


def test_a_list_of_names_makes_the_starting_work_of_every_topic_named(tmp_path):
    first, second = two_probes(tmp_path)
    with running_shell(tmp_path, [first, second], extra_env={"APP_SEED": "alpha,beta"}) as run:
        assert seeded(run, "alpha") is True and seeded(run, "beta") is True


def test_a_list_with_spaces_and_a_repeat_seeds_each_named_topic(tmp_path):
    first, second = two_probes(tmp_path)
    with running_shell(tmp_path, [first, second], extra_env={"APP_SEED": " beta , ,beta"}) as run:
        assert seeded(run, "alpha") is False and seeded(run, "beta") is True


def test_one_name_seeds_that_topic_alone_as_before(tmp_path):
    first, second = two_probes(tmp_path)
    with running_shell(tmp_path, [first, second], extra_env={"APP_SEED": "alpha"}) as run:
        assert seeded(run, "alpha") is True and seeded(run, "beta") is False


def test_an_unknown_name_in_the_list_stops_the_start_with_the_names_there_are(tmp_path):
    first, second = two_probes(tmp_path)
    run = start_shell(tmp_path, [first, second], extra_env={"APP_SEED": "alpha,gamma"}, wait=False)
    assert run.process.wait(timeout=60) != 0
    log = run.log.read_text()
    assert "APP_SEED is 'gamma'" in log and "topics served: alpha, beta" in log
    assert wait_gone(carrying(str(tmp_path))) == []


def test_every_name_of_the_list_is_checked_not_only_the_first(tmp_path):
    first, second = two_probes(tmp_path)
    run = start_shell(
        tmp_path, [first, second], extra_env={"APP_SEED": "gamma,alpha,delta"}, wait=False
    )
    assert run.process.wait(timeout=60) != 0
    assert (
        "APP_SEED names gamma and delta, which are not topics served here; "
        "the topics are alpha and beta." in run.log.read_text()
    )


def test_a_topic_started_again_is_given_its_own_name_and_no_other(tmp_path, monkeypatch):
    folder = make_probe_topic(tmp_path, "01_alpha_agent", name="alpha", value="a")
    config = AppConfig(secret=b"s", topic_folders=(), seed="beta,alpha")
    seen: list[dict] = []

    class FakeProcess:
        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        seen.append(kwargs["env"])
        return FakeProcess()

    monkeypatch.setattr("fsi_common.app.children.subprocess.Popen", fake_popen)
    child = TopicChild(folder=folder, state=None)
    child.start(config)
    assert seen[-1]["APP_SEED"] == "beta,alpha", "before it has answered its name is not known"
    child.info = TopicInfo(name="alpha", title="Alpha", prefix="/alpha")
    child.start(config)
    assert seen[-1]["APP_SEED"] == "alpha"
    child.info = TopicInfo(name="gamma", title="Gamma", prefix="/gamma")
    child.start(config)
    assert "APP_SEED" not in seen[-1]


def test_the_environment_of_a_topic_carries_the_setting_it_is_given(tmp_path):
    config = AppConfig(secret=b"s", topic_folders=(), seed="a,b")
    env = child_environment(config, Path(tmp_path), state=None, port=1, fd=2, seed="b")
    assert env["APP_SEED"] == "b"
    assert "APP_SEED" not in child_environment(
        config, Path(tmp_path), state=None, port=1, fd=2, seed=""
    )


def test_a_refused_start_may_leave_starting_work_and_the_next_correct_start_reuses_it(tmp_path):
    first, second = two_probes(tmp_path)
    refused = start_shell(
        tmp_path, [first, second], extra_env={"APP_SEED": "alpha,nosuch"}, wait=False
    )
    assert refused.process.wait(timeout=60) != 0
    assert "APP_SEED is 'nosuch'" in refused.log.read_text()
    marker = refused.state_dir / "01_alpha_agent" / "seeded.txt"
    assert marker.read_text() == "seeded once\n", "the refused start left alpha's work, intact"
    with running_shell(tmp_path, [first, second], extra_env={"APP_SEED": "alpha,beta"}) as run:
        with run.client() as http:
            alpha, beta = http.get("/alpha/state").json(), http.get("/beta/state").json()
        assert alpha["seeded"] is True and alpha["made"] is False, "alpha reuses, it does not redo"
        assert beta["seeded"] is True and beta["made"] is True
    assert marker.read_text() == "seeded once\n", "the work was not made twice"
