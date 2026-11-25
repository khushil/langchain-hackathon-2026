"""Tests of the two agents an experiment runs, on scripted models: no live call, no LangSmith."""

import re
from typing import Any

import pytest
from engine_fakes import (
    DOCUMENT,
    ScriptedModels,
    default_summary,
    empty_second_read,
    obliging_second_read,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from evals.build_dataset import read_examples
from evals.evaluators import score_summary
from evals.experiment_targets import (
    SectionTextDiffersError,
    document_target,
    engine_section_target,
    starter_section_target,
)
from sub_agent import INSTRUCTIONS, SectionSummary


class ToolCallingModel(BaseChatModel):
    """A chat model that answers with a tool call that holds the scripted summary of a section."""

    seen: list[Any] = []
    bound: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "tool-calling-fake"

    def bind_tools(self, tools, **kwargs):
        self.bound.extend(getattr(t, "name", None) or t["name"] for t in tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        number = re.match(r"Section (\S+):", messages[-1].content).group(1)
        summary = default_summary(DOCUMENT.section(number))
        call = {"name": "SectionSummary", "args": summary.model_dump(), "id": f"call-{number}"}
        message = AIMessage(content="", tool_calls=[call])
        return ChatResult(generations=[ChatGeneration(message=message)])


SECTIONS = read_examples("sections.jsonl")
DOCUMENT_EXAMPLE = read_examples("documents.jsonl")[0]


def numbers(output: dict) -> list[str]:
    return [o["paragraph"] for o in output["obligations"]]


def test_the_starters_agent_returns_a_section_summary_for_each_of_the_ten_sections():
    model = ToolCallingModel(seen=[], bound=[])
    target = starter_section_target(lambda role: model)
    outputs = [target(example["inputs"]) for example in SECTIONS]
    assert [o["number"] for o in outputs] == [str(n) for n in range(1, 11)]
    assert all(SectionSummary.model_validate(o) for o in outputs)
    assert len(model.seen) == 10


def test_the_starters_agent_is_the_notebooks_deep_agent_given_the_notebooks_task():
    model, roles = ToolCallingModel(seen=[], bound=[]), []

    def models(role):
        roles.append(role)
        return model

    starter_section_target(models)(SECTIONS[6]["inputs"])
    assert roles == ["section"]
    (messages,) = model.seen
    assert INSTRUCTIONS in str(messages[0].content)
    section = DOCUMENT.section("7")
    assert messages[-1].content == f"Section 7: {section.title}\n\n{section.text}"


def test_the_deep_agents_own_tools_are_part_of_the_starters_agent():
    model = ToolCallingModel(seen=[], bound=[])
    starter_section_target(lambda role: model)(SECTIONS[6]["inputs"])
    assert {"task", "ls", "read_file", "write_file", "SectionSummary"} <= set(model.bound)


def test_the_engines_agent_asks_for_the_section_in_the_engines_own_words():
    models = ScriptedModels()
    engine_section_target(models)(SECTIONS[6]["inputs"])
    (_, first), *_ = models.calls
    assert first == "Number: 7"


def test_the_starters_agent_keeps_every_obligation_the_model_returned():
    target = starter_section_target(lambda role: ToolCallingModel(seen=[], bound=[]))
    output = target(SECTIONS[6]["inputs"])
    expected = default_summary(DOCUMENT.section("7")).model_dump()
    assert output == expected


def test_the_engines_agent_returns_a_section_summary_for_each_of_the_ten_sections():
    target = engine_section_target(ScriptedModels())
    outputs = [target(example["inputs"]) for example in SECTIONS]
    assert [o["number"] for o in outputs] == [str(n) for n in range(1, 11)]
    assert all(SectionSummary.model_validate(o) for o in outputs)
    assert sum(len(o["obligations"]) for o in outputs) == sum(
        len(default_summary(s).obligations) for s in DOCUMENT.sections
    )


def test_the_engines_agent_leaves_out_an_obligation_whose_quote_failed_its_check():
    def one_paraphrase(section):
        base = default_summary(section)
        if section.number != "7":
            return base
        bad = base.obligations[0].model_copy(update={"evidence": "Firms ought to say so soon"})
        return base.model_copy(update={"obligations": [bad, *base.obligations[1:]]})

    target = engine_section_target(ScriptedModels(section=one_paraphrase))
    output = target(SECTIONS[6]["inputs"])
    kept = default_summary(DOCUMENT.section("7")).obligations[1:]
    assert [o["paragraph"] for o in output["obligations"]] == [o.paragraph for o in kept]
    assert all(o["evidence"] != "Firms ought to say so soon" for o in output["obligations"])


def test_the_engines_agent_includes_what_a_second_read_gave_for_a_marked_paragraph():
    def missing_9_3(section):
        base = default_summary(section)
        kept = [o for o in base.obligations if o.paragraph != "9.3"]
        return base.model_copy(update={"obligations": kept})

    models = ScriptedModels(section=missing_9_3, paragraph=obliging_second_read)
    output = engine_section_target(models)(SECTIONS[8]["inputs"])
    assert models.rereads == ["9.3"]
    assert "9.3" in numbers(output)


def test_the_engines_agent_leaves_out_a_paragraph_whose_second_read_found_nothing():
    def missing_9_3(section):
        base = default_summary(section)
        kept = [o for o in base.obligations if o.paragraph != "9.3"]
        return base.model_copy(update={"obligations": kept})

    models = ScriptedModels(section=missing_9_3, paragraph=empty_second_read)
    output = engine_section_target(models)(SECTIONS[8]["inputs"])
    assert models.rereads == ["9.3"]
    assert "9.3" not in numbers(output)


def test_the_engines_agent_leaves_out_a_second_reads_quote_that_failed_its_check():
    def missing_9_3(section):
        base = default_summary(section)
        kept = [o for o in base.obligations if o.paragraph != "9.3"]
        return base.model_copy(update={"obligations": kept})

    def paraphrased(section, number):
        read = obliging_second_read(section, number)
        bad = read.obligations[0].model_copy(update={"evidence": "Firms ought to say so soon"})
        return read.model_copy(update={"obligations": [bad]})

    models = ScriptedModels(section=missing_9_3, paragraph=paraphrased)
    output = engine_section_target(models)(SECTIONS[8]["inputs"])
    assert "9.3" not in numbers(output)


def test_the_document_agent_returns_every_section_in_order_in_the_shape_the_measures_read():
    target = document_target(engine_section_target(ScriptedModels()))
    output = target(DOCUMENT_EXAMPLE["inputs"])
    assert [s["number"] for s in output["sections"]] == [str(n) for n in range(1, 11)]
    measures = {m.key: m for m in score_summary(output, DOCUMENT_EXAMPLE["reference_outputs"])}
    assert measures["obligations_found"].denominator == 39


def test_a_section_whose_text_differs_from_the_librarys_is_refused_by_name():
    inputs = {**SECTIONS[6]["inputs"], "section": {**SECTIONS[6]["inputs"]["section"]}}
    inputs["section"]["text"] += "\n\n7.99 A new paragraph."
    with pytest.raises(SectionTextDiffersError, match="section 7 of PS26-4"):
        engine_section_target(ScriptedModels())(inputs)


def test_a_document_the_library_does_not_hold_fails_in_words():
    from context.errors import DocumentNotFoundError

    inputs = {**SECTIONS[0]["inputs"], "document_id": "PS99-9"}
    with pytest.raises(DocumentNotFoundError, match="PS99-9"):
        engine_section_target(ScriptedModels())(inputs)


def test_the_deep_agent_is_built_as_the_notebooks_step_two_builds_it(monkeypatch):
    import deepagents

    built, original = [], deepagents.create_deep_agent

    def spy(**kwargs):
        built.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(deepagents, "create_deep_agent", spy)
    model = ToolCallingModel(seen=[], bound=[])
    starter_section_target(lambda role: model)
    (kwargs,) = built
    assert set(kwargs) == {"model", "system_prompt", "response_format"}
    assert kwargs["model"] is model
    assert kwargs["system_prompt"] == INSTRUCTIONS
    assert kwargs["response_format"] is SectionSummary
