"""Tests for the language filter. langdetect runs with a fixed seed."""

from __future__ import annotations

from app.ingest.langfilter import ascii_ratio, detect_language


def test_romaji_title_passes_as_english():
    # langdetect is uncertain on short romaji, so the ASCII tiebreak
    # must carry this one.
    assert detect_language("Seiwa Gakuen vs Aomori Yamada Highlights", "") == "en"


def test_plain_english_detected():
    result = detect_language(
        "Japanese High School Soccer Final",
        "Full match highlights with English commentary.",
    )
    assert result == "en"


def test_japanese_detected():
    assert detect_language("高校サッカー 決勝 ハイライト", "全国大会の決勝戦です。") == "ja"


def test_other_confident_language_keeps_its_code():
    result = detect_language(
        "Melhores momentos do futebol juvenil brasileiro",
        "Resumo completo da partida com todos os gols.",
    )
    assert result == "pt"


def test_empty_metadata_is_other():
    assert detect_language("", "") == "other"


def test_uncertain_non_ascii_title_is_other():
    # Mixed script keeps the detector below the confidence bar, and the
    # title is not mostly ASCII, so the fallback is "other".
    assert detect_language("第3回 U-18 Cup 高校", "") == "other"


def test_detection_is_deterministic():
    title = "Seiwa Gakuen vs Aomori Yamada Highlights"
    results = {detect_language(title, "") for _ in range(5)}
    assert len(results) == 1


def test_ascii_ratio():
    assert ascii_ratio("") == 0.0
    assert ascii_ratio("abc") == 1.0
    assert ascii_ratio("ab高校") == 0.5
