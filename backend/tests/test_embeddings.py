"""Tests for the pure embedding-text builder. No model is loaded."""

from __future__ import annotations

from app.services.embeddings import build_embedding_text


def test_builds_title_tags_and_description_snippet():
    text = build_embedding_text(
        "Seiwa Gakuen vs Aomori Yamada Highlights",
        ["soccer", "highlights"],
        "Full match recap with commentary.",
    )
    assert text == (
        "Seiwa Gakuen vs Aomori Yamada Highlights soccer highlights "
        "Full match recap with commentary."
    )


def test_handles_missing_tags_explicitly():
    # Most videos have no tags; None must not become the literal "None".
    text = build_embedding_text("Title only", None, "Some description.")
    assert text == "Title only Some description."
    assert "None" not in text


def test_truncates_description_to_500_chars():
    long_description = "x" * 800
    text = build_embedding_text("Title", None, long_description)
    assert text == "Title " + "x" * 500


def test_handles_missing_description():
    text = build_embedding_text("Title", ["tag"], "")
    assert text == "Title tag"
