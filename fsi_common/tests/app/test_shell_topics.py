"""Two topics behind one address, each in its own process, served by a shell run as a process."""

from __future__ import annotations

import http.client
import json
import time

import httpx
import pytest
from app_probe_topic import make_probe_topic
from app_shell_support import (
    command_line,
    listening,
    running_shell,
)

from fsi_common.app.session import SessionCodec
from fsi_common.records import Person

SIGNING_TEXT = "probe-signing-8f3a1c"


@pytest.fixture(scope="module")
def shell(tmp_path_factory):
    """One shell over two probe topics whose ``utils`` packages differ, seeded with the second."""
    root = tmp_path_factory.mktemp("shell")
    first = make_probe_topic(
        root, "01_alpha_agent", name="alpha", value="alpha-value", waiting="3", noun="case"
    )
    second = make_probe_topic(
        root, "02_beta_agent", name="beta", value="beta-value", waiting="2", noun="alert"
    )
    with running_shell(
        root, [first, second], secret=SIGNING_TEXT, extra_env={"APP_SEED": "beta"}
    ) as run:
        run.folders = (first, second)
        yield run


@pytest.fixture()
def client(shell):
    with shell.client() as http:
        yield http


def test_each_topic_runs_on_its_own_utils_package_behind_one_address(client):
    assert "Value is alpha-value." in client.get("/alpha/").text
    assert "Value is beta-value." in client.get("/beta/").text


def test_a_topics_process_has_only_its_own_folder_and_the_shared_package_on_its_path(client):
    for name, own, other in (
        ("alpha", "01_alpha_agent", "02_beta_agent"),
        ("beta", "02_beta_agent", "01_alpha_agent"),
    ):
        paths = client.get(f"/{name}/syspath").json()["path"]
        assert any(p.endswith(f"/{own}") for p in paths)
        assert not any(other in p for p in paths)
        assert sum(p.endswith("fsi_common") for p in paths) == 1


def test_the_shell_starts_one_child_for_each_topic_and_each_listens_only_on_loopback(shell):
    kids = shell.children()
    assert len(kids) == 2
    for pid in kids:
        sockets = listening(pid)
        assert len(sockets) == 1 and sockets[0].startswith("127.0.0.1:"), sockets
    assert f"127.0.0.1:{shell.port}" in listening(shell.pid)
    assert {s for pid in kids for s in listening(pid)}.isdisjoint(listening(shell.pid))


def test_the_signing_secret_is_in_no_command_line_and_no_log_and_no_state_file(shell):
    secrets = (SIGNING_TEXT, SIGNING_TEXT.encode().hex())
    assert len(shell.children()) == 2
    for pid in [shell.pid, *shell.children()]:
        assert not any(s in command_line(pid) for s in secrets), command_line(pid)
    assert not any(s in shell.log.read_text(errors="replace") for s in secrets)
    for path in shell.state_dir.rglob("*"):
        if path.is_file():
            assert not any(s in path.read_text(errors="replace") for s in secrets), path


def test_a_sign_in_at_the_shell_is_accepted_by_every_topic(client):
    done = client.post("/signin", data={"name": "Dana Whitfield", "role": "Head of Compliance"})
    assert done.status_code == 303
    for path in ("/", "/alpha/", "/beta/"):
        assert "Dana Whitfield, Head of Compliance" in client.get(path).text, path
    client.post("/signout")
    assert "Dana Whitfield" not in client.get("/beta/").text


def test_a_cookie_signed_with_another_secret_signs_nobody_in_at_any_topic(shell, client):
    person = Person(name="Dana Whitfield", role="Head of Compliance")
    ours = SessionCodec(SIGNING_TEXT.encode().hex().encode("ascii"))
    client.cookies.set(f"reviewer-{shell.port}", ours.encode(person))
    assert "Dana Whitfield" in client.get("/alpha/").text, "the control cookie must sign her in"
    client.cookies.set(f"reviewer-{shell.port}", SessionCodec(b"another").encode(person))
    for path in ("/alpha/", "/beta/", "/"):
        assert "Dana Whitfield" not in client.get(path).text, path


def test_the_home_page_counts_what_waits_in_every_topic_and_links_each_list(client):
    page = client.get("/").text
    assert "3 cases and 2 alerts are waiting for a reviewer." in page
    assert page.count('data-hook="tile"') == 2
    assert 'href="/alpha/"' in page and 'href="/beta/"' in page


def test_every_topics_header_lists_every_topic(client):
    for path in ("/alpha/", "/beta/", "/alpha/gone"):
        page = client.get(path).text
        assert 'href="/alpha/"' in page and 'href="/beta/"' in page, path
    assert 'aria-current="page"' in client.get("/beta/").text


def test_about_holds_the_paragraphs_of_every_topic(client):
    page = client.get("/about").text
    assert "About the alpha probe." in page and "About the beta probe." in page


