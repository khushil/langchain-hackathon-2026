"""What a person types is shown as text on every page of the shell, never read as markup."""

from __future__ import annotations

import pytest
from app_toy_topic import make_toy_folder
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app

NAME = "<script>x</script> Dana"
ROLE = "<b>Head</b> of Compliance"
ESCAPED_NAME = "&lt;script&gt;x&lt;/script&gt; Dana"


@pytest.fixture()
def client(tmp_path):
    config = AppConfig(secret=b"test-secret", topic_folders=(make_toy_folder(tmp_path),))
    return TestClient(create_app(config), follow_redirects=False)


def test_the_name_and_role_a_person_types_are_escaped_in_the_header_on_every_page(client):
    client.post("/signin", data={"name": NAME, "role": ROLE})
    for path in ("/", "/about", "/signin", "/toy/", "/nowhere"):
        page = client.get(path)
        assert page.status_code in {200, 404}, path
        assert ESCAPED_NAME in page.text, path
        assert "<script>x" not in page.text and "<b>Head" not in page.text, path


def test_what_the_sign_in_form_gives_back_after_a_refusal_is_escaped(client):
    page = client.post("/signin", data={"name": '"><script>x</script>', "role": "  "})
    assert page.status_code == 422
    assert "<script>x" not in page.text
    assert "&lt;script&gt;x&lt;/script&gt;" in page.text
