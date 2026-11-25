"""The manifest of a corpus: what each document is, where it came from, its digest and its terms."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from context.errors import ContextError

MANIFEST = "manifest.json"
FETCHED = "fetched"
"""The subfolder of a corpus that fetch-only documents go into when no setting names a folder."""

ALLOWED_EXTRAS = frozenset({MANIFEST, "README.md", ".gitignore"})
"""Files a corpus folder may hold beside its documents."""


class CorpusError(ContextError):
    """Base class of every error raised while reading or fetching a corpus."""


class CorpusNotFoundError(CorpusError):
    """There is no corpus folder by that name, or there is more than one."""


class CorpusManifestError(CorpusError):
    """The manifest is missing, is not JSON, or does not describe its documents completely."""


def _relative_file(value: str | None) -> str | None:
    if value is None:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"the file {value} leaves the corpus folder")
    if value in ALLOWED_EXTRAS or path.parts[0] == FETCHED:
        raise ValueError(f"the file {value} names a reserved place in the corpus folder")
    return value


class ManifestDocument(BaseModel):
    """One document of a corpus, as its manifest entry describes it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, pattern=r"^\S+$", description="The document's id in the corpus")
    title: str = Field(min_length=1, pattern=r"\S", description="The title the document gives")
    file: str = Field(min_length=1, description="The file name of the document")
    format: Literal["markdown", "pdf", "html", "text"]
    language: str = Field(pattern=r"^[a-z]{2}$", description="The language code, for example en")
    holding: Literal["committed", "fetch"] = Field(
        description="committed: the repository holds the file; fetch: it holds only this entry"
    )
    source: str = Field(min_length=1, pattern=r"\S", description="The address, or who wrote it")
    date: str = Field(description="The date written or fetched, as YYYY-MM-DD")
    date_kind: Literal["written", "fetched"]
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$", description="SHA-256 of the file's bytes")
    terms: str = Field(min_length=1, pattern=r"\S", description="The terms of reuse, as quoted")
    terms_address: str | None = Field(default=None, description="Where the terms are published")
    version: str | None = Field(default=None, description="The version or date the document gives")
    part: str | None = Field(default=None, description="The layer of the corpus it belongs to")
    text_file: str | None = Field(default=None, description="A text twin of a PDF or HTML file")
    text_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("date")
    @classmethod
    def _calendar_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @field_validator("file", "text_file")
    @classmethod
    def _inside_the_folder(cls, value: str | None) -> str | None:
        return _relative_file(value)

    @model_validator(mode="after")
    def _twin_complete(self) -> Self:
        if (self.text_file is None) != (self.text_digest is None):
            raise ValueError(f"{self.id} needs both text_file and text_digest, or neither")
        return self


class NamedDocument(BaseModel):
    """A document a corpus document names and that is not in the corpus, so it was not read."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, pattern=r"\S")
    named_in: str = Field(min_length=1, description="The id of the document that names it")
    status: Literal["not published", "published, not collected", "not collected"] = Field(
        default="not published",
        description="Whether it was published; the documents named here were not read either way",
    )


class InferredRelation(BaseModel):
    """A relation between two documents that no quote states and that is recorded as inferred."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relation: Literal["supersedes"]
    document: str = Field(min_length=1)
    other: str = Field(min_length=1)
    basis: str = Field(min_length=1, pattern=r"\S", description="Why the relation is inferred")


class Manifest(BaseModel):
    """A corpus's manifest: who it is about, whether we wrote it, and every document in it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    institution: str = Field(min_length=1, pattern=r"\S")
    origin: Literal["written", "published"]
    description: str = Field(min_length=1, pattern=r"\S")
    documents_setting: str | None = Field(
        default=None,
        pattern=r"^[A-Z][A-Z0-9_]*$",
        description="The environment setting that names the folder of the fetch-only documents",
    )
    benchmark: str | None = Field(
        default=None, description="Why the regulations are read for this institution as a benchmark"
    )
    named_not_read: list[NamedDocument] = Field(default_factory=list)
    inferred_relations: list[InferredRelation] = Field(default_factory=list)
    documents: list[ManifestDocument]

    @model_validator(mode="after")
    def _complete(self) -> Self:
        if not self.documents:
            raise ValueError("the manifest lists no document")
        listed = {
            "id": [d.id for d in self.documents],
            "file": [d.file for d in self.documents],
            "digest": [d.digest for d in self.documents],
        }
        for field, values in listed.items():
            repeated = sorted({v for v in values if values.count(v) > 1})
            if repeated:
                raise ValueError(f"the {field} {', '.join(repeated)} is listed twice")
        for document in self.documents:
            _check_origin(self.origin, document)
        ids = set(listed["id"])
        named = [n.named_in for n in self.named_not_read]
        related = [r.document for r in self.inferred_relations]
        related += [r.other for r in self.inferred_relations]
        unknown = sorted({i for i in named + related if i not in ids})
        if unknown:
            names = ", ".join(unknown)
            raise ValueError(f"the corpus records name {names}, which it does not list")
        if any(r.document == r.other for r in self.inferred_relations):
            raise ValueError("an inferred relation relates a document to itself")
        return self


def _check_origin(origin: str, document: ManifestDocument) -> None:
    if origin == "written":
        if document.holding != "committed" or document.date_kind != "written":
            raise ValueError(
                f"{document.id} is in a written corpus, so it is committed and its date is the "
                "date it was written"
            )
        return
    if not document.source.startswith("https://") or document.date_kind != "fetched":
        raise ValueError(
            f"{document.id} is published, so it needs its https address and the date it was fetched"
        )
    if document.holding == "committed" and not (document.terms_address or "").startswith(
        "https://"
    ):
        raise ValueError(
            f"{document.id} is published and committed, so its terms need the https address "
            "where they allow it"
        )


def load_manifest(folder: Path) -> Manifest:
    """Read and validate a corpus folder's manifest.

    Args:
        folder: The corpus folder.

    Returns:
        The manifest, validated.

    Raises:
        CorpusManifestError: If the manifest is missing, is not JSON, does not validate, or names
            another corpus. The message names the file and every field at fault.
    """
    path = folder / MANIFEST
    if not path.is_file():
        raise CorpusManifestError(f"The corpus folder {folder} has no {MANIFEST}.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusManifestError(f"{path} is not JSON: {exc.msg} at line {exc.lineno}.") from exc
    try:
        manifest = Manifest.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'manifest'}: {error['msg']}"
            for error in exc.errors()
        )
        raise CorpusManifestError(f"{path} does not describe its corpus: {problems}.") from exc
    if manifest.corpus != folder.name:
        raise CorpusManifestError(
            f"{path} names the corpus {manifest.corpus}, and its folder is {folder.name}."
        )
    return manifest
