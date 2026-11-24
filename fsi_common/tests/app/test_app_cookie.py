"""Two applications on two ports of one host keep their own sign-ins."""

from __future__ import annotations

import pytest
from app_toy_topic import make_toy_folder
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app
from fsi_common.app.config import ConfigError

DANA = {"name": "Dana Whitfield", "role": "Head of Compliance"}
SAM = {"name": "Sam Okoye", "role": "Compliance Officer"}


def _two_apps(tmp_path):
    """Two applications on two ports, whose clients share one cookie jar as a browser's tabs do."""
    first = _app(tmp_path, 4802, b"first")
    second = _app(tmp_path, 4803, b"second")
    second._cookies = (
        first.cookies
    )  # a browser keeps cookies by host, so the port does not part them
    return first, second


def _app(tmp_path, port, secret):
    folder = make_toy_folder(tmp_path / str(port))
    config = AppConfig(port=port, secret=secret, topic_folders=(folder,))
    return TestClient(create_app(config), follow_redirects=False)


def test_signing_in_on_one_port_does_not_sign_the_person_out_on_the_other(tmp_path):
    first, second = _two_apps(tmp_path)
    first.post("/signin", data=DANA)
    second.post("/signin", data=SAM)
    assert "Dana Whitfield, Head of Compliance" in first.get("/").text
    assert "Sam Okoye" not in first.get("/").text
    assert "Sam Okoye, Compliance Officer" in second.get("/").text
    assert "Dana Whitfield" not in second.get("/").text


def test_signing_out_on_one_port_leaves_the_other_signed_in(tmp_path):
    first, second = _two_apps(tmp_path)
    first.post("/signin", data=DANA)
    second.post("/signin", data=SAM)
    second.post("/signout")
    assert "Sam Okoye" not in second.get("/").text
    assert "Dana Whitfield, Head of Compliance" in first.get("/").text


def test_the_cookie_is_named_from_the_port_unless_a_setting_names_it():
    assert AppConfig(port=4802).cookie_name == "reviewer-4802"
    assert AppConfig(port=4803, cookie="desk").cookie_name == "desk"
    assert AppConfig.from_env({"APP_PORT": "4802"}).cookie_name == "reviewer-4802"
    assert AppConfig.from_env({"APP_COOKIE": "desk"}).cookie_name == "desk"
    assert AppConfig.from_env({}).cookie_name == "reviewer-4803"


@pytest.mark.parametrize("name", ["", "has space", "semi;colon", "équal=", "x" * 65])
def test_a_cookie_name_that_a_browser_would_refuse_is_refused_in_words(name):
    with pytest.raises(ConfigError, match="APP_COOKIE"):
        AppConfig.from_env({"APP_COOKIE": name})
