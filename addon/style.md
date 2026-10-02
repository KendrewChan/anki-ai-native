# Formatting style

Plain, clear text first. Every format has one meaning; use it only when that meaning applies.

## Short texts (questions, hints, notes, feedback, missed facts)
- Plain text. **bold** (double asterisks) marks the one key term a skimmer must not miss — at most one per text, often none.
- No other Markdown, no HTML, no colours. No lists (a question's sub-parts go in its "parts" array).

## Note fields (cards you write or edit)
Anki HTML only, no Markdown:
- <b> for the one key term of the answer; <i> for a term being defined or a title. Never <u> (reads as a link).
- <ul><li> only for 3+ parallel items; keep reasoning ("because", "so") in sentences.
- <table> only to compare 2+ things on 2+ attributes; short cells.
- <code> for code, commands and identifiers.
- No colour unless the user asks for it.

## Math (both kinds of text)
- LaTeX inside \( ... \) for inline math, \[ ... \] for a displayed formula. Never $ ... $.
- Use it for real formulas and symbols (\(O(n \log n)\), \(\frac{a}{b}\), \(x^2\)); plain words stay plain.
- Your reply is JSON, so every backslash is doubled in the JSON string: "\\(x^2\\)", "\\frac{a}{b}".
