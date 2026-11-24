"""The seven measures of a section summary, as plain functions and as LangSmith evaluators.

A summary is the JSON of the starter's section summary, or `{"sections": [...]}` for a document.
The reference is an example's `reference_outputs`. Nothing here calls a model or imports the engine.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fsi_common.evals.measures import Measure

from .matching import Labelled, Predicted, pair_obligations
from .normalise import is_word_for_word, normalise

MEASURE_KEYS = (
    "obligations_found",
    "invented_obligations",
    "quotes_word_for_word",
    "deadlines_as_written",
    "deadlines_matched",
    "paragraph_recall",
    "paragraph_precision",
)


class MalformedSummaryError(Exception):
    """A summary or a reference does not have the shape the measures read."""


@dataclass(frozen=True)
class Scene:
    """A summary read against its reference: the pairs made and the paragraphs in play."""

    predicted: list[Predicted]
    labelled: list[Labelled]
    pairs: dict[int, int]
    texts: Mapping[str, str]
    labelled_paragraphs: frozenset[str]


def _obligation(raw: Any) -> Predicted:
    if not isinstance(raw, Mapping):
        raise MalformedSummaryError(f"an obligation is {type(raw).__name__}, not an object")
    paragraph, evidence, deadline = raw.get("paragraph"), raw.get("evidence"), raw.get("deadline")
    if not isinstance(paragraph, str) or not isinstance(evidence, str):
        raise MalformedSummaryError("an obligation needs a paragraph and evidence, both text")
    if deadline is not None and not isinstance(deadline, str):
        raise MalformedSummaryError("an obligation's deadline must be text or null")
    return Predicted(paragraph.strip(), evidence, deadline)


def read_summary(summary: Any) -> list[Predicted]:
    """Read the predicted obligations of a section summary, or of every section of a document.

    Args:
        summary: A section summary, or an object with a list `sections` of them.

    Returns:
        The predicted obligations in order.

    Raises:
        MalformedSummaryError: If the shape is wrong.
    """
    if not isinstance(summary, Mapping):
        raise MalformedSummaryError(f"a summary is {type(summary).__name__}, not an object")
    if "sections" in summary:
        parts = summary["sections"]
        if not isinstance(parts, list):
            raise MalformedSummaryError("sections must be a list")
        return [p for part in parts for p in read_summary(part)]
    obligations = summary.get("obligations")
    if not isinstance(obligations, list):
        raise MalformedSummaryError("a summary needs a list of obligations")
    return [_obligation(raw) for raw in obligations]


def _scene(summary: Any, reference: Mapping[str, Any]) -> Scene:
    texts = reference.get("paragraph_texts")
    items = reference.get("items")
    if not isinstance(texts, Mapping) or not isinstance(items, list):
        raise MalformedSummaryError("the reference needs paragraph_texts and items")
    predicted = read_summary(summary)
    labelled = [
        Labelled(i["paragraph"], i["evidence"], i.get("deadline_as_written"))
        for i in items
        if i["kind"] == "obligation"
    ]
    return Scene(
        predicted,
        labelled,
        pair_obligations(predicted, labelled),
        texts,
        frozenset(label.paragraph for label in labelled),
    )


def _measure(key: str, numerator: int, denominator: int, population: str, **kwargs: Any) -> Measure:
    return Measure(key, numerator, denominator, population, **kwargs)


def _nonempty(text: str | None) -> bool:
    return bool(text) and bool(normalise(text or ""))


def _as_written(scene: Scene, item: Predicted, text: str | None) -> bool:
    return is_word_for_word(text or "", scene.texts.get(item.paragraph))


def _found(scene: Scene) -> Measure:
    return _measure(
        "obligations_found",
        len(set(scene.pairs.values())),
        len(scene.labelled),
        "labelled obligations in scope",
    )


def _invented(scene: Scene) -> Measure:
    invented = sum(
        1
        for index, item in enumerate(scene.predicted)
        if index not in scene.pairs and item.paragraph not in scene.labelled_paragraphs
    )
    return _measure(
        "invented_obligations",
        invented,
        len(scene.predicted),
        "predicted obligations",
        lower_is_better=True,
    )


def _quotes(scene: Scene) -> Measure:
    existing = [p for p in scene.predicted if p.paragraph in scene.texts]
    good = sum(1 for p in existing if _as_written(scene, p, p.evidence))
    return _measure(
        "quotes_word_for_word",
        good,
        len(existing),
        "predicted obligations citing a paragraph in scope",
    )


def _deadlines_as_written(scene: Scene) -> Measure:
    given = [p for p in scene.predicted if _nonempty(p.deadline)]
    good = sum(1 for p in given if _as_written(scene, p, p.deadline))
    return _measure(
        "deadlines_as_written", good, len(given), "predicted obligations with a deadline"
    )


def _deadlines_matched(scene: Scene) -> Measure:
    pairs = [
        (scene.predicted[p], scene.labelled[label])
        for p, label in sorted(scene.pairs.items())
        if _nonempty(scene.labelled[label].deadline)
    ]
    good = 0
    for item, label in pairs:
        if not _nonempty(item.deadline):
            continue
        said, wanted = normalise(item.deadline or ""), normalise(label.deadline or "")
        good += wanted in said or said in wanted
    return _measure(
        "deadlines_matched",
        good,
        len(pairs),
        "matched obligations whose labelled deadline is not empty",
    )


def _recall(scene: Scene) -> Measure:
    found = {p.paragraph for p in scene.predicted} & scene.labelled_paragraphs
    return _measure(
        "paragraph_recall",
        len(found),
        len(scene.labelled_paragraphs),
        "paragraphs holding a labelled obligation",
    )


def _precision(scene: Scene) -> Measure:
    cited = {p.paragraph for p in scene.predicted}
    return _measure(
        "paragraph_precision",
        len(cited & scene.labelled_paragraphs),
        len(cited),
        "paragraphs holding a predicted obligation",
    )


_MEASURES: dict[str, Callable[[Scene], Measure]] = {
    "obligations_found": _found,
    "invented_obligations": _invented,
    "quotes_word_for_word": _quotes,
    "deadlines_as_written": _deadlines_as_written,
    "deadlines_matched": _deadlines_matched,
    "paragraph_recall": _recall,
    "paragraph_precision": _precision,
}


def score_summary(summary: Any, reference: Mapping[str, Any]) -> list[Measure]:
    """Score a summary on all seven measures.

    Args:
        summary: A section summary as JSON, or `{"sections": [...]}` for a document.
        reference: An example's `reference_outputs`.

    Returns:
        The seven measures, in `MEASURE_KEYS` order.

    Raises:
        MalformedSummaryError: If the summary or the reference has the wrong shape.
    """
    scene = _scene(summary, reference)
    return [_MEASURES[key](scene) for key in MEASURE_KEYS]


def evaluate_pair(example: Mapping[str, Any], output: Any) -> list[Measure]:
    """Score an output against an example, in the shape the runner expects.

    Args:
        example: A dataset example with `reference_outputs`.
        output: The summary to score.

    Returns:
        The seven measures.
    """
    return score_summary(output, example["reference_outputs"])


def _langsmith_evaluator(key: str) -> Callable[[dict, dict], dict]:
    def evaluate(outputs: dict, reference_outputs: dict) -> dict:
        scored = {m.key: m for m in score_summary(outputs, reference_outputs)}[key]
        comment = scored.line().removeprefix(f"{key}: ")
        return {"key": key, "score": scored.score, "comment": comment}

    evaluate.__name__ = key
    evaluate.__qualname__ = key
    evaluate.__doc__ = f"The {key} measure as a LangSmith evaluator."
    return evaluate


def langsmith_evaluators() -> list[Callable[[dict, dict], dict]]:
    """The seven measures as LangSmith evaluators, taking the outputs and the reference outputs.

    Returns:
        One function per measure, named after it. A measure with nothing in scope has no score
        and says so in its comment.
    """
    return [_langsmith_evaluator(key) for key in MEASURE_KEYS]
