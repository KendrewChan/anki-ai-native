import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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
    assert r["per_question"] == [{"verdict": "correct", "note": "ok", "parts": []},
                                 {"verdict": "partial", "note": "", "parts": []}]


def test_parse_grade_parts_cleaned():
    r = grading.parse_grade('{"verdict":"partial","per_question":[{"verdict":"partial","parts":'
                            '[{"text":" a b ","verdict":"Correct"},{"text":"","verdict":"wrong"},{"text":"c","verdict":"?"},"x"]}]}')
    assert r["per_question"][0]["parts"] == [{"text": "a b", "verdict": "correct", "why": ""}]
    assert "parts" in grading.SYSTEM_PROMPT


def test_parse_grade_clamps_and_defaults_ease():
    assert grading.parse_grade('{"verdict":"correct","ease":9}')["ease"] == 4
    assert grading.parse_grade('{"verdict":"wrong"}')["ease"] == 1


@pytest.mark.parametrize("reply", ["no json here", '{"verdict":"meh","ease":1}', "[1,2]"])
def test_parse_grade_rejects_bad_replies(reply):
    with pytest.raises(ValueError):
        grading.parse_grade(reply)


def test_parse_questions_list_capped_and_cleaned():
    r = grading.parse_questions('{"questions":[" a ","","b","c","d","e","f","g","h","i"]}')
    assert r["questions"] == ["a", "b", "c", "d", "e", "f", "g", "h"] and r["show_original"] is False
    assert [(it["num"], it["text"], it["hint"], it["parts"]) for it in r["items"]][:2] == [("1.", "a", "", []), ("2.", "b", "", [])]


def test_parse_questions_hints_aligned_to_questions():
    r = grading.parse_questions('{"questions":["a","b"],"hints":[" think X ","y","extra"]}')
    assert [it["hint"] for it in r["items"]] == ["think X", "y"]
    assert [it["hint"] for it in grading.parse_questions('{"questions":["a","b"],"hints":["h"]}')["items"]] == ["h", ""]
    assert "hints" in grading.SYSTEM_PROMPT and '"parts"' in grading.SYSTEM_PROMPT


def test_parse_questions_parts_numbered_with_hint_per_part():
    r = grading.parse_questions('{"questions":["Why A?",{"question":"Describe B:","parts":["x"," ","y"]}],'
                                '"hints":["ha",["hx","hy"]]}')
    assert r["questions"] == ["Why A?", "Describe B:\n2.1 x\n2.2 y"]
    b = r["items"][1]
    assert b["num"] == "2." and b["hint"] == "" and b["parts"] == [
        {"label": "2.1", "text": "x", "hint": "hx"}, {"label": "2.2", "text": "y", "hint": "hy"}]
    one = grading.parse_questions('{"questions":[{"question":"S","parts":["p","q"]}],"hints":["only one"]}')
    assert one["questions"] == ["S\n1. p\n2. q"] and one["items"][0]["num"] == ""
    assert [p["hint"] for p in one["items"][0]["parts"]] == ["only one", ""]


def test_parse_questions_accepts_single_question_key():
    r = grading.parse_questions('{"question":" Why? "}')
    assert r["questions"] == ["Why?"] and r["items"][0] == {"num": "", "text": "Why?", "hint": "", "parts": []}


def test_display_items_escapes_ai_text():
    items = grading.parse_questions('{"questions":[{"question":"<b>","parts":["**k**"]}],"hints":[["<i>"]]}')["items"]
    d = ui.display_items(items)[0]
    assert d["text"] == "&lt;b&gt;" and d["parts"][0] == {"label": "1.", "text": "<b>k</b>", "hint": "&lt;i&gt;"}


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


def test_question_html_sharp_starts_without_box():
    html = ui.question_html("<b>orig</b>", rewrite=True)
    assert html.index('id="ai-orig"') < html.index('class="ai-q loading"')
    assert '<textarea' not in html and "__HINT__" not in html


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
    assert '<span class="ai-mark-correct">✓</span> 1. Q one' in html and '<span class="ai-mark-wrong">✗</span> 2. Q two' in html and "(blank)" in html and "<li>m</li>" in html