def test_a_request_passes_whole_with_its_method_path_query_form_and_cookies(client):
    client.cookies.set("c1", "v1")
    got = client.get("/alpha/echo?x=1&y=two%20words").json()
    assert got["method"] == "GET" and got["path"] == "/alpha/echo"
    assert got["query"] == "x=1&y=two%20words"
    assert "c1=v1" in got["cookie"]
    posted = client.post("/beta/echo?q=1", data={"name": "Dana", "note": "a b&c"}).json()
    assert posted["method"] == "POST" and posted["query"] == "q=1"
    assert posted["form"] == {"name": "Dana", "note": "a b&c"}


def test_a_redirect_reaches_the_person_as_the_topic_sent_it(client):
    sent = client.get("/alpha/redirect")
    assert sent.status_code == 303
    assert sent.headers["location"] == "/alpha/echo?x=1"
    assert client.get("/alpha/redirect", follow_redirects=True).json()["query"] == "x=1"


def test_a_topic_that_sets_two_cookies_sets_both(client):
    assert len(client.get("/alpha/cookies").headers.get_list("set-cookie")) == 2


def test_a_csv_download_streams_and_keeps_its_headers(client):
    started = time.monotonic()
    with client.stream("GET", "/beta/csv") as response:
        assert response.headers["content-type"].startswith("text/csv")
        assert response.headers["content-disposition"] == 'attachment; filename="probe.csv"'
        chunks = []
        for chunk in response.iter_raw():
            chunks.append((time.monotonic() - started, chunk))
    assert b"".join(c for _, c in chunks) == b"row,0\r\nrow,1\r\nrow,2\r\n"
    assert chunks[0][0] < chunks[-1][0] - 0.3, "the first row arrived with the last"


def test_a_head_request_gets_the_headers_and_no_body(client):
    response = client.head("/alpha/")
    assert response.status_code == 200 and response.content == b""


def test_a_topics_own_error_pages_reach_the_person_unchanged(client):
    gone = client.get("/alpha/gone")
    assert gone.status_code == 404
    assert "There is no thing numbered 7." in gone.text
    boom = client.get("/beta/boom")
    assert boom.status_code == 500 and "the probe broke" not in boom.text


def test_a_topics_static_file_and_the_shared_one_are_served(client):
    assert client.get("/alpha/static/toy.css").text.startswith("body")
    assert client.get("/static/app.css").status_code == 200


def test_an_address_under_no_topic_is_the_shells_own_not_found_page(client):
    for path in ("/gamma/", "/alphabet/", "/_shell/topic"):
        page = client.get(path)
        assert page.status_code == 404, path
        assert "There is nothing at this address." in page.text


def test_each_topic_keeps_its_state_in_a_folder_named_for_its_own_folder(shell, client):
    for name, folder in (("alpha", "01_alpha_agent"), ("beta", "02_beta_agent")):
        kept = client.get(f"/{name}/state").json()["folder"]
        assert kept == str(shell.state_dir / folder)
        assert (shell.state_dir / folder / "marker.txt").read_text() == name


def test_the_seed_is_made_in_the_topic_it_names_and_in_no_other(client):
    assert client.get("/beta/state").json()["seeded"] is True
    assert client.get("/alpha/state").json()["seeded"] is False


def test_the_internal_route_is_not_open_on_the_public_port(shell):
    with httpx.Client(base_url=shell.url) as http:
        assert http.get("/_shell/topic").status_code == 404
    names = {}
    for pid in shell.children():
        info = json.loads(httpx.get(f"http://{listening(pid)[0]}/_shell/topic").text)
        names[info["name"]] = info["waiting"]
    assert names == {"alpha": 3, "beta": 2}


@pytest.mark.parametrize(
    "path",
    [
        "/alpha/../_shell/topic",
        "/alpha/%2e%2e/_shell/topic",
        "/alpha/%2E%2E/_shell/topic",
        "/alpha/..%2f_shell/topic",
        "/alpha/./echo",
        "/alpha/%2e/echo",
        "/alpha/x/../../_shell/topic",
    ],
)
def test_a_path_with_dot_segments_never_reaches_an_internal_route_or_another_page(shell, path):
    connection = http.client.HTTPConnection("127.0.0.1", shell.port, timeout=30)
    try:
        connection.request("GET", path)
        answer = connection.getresponse()
        body = answer.read().decode()
    finally:
        connection.close()
    assert answer.status == 404, path
    assert "There is nothing at this address." in body
    assert '"waiting"' not in body


def test_an_answer_carries_one_date_and_one_server_header_not_the_topics_and_the_shells(client):
    headers = client.get("/alpha/").headers
    assert len(headers.get_list("date")) == 1
    assert len(headers.get_list("server")) == 1


def test_a_streamed_answer_carries_one_transfer_encoding_header(client):
    with client.stream("GET", "/beta/csv") as response:
        assert len(response.headers.get_list("transfer-encoding")) == 1
        response.read()
