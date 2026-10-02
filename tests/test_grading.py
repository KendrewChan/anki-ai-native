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
    assert r == {"per_question": [], "verdict": "partial", "ease": 2, "feedback": "f", "missed": ["a", "b"]}


def test_parse_grade_per_question_normalised():
    r = grading.parse_grade('{"verdict":"partial","per_question":[{"verdict":"Correct","note":" ok "},{"verdict":"??"},"junk"]}')
    assert r["per_question"] == [{"verdict": "correct", "note": "ok"}, {"verdict": "partial", "note": ""}]


def test_parse_grade_clamps_and_defaults_ease():
    assert grading.parse_grade('{"verdict":"correct","ease":9}')["ease"] == 4
    assert grading.parse_grade('{"verdict":"wrong"}')["ease"] == 1


@pytest.mark.parametrize("reply", ["no json here", '{"verdict":"meh","ease":1}', "[1,2]"])
def test_parse_grade_rejects_bad_replies(reply):
    with pytest.raises(ValueError):
        grading.parse_grade(reply)


def test_parse_questions_list_capped_and_cleaned():
    r = grading.parse_questions('{"questions":[" a ","","b","c","d","e"]}')
    assert r == {"questions": ["a", "b", "c", "d"]}


def test_parse_questions_accepts_single_question_key():
    assert grading.parse_questions('{"question":" Why? "}') == {"questions": ["Why?"]}


@pytest.mark.parametrize("reply", ['{"questions":[]}', '{"questions":[""]}', '{"other":1}'])
def test_parse_questions_rejects_empty(reply):
    with pytest.raises(ValueError):
        grading.parse_questions(reply)


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


def test_grade_prompt_pairs_each_answer_with_its_question():
    p = grading.grade_prompt("Card Q", ["First?", "Second?"], "Ref", ["one", ""])
    assert "Q1: First?\nUser's answer 1: one" in p
    assert "Q2: Second?\nUser's answer 2: (blank)" in p
    assert "Card Q" in p and "Ref" in p


def test_grade_prompt_without_rewrite_uses_card_question():
    p = grading.grade_prompt("Card Q", [], "Ref", ["mine"])
    assert "Q1: Card Q\nUser's answer 1: mine" in p


def test_grade_prompt_folds_extra_answers_into_last():
    p = grading.grade_prompt("Card Q", ["Only?"], "Ref", ["a", "b"])
    assert "User's answer 1: a\nb" in p


def test_question_html_show_original_on_top_then_box():
    html = ui.question_html("<b>orig</b>", rewrite=True)
    assert html.index('id="ai-orig"') < html.index('class="ai-q loading"') < html.index('class="ai-ans"')


def test_question_html_cloze_has_no_rewrite():
    html = ui.question_html("<b>orig</b>", rewrite=False)
    assert 'ai-q loading' not in html and "<b>orig</b>" in html and 'class="ai-ans"' in html


def test_verdict_html_escapes_user_answer():
    v = {"verdict": "wrong", "ease": 1, "feedback": "x", "missed": [], "per_question": []}
    html = ui.verdict_html(v, [], ["<script>"])
    assert "&lt;script&gt;" in html and "Missed:</b> nothing" in html


def test_verdict_html_per_question_rows():
    v = {"verdict": "partial", "ease": 2, "feedback": "f", "missed": ["m"],
         "per_question": [{"verdict": "correct", "note": "n1"}, {"verdict": "wrong", "note": "n2"}]}
    html = ui.verdict_html(v, ["Q one", "Q two"], ["a1", ""])
    assert "✓ Q one" in html and "✗ Q two" in html and "(blank)" in html and "<li>m</li>" in html
