"""What the cassette fallback tolerates, and what it still refuses.

The fallback exists so prompt wording can move without a paid re-record. The line
it must hold is *shape*: a structured call's output contract is the thing replay
protects, so a reworded instruction has to replay while a changed contract has to
miss. These tests pin both sides of that line.
"""
import pytest

from interview_bot.llm.transport import (
    _descriptions,
    _prompt_text,
    _replay_identity,
    _shape_only,
)


def _score_request(*, system="Score the answer.", critique_desc="Write a critique.", extra=None):
    props = {
        "critique": {"type": "string", "description": critique_desc},
        "dimensions": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "depth_accuracy": {
                    "type": "integer",
                    "enum": [0, 1, 2],
                    "description": "Technical correctness and substance.",
                }
            },
            "required": ["depth_accuracy"],
        },
    }
    if extra:
        props["dimensions"]["properties"].update(extra)
        props["dimensions"]["required"] = sorted(props["dimensions"]["properties"])
    return {
        "kind": "llm.generate_structured",
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "system": system,
        "cache_prefix": None,
        "messages": [{"role": "user", "content": "answer"}],
        "schema": {"type": "json_schema", "schema": {"type": "object", "properties": props}},
        "temperature": 0.0,
        "max_tokens": 512,
    }


# --- prose moves freely -----------------------------------------------------

def test_rewording_the_system_prompt_keeps_the_same_identity():
    a = _score_request()
    b = _score_request(system="Score the candidate's answer honestly.")
    assert _replay_identity(a) == _replay_identity(b)


def test_rewording_a_schema_description_keeps_the_same_identity():
    # A Pydantic extraction model's docstring lands here — it is prompt text that
    # happens to travel inside the schema.
    a = _score_request()
    b = _score_request(critique_desc="Name the exact gaps before scoring. Under 40 words.")
    assert _replay_identity(a) == _replay_identity(b)


# --- shape does not ---------------------------------------------------------

def test_adding_a_dimension_changes_the_identity():
    a = _score_request()
    b = _score_request(extra={"communication": {"type": "integer", "enum": [0, 1, 2]}})
    assert _replay_identity(a) != _replay_identity(b)


def test_widening_an_enum_changes_the_identity():
    a = _score_request()
    b = _score_request()
    b["schema"]["schema"]["properties"]["dimensions"]["properties"]["depth_accuracy"]["enum"] = [
        0, 1, 2, 3
    ]
    assert _replay_identity(a) != _replay_identity(b)


def test_changing_the_model_changes_the_identity():
    # Not prompt text: a different model is a different system under test.
    a = _score_request()
    b = _score_request()
    b["model"] = "claude-sonnet-5"
    assert _replay_identity(a) != _replay_identity(b)


# --- the helpers ------------------------------------------------------------

def test_shape_only_strips_descriptions_at_every_depth():
    stripped = _shape_only(_score_request()["schema"])
    assert "description" not in repr(stripped)
    # …and keeps everything that defines the contract.
    dims = stripped["schema"]["properties"]["dimensions"]
    assert dims["required"] == ["depth_accuracy"]
    assert dims["properties"]["depth_accuracy"]["enum"] == [0, 1, 2]
    assert dims["additionalProperties"] is False


def test_shape_only_leaves_non_schema_values_alone():
    assert _shape_only([1, "two", None]) == [1, "two", None]
    assert _shape_only({"enum": ["a"]}) == {"enum": ["a"]}


def test_prompt_text_carries_schema_descriptions():
    # Ranking candidates by prompt similarity is useless if the only text that
    # moved is invisible to the comparison.
    a = _prompt_text(_score_request())
    b = _prompt_text(_score_request(critique_desc="Something else entirely."))
    assert a != b
    assert "Write a critique." in a


def test_descriptions_are_collected_from_nested_schemas():
    found = _descriptions(_score_request()["schema"])
    assert "Write a critique." in found
    assert "Technical correctness and substance." in found


@pytest.mark.parametrize("value", [{}, [], "x", 3, None])
def test_descriptions_of_a_schemaless_value_is_empty(value):
    assert _descriptions(value) == []
