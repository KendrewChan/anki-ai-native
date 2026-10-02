import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "anki-ai"))

from addon import grading  # noqa: E402
from addon import ui  # noqa: E402


def test_strip_html_drops_style_script_tags_and_entities():
    html = "<style>.card{x:1}</style><div>Kafka&nbsp;ordering</div><script>alert(1)</script><br>by key &amp; partition"
    assert grading.strip_html(html) == "Kafka ordering\nby key & partition"


def test_answer_only_keeps_text_after_answer_hr():
    assert grading.answer_only("Q<hr id=answer>A") == "A"
    assert grading.answer_only("no divider") == "no divider"


def test_parse_grade_from_fenced_reply():
    r = grading.parse_grade('```json\n{"verdict":"Partial","ease":"2","feedback":" f ","missed":["a",""," b "]}\n```')
    assert r == {"verdict": "partial", "ease": 2, "feedback": "f", "missed": ["a", "b"]}


def test_parse_grade_clamps_and_defaults_ease():
    assert grading.parse_grade('{"verdict":"correct","ease":9}')["ease"] == 4
    assert grading.parse_grade('{"verdict":"wrong"}')["ease"] == 1


@pytest.mark.parametrize("reply", ["no json here", '{"verdict":"meh","ease":1}', "[1,2]"])
def test_parse_grade_rejects_bad_replies(reply):
    with pytest.raises(ValueError):
        grading.parse_grade(reply)


def test_parse_question():
    assert grading.parse_question('{"question":" Why? "}') == {"question": "Why?"}
    with pytest.raises(ValueError):
        grading.parse_question('{"question":""}')


def test_missed_html_escapes():
    assert grading.missed_html(["a<b"], "2026-10-02") == "<hr><b>Missed (2026-10-02)</b><ul><li>a&lt;b</li></ul>"


@pytest.mark.parametrize("fields,expected", [
    (["Front", "Back"], "Back"),
    (["Text", "Back Extra"], "Back Extra"),
    (["Term", "Definition", "Example"], "Example"),
    ([], None),
])
def test_pick_missed_field(fields, expected):
    assert grading.pick_missed_field(fields) == expected


def test_grade_prompt_includes_card_and_answer():
    p = grading.grade_prompt("Q", "Sharp?", "A", "mine")
    assert "Q" in p and "Sharp?" in p and "A" in p and "mine" in p


def test_question_html_cloze_has_no_rewrite():
    assert 'id="ai-q"' in ui.question_html("<b>orig</b>", rewrite=True)
    html = ui.question_html("<b>orig</b>", rewrite=False)
    assert 'id="ai-q"' not in html and "<b>orig</b>" in html


def test_verdict_html_escapes_user_answer():
    v = {"verdict": "wrong", "ease": 1, "feedback": "x", "missed": []}
    html = ui.verdict_html(v, "<script>")
    assert "&lt;script&gt;" in html and "Missed:</b> nothing" in html