def test_verdict_html_colours_wrong_red_partial_orange():
    v = {"verdict": "partial", "ease": 2, "feedback": "f", "missed": [],
         "per_question": [{"verdict": "correct", "note": ""}, {"verdict": "wrong", "note": ""},
                          {"verdict": "partial", "note": ""}]}
    html = ui.verdict_html(v, ["Q1", "Q2", "Q3"], ["a1", "a2", "a3"])
    assert '<div class="ai-you">You: a1' in html
    assert '<div class="ai-you ai-you-wrong">You: a2' in html and '<div class="ai-you ai-you-partial">You: a3' in html
    single = ui.verdict_html(dict(v, verdict="wrong", per_question=[]), [], ["x"])
    assert 'class="ai-you ai-you-wrong"' in single


def test_verdict_html_lists_claims_with_why():
    parts = [{"text": "2pc strong consistency", "verdict": "correct", "why": "ignored"},
             {"text": "saga <weak>", "verdict": "partial", "why": "**eventual**, not weak"}]
    v = {"verdict": "partial", "ease": 2, "feedback": "f", "missed": [],
         "per_question": [{"verdict": "partial", "note": "", "parts": parts}]}
    html = ui.verdict_html(v, ["Q"], ["whole answer text"])
    assert ('<div class="ai-you ai-you-marked">You:<ul class="ai-claims">'
            '<li><span class="ai-mark-correct">2pc strong consistency</span></li>'
            '<li><span class="ai-mark-partial">saga &lt;weak&gt;</span>'
            '<span class="ai-why"> — <b>eventual</b>, not weak</span></li></ul></div>') in html
    assert "whole answer text" not in html and "ignored" not in html
    plain = ui.verdict_html(dict(v, per_question=[{"verdict": "wrong", "note": "", "parts": []}]), [], ["x"])
    assert '<div class="ai-you ai-you-partial">You: x</div>' in plain  # no claims: whole answer by grade


def test_parse_grade_keeps_why_and_prompt_demands_consistency():
    r = grading.parse_grade('{"verdict":"partial","per_question":[{"verdict":"partial","parts":'
                            '[{"text":"a","verdict":"partial","why":" off "}]}]}')
    assert r["per_question"][0]["parts"] == [{"text": "a", "verdict": "partial", "why": "off"}]
    assert "a question is no better than its weakest claim" in grading.SYSTEM_PROMPT


def test_answer_side_keeps_model_answer_plain():
    assert "ai-model" not in ui.CSS and not hasattr(ui, "model_answer_html")


def test_missed_html_nothing():
    assert grading.missed_html([], "2026-10-09") == "<hr><b>Missed (2026-10-09)</b>: nothing"


def test_replace_missed_keeps_only_latest_section():
    back = ("<ul><li>real answer</li></ul>"
            "<hr><b>Missed (2026-09-26)</b><ul><li>old one</li></ul>"
            "<hr><b>Missed (2026-10-02)</b><ul><li>old two</li><li>x</li></ul>"
            "<hr><b>Missed (2026-10-05)</b>: nothing")
    out = grading.replace_missed(back, ["new"], "2026-10-09")
    assert out == "<ul><li>real answer</li></ul><hr><b>Missed (2026-10-09)</b><ul><li>new</li></ul>"


def test_replace_missed_clean_review_still_records_date():
    out = grading.replace_missed("A<hr><b>Missed (2026-09-26)</b><ul><li>old</li></ul>", [], "2026-10-09")
    assert out == "A<hr><b>Missed (2026-10-09)</b>: nothing"


def test_replace_missed_tolerates_editor_reformatting_and_keeps_other_hr():
    back = "A<hr>B\n<hr />\n<b> Missed (2026-09-26) </b>\n<ul>\n<li>old</li>\n</ul>"
    assert grading.replace_missed(back, ["n"], "D") == "A<hr>B<hr><b>Missed (D)</b><ul><li>n</li></ul>"


def test_edit_prompt_has_fields_review_and_request():
    v = {"verdict": "wrong", "feedback": "Missed the key part."}
    p = grading.edit_prompt({"Front": "Q?", "Back": "<b>A</b>"}, "fix the typo", ["Q1"], ["my ans"], v,
                            [("Deck", "be terse")])
    assert "[Front]\nQ?" in p and "[Back]\n<b>A</b>" in p and "Q: Q1\nUser: my ans" in p
    assert "Grade: wrong — Missed the key part." in p and p.endswith("fix the typo") and "be terse" in p


def test_parse_edit_reply_and_plan():
    r = grading.parse_edit_reply('```json\n{"reply": "Fixed.", "fields": {"Back": "B2", "Nope": "x", "Front": "Q"}}\n```')
    assert r["reply"] == "Fixed."
    changes, unknown = grading.plan_field_edit({"Front": "Q", "Back": "B"}, r["fields"])
    assert changes == {"Back": "B2"} and unknown == ["Nope"]
    assert grading.parse_edit_reply('{"reply": "Unclear."}') == {"reply": "Unclear.", "fields": {}}
    with pytest.raises(ValueError):
        grading.parse_edit_reply('{"fields": ["x"]}')


