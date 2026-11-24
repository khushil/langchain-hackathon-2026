"""Sign-in by typed name and role, kept in a signed cookie."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json

from pydantic import ValidationError
from starlette.requests import Request

from fsi_common.records import Person

SIGN_IN_PROBLEMS = {
    "person.empty": "Type your name and the role you act in.",
}


class SignInError(ValueError):
    """The typed name or role cannot be a person's."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SessionCodec:
    """Writes and reads the signed value that says who is signed in."""

    def __init__(self, secret: bytes) -> None:
        self._secret = secret

    def _sign(self, payload: str) -> str:
        return _b64(hmac.new(self._secret, payload.encode("ascii"), hashlib.sha256).digest())

    def encode(self, person: Person) -> str:
        """Return the cookie value for a person.

        Args:
            person: Who signed in.

        Returns:
            The value: their name and role, then a signature of both.
        """
        payload = _b64(json.dumps({"name": person.name, "role": person.role}).encode("utf-8"))
        return f"{payload}.{self._sign(payload)}"

    def decode(self, value: str | None) -> Person | None:
        """Read a cookie value.

        Args:
            value: The cookie's value, or None when there is no cookie.

        Returns:
            The person, or None when the value is absent, altered or signed with another secret.
        """
        if not value or value.count(".") != 1:
            return None
        payload, signature = value.split(".")
        if not hmac.compare_digest(signature, self._sign(payload)):
            return None
        try:
            data = json.loads(_unb64(payload))
            return Person(name=data["name"], role=data["role"])
        except (binascii.Error, ValueError, KeyError, TypeError, ValidationError):
            return None


def make_person(name: str, role: str) -> Person:
    """Make the person who signs in from what they typed.

    Args:
        name: The typed name.
        role: The typed role.

    Returns:
        The person.

    Raises:
        SignInError: If either is empty or names a model, a program or a service; the message
            says so in words.
    """
    try:
        return Person(name=name.strip(), role=role.strip())
    except ValidationError as exc:
        error = exc.errors()[0]
        raise SignInError(SIGN_IN_PROBLEMS.get(error["type"], _sentence(error["msg"]))) from exc


def _sentence(message: str) -> str:
    return message[:1].upper() + message[1:] + ("" if message.endswith(".") else ".")


def current_person(request: Request) -> Person | None:
    """Return the person signed in on a request.

    Args:
        request: The request.

    Returns:
        The person, or None when nobody is signed in.
    """
    return request.app.state.sessions.decode(request.cookies.get(request.app.state.cookie_name))


def safe_next(target: str | None) -> str:
    """Return where to go after signing in, refusing any address outside this application.

    Args:
        target: The requested address.

    Returns:
        The address when it is a path on this site, otherwise ``/``.
    """
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"
