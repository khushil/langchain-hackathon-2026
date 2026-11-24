"""What stopped a page is said in words: its own reason, or that nothing is at the address."""

from __future__ import annotations

import pytest
from app_toy_topic import make_toy_folder
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app


@pytest.fixture()
def client(tmp_path):
    config = AppConfig(secret=b"test-secret", topic_folders=(make_toy_folder(tmp_path),))
    return TestClient(create_app(config), follow_redirects=False)


def test_a_page_that_gives_a_reason_for_a_missing_thing_says_it(client):
    page = client.get("/toy/gone")
    assert page.status_code == 404
    assert "There is no thing numbered 7." in page.text
    assert "There is nothing at this address." not in page.text


def test_an_address_the_application_does_not_have_gets_the_standard_words(client):
    page = client.get("/toy/nowhere")
    assert page.status_code == 404
    assert "There is nothing at this address." in page.text