def test_verdict_html_has_edit_bar_with_status():
    v = {"verdict": "correct", "ease": 3, "feedback": "f", "missed": [], "per_question": []}
    html = ui.verdict_html(v, [], ["a"], ("Not saved: <x>", True))
    assert html.index('id="ai-edit"') < html.index('class="ai-verdict"')
    assert '<div id="ai-edit-status" class="ai-err">Not saved: &lt;x&gt;</div>' in html
    assert 'id="ai-edit-status">' in ui.verdict_html(v, [], ["a"])


def test_style_guide_in_every_system_prompt():
    from addon import generate_ops
    assert "\\( ... \\)" in grading.STYLE_GUIDE
    for prompt in (grading.system_prompt([]), grading.system_prompt(["be terse"]), grading.EDIT_SYSTEM_PROMPT,
                   generate_ops.GENERATE_SYSTEM_PROMPT):
        assert grading.STYLE_GUIDE in prompt


def test_rich_escapes_and_bolds_keeps_latex():
    assert grading.rich("**key** <i> \\(x^2\\)") == "<b>key</b> &lt;i&gt; \\(x^2\\)"
    assert grading.missed_html(["**a**"], "D") == "<hr><b>Missed (D)</b><ul><li><b>a</b></li></ul>"


def test_parse_json_reply_repairs_single_backslash_latex():
    # \( and \sqrt are invalid JSON escapes; \frac and \times parse as form feed / tab
    r = grading.parse_json_reply(r'{"feedback": "Use \(\sqrt{x}\) and \frac{a}{b} \times 2\nnext", "ok": "\\(y\\)"}')
    assert r["feedback"] == "Use \\(\\sqrt{x}\\) and \\frac{a}{b} \\times 2\nnext" and r["ok"] == "\\(y\\)"


def test_verdict_html_renders_bold_and_multiline_question():
    v = {"verdict": "correct", "ease": 3, "feedback": "**Key** fact", "missed": [],
         "per_question": [{"verdict": "correct", "note": "n"}]}
    html = ui.verdict_html(v, ["Explain:\n1. a\n2. b"], ["x"])
    assert "<b>Key</b> fact" in html and "</span> Explain:\n1. a\n2. b" in html
    two = ui.verdict_html(dict(v, per_question=v["per_question"] * 2), ["A", "B:\n2.1 x"], ["x", "y"])
    assert "</span> 1. A" in two and "</span> 2. B:\n2.1 x" in two


def test_deck_rules_override_defaults_and_can_show_original():
    assert grading.parse_questions('{"questions":["a"],"show_original":true}')["show_original"] is True
    assert grading.parse_questions('{"questions":["a"],"show_original":"yes"}')["show_original"] is False
    assert "Priority: deck rules" in grading.SYSTEM_PROMPT and "never more than 8" in grading.SYSTEM_PROMPT


def test_ask_prompt_sends_front_only():
    p = grading.ask_prompt("Front?", [("Deck", "r")])
    assert p.startswith("NEW CARD\n\nQuestion:\nFront?") and "Reference answer" not in p
    assert "only the card's question (its front), never its answer" in grading.SYSTEM_PROMPT


def test_card_box_answers_questions_and_edits():
    assert "answer their questions" in grading.EDIT_SYSTEM_PROMPT and "change nothing" in grading.EDIT_SYSTEM_PROMPT
    v = {"verdict": "correct", "ease": 3, "feedback": "f", "missed": [], "per_question": []}
    html = ui.verdict_html(v, [], ["a"], ("Because **ordering** is per partition", False))
    assert 'placeholder="Ask AI about this card, or to change it' in html and "Because <b>ordering</b>" in html
    js = ui.edit_status_js("x < **y**", False)
    assert "x &lt; <b>y</b>" in js and "innerHTML" in js


def test_prompt_explains_boxes_per_question():
    assert "each with ONE answer box" in grading.SYSTEM_PROMPT
    assert "use separate questions when each needs its own box" in grading.SYSTEM_PROMPT


def test_prompt_says_one_page_shared_context_once():
    assert "shared context appears once" in grading.SYSTEM_PROMPT
    assert "the way to present the card's question as written" in grading.SYSTEM_PROMPT
