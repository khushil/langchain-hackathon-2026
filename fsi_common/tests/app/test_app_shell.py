"""The shell's layout, sign-in, About, topic registry and errors, with Starlette's test client."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from app_toy_topic import make_toy_folder
from starlette.testclient import TestClient

from fsi_common.app import (
    AppConfig,
    NoTopicsError,
    TopicLoadError,
    create_app,
)
from fsi_common.app.topics import load_topics

ADVICE = "regulatory advice"
ADVICE_OPENING = "Outputs of this product are not legal"


@pytest.fixture()
def topic_folder(tmp_path):
    return make_toy_folder(tmp_path)


@pytest.fixture()
def client(topic_folder):
    config = AppConfig(secret=b"test-secret", topic_folders=(topic_folder,))
    return TestClient(create_app(config), follow_redirects=False)


def test_home_lists_the_topic_and_the_layout_carries_one_demo_tag(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Review desk" in page.text
    assert 'href="/toy/"' in page.text
    assert page.text.count('data-hook="demo-tag"') == 1
    assert 'href="/about"' in page.text
    assert "No item is waiting for a reviewer." in page.text


def test_every_page_has_an_answer_sentence_at_most_three_tiles_and_one_exhibit(client):
    for path in ("/", "/about", "/signin", "/toy/", "/nowhere"):
        page = client.get(path)
        assert page.text.count('data-hook="sentence"') == 1, path
        assert page.text.count('data-hook="tile"') <= 3, path
        assert page.text.count('data-hook="exhibit"') == 1, path


def test_the_topic_page_renders_inside_the_layout_and_its_static_file_is_served(client):
    page = client.get("/toy/")
    assert "The toy topic has 2 things." in page.text
    assert 'class="topbar"' in page.text
    assert client.get("/toy/static/toy.css").text.startswith("body")
    assert client.get("/static/app.css").status_code == 200


def test_about_holds_the_advice_sentence_and_each_topics_paragraphs(client):
    page = client.get("/about")
    assert ADVICE_OPENING in page.text and ADVICE in page.text
    assert "The toy topic holds invented things." in page.text
    assert "fictional" in page.text


def test_the_advice_sentence_is_on_no_other_page(client):
    for path in ("/", "/signin", "/toy/", "/nowhere"):
        assert ADVICE not in client.get(path).text, path


def test_sign_in_keeps_the_person_in_a_signed_cookie_and_sign_out_removes_it(client):
    done = client.post("/signin", data={"name": "Dana Whitfield", "role": "Head of Compliance"})
    assert done.status_code == 303
    page = client.get("/")
    assert "Dana Whitfield, Head of Compliance" in page.text
    assert 'action="/signout"' in page.text
    client.post("/signout")
    assert "Dana Whitfield" not in client.get("/").text


@pytest.mark.parametrize(
    ("name", "role", "words"),
    [
        ("", "Head of Compliance", "Type your name and the role you act in."),
        ("Dana", "   ", "Type your name and the role you act in."),
        ("Claude", "Head of Compliance", "a model, a program or a service"),
        ("Dana Whitfield", "AI", "a model, a program or a service"),
    ],
)
def test_sign_in_refuses_a_missing_or_machine_name_in_words(client, name, role, words):
    page = client.post("/signin", data={"name": name, "role": role})
    assert page.status_code == 422
    assert words in page.text
    assert "set-cookie" not in page.headers


def test_a_cookie_that_was_altered_or_signed_by_another_secret_signs_nobody_in(
    client, topic_folder
):
    client.post("/signin", data={"name": "Dana Whitfield", "role": "Head of Compliance"})
    value = client.cookies.get(client.app.state.cookie_name)
    assert value
    other = TestClient(
        create_app(AppConfig(secret=b"another", topic_folders=(topic_folder,))),
        cookies={client.app.state.cookie_name: value},
    )
    assert "Dana Whitfield" not in other.get("/").text
    forged = value.split(".")[0] + ".AAAA"
    client.cookies.set(client.app.state.cookie_name, forged)
    assert "Dana Whitfield" not in client.get("/").text


@pytest.mark.parametrize(
    "target", ["https://evil.example/", "//evil.example/", "javascript:alert(1)"]
)
def test_sign_in_never_sends_the_person_outside_the_application(client, target):
    done = client.post(
        "/signin", data={"name": "Dana Whitfield", "role": "Head of Compliance", "next": target}
    )
    assert done.headers["location"] == "/"


def test_sign_in_returns_to_the_page_asked_for(client):
    done = client.post(
        "/signin",
        data={"name": "Dana Whitfield", "role": "Head of Compliance", "next": "/toy/?x=1"},
    )
    assert done.headers["location"] == "/toy/?x=1"


def test_an_unknown_address_is_a_page_in_words_with_a_way_home(client):
    page = client.get("/compliance-brief/")
    assert page.status_code == 404
    assert "There is nothing at this address." in page.text
    assert 'href="/"' in page.text


def test_an_application_with_no_topics_fails_loudly(tmp_path):
    with pytest.raises(NoTopicsError, match="No topic is configured"):
        create_app(AppConfig(secret=b"x", topic_folders=()))
    with pytest.raises(NoTopicsError):
        create_app(AppConfig(secret=b"x"), topics=[])


def test_a_folder_without_a_plugin_is_refused_naming_the_folder(tmp_path):
    with pytest.raises(TopicLoadError, match="has no review_app/plugin.py") as raised:
        load_topics([tmp_path])
    assert str(tmp_path) in str(raised.value)


def test_a_plugin_that_does_not_import_is_refused_with_the_cause(tmp_path):
    folder = make_toy_folder(tmp_path)
    (folder / "review_app" / "plugin.py").write_text("import a_module_that_is_not_there\n")
    with pytest.raises(TopicLoadError, match="a_module_that_is_not_there"):
        load_topics([folder])


def test_a_plugin_without_plugin_is_refused(tmp_path):
    folder = make_toy_folder(tmp_path)
    (folder / "review_app" / "plugin.py").write_text("x = 1\n")
    with pytest.raises(TopicLoadError, match="exports no PLUGIN"):
        load_topics([folder])


def test_two_topics_with_one_package_name_load_side_by_side_and_leave_no_trace(tmp_path):
    first = make_toy_folder(tmp_path, "first")
    second = make_toy_folder(tmp_path, "second")
    source = (second / "review_app" / "plugin.py").read_text()
    (second / "review_app" / "plugin.py").write_text(
        source.replace('name="toy"', 'name="other"').replace('prefix="/toy"', 'prefix="/other"')
    )
    plugins = load_topics([first, second])
    assert [p.prefix for p in plugins] == ["/toy", "/other"]
    assert "review_app" not in sys.modules
    assert str(first.resolve()) not in sys.path


def test_two_topics_with_one_name_are_refused(tmp_path):
    with pytest.raises(TopicLoadError, match="share the name toy"):
        load_topics([make_toy_folder(tmp_path, "a"), make_toy_folder(tmp_path, "b")])


def test_config_reads_the_environment_with_the_documented_defaults():
    config = AppConfig.from_env({"APP_TOPICS": ""})
    assert (config.host, config.port) == ("127.0.0.1", 4803)
    assert AppConfig().host == "127.0.0.1"
    assert AppConfig.from_env({"APP_TOPICS": "", "APP_HOST": "0.0.0.0"}).host == "0.0.0.0"
    custom = AppConfig.from_env(
        {"APP_HOST": "127.0.0.1", "APP_PORT": "5000", "APP_SECRET": "s", "APP_TOPICS": "/a:/b"}
    )
    assert (custom.host, custom.port, custom.secret) == ("127.0.0.1", 5000, b"s")
    assert custom.topic_folders == (Path("/a"), Path("/b"))


@pytest.mark.parametrize("port", ["abc", "0", "70000"])
def test_config_refuses_a_port_it_cannot_use(port):
    from fsi_common.app import ConfigError

    with pytest.raises(ConfigError, match="APP_PORT"):
        AppConfig.from_env({"APP_PORT": port, "APP_TOPICS": ""})


def test_a_random_secret_is_made_per_process_when_none_is_given():
    one, two = AppConfig.from_env({"APP_TOPICS": ""}), AppConfig.from_env({"APP_TOPICS": ""})
    assert one.secret != two.secret
    assert len(one.secret) == 32


def test_the_shell_names_no_regulatory_document():
    folder = Path(__file__).resolve().parents[2] / "fsi_common" / "app"
    text = "\n".join(
        p.read_text() for p in folder.rglob("*") if p.suffix in {".py", ".html", ".css"}
    )
    assert not re.search(r"PS26|FIRM-0|Harbour|NimbusCloud", text)


def test_the_module_serves_on_the_host_and_port_the_environment_names(topic_folder):
    import os
    import subprocess
    import sys
    import time
    import urllib.request

    from fsi_common.app.testing import free_port

    port = free_port()
    env = {
        **os.environ,
        "APP_HOST": "127.0.0.1",
        "APP_PORT": str(port),
        "APP_TOPICS": str(topic_folder),
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    }
    process = subprocess.Popen([sys.executable, "-m", "fsi_common.app"], env=env)
    try:
        body = ""
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/about", timeout=1) as page:
                    body = page.read().decode()
                break
            except OSError:
                time.sleep(0.1)
        assert "Toy topic" in body
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_make_serve_leaves_the_host_to_the_default():
    makefile = (Path(__file__).resolve().parents[3] / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\nserve:\n", 1)[1].split("\n\n", 1)[0]
    assert "APP_HOST" not in recipe and "0.0.0.0" not in recipe
