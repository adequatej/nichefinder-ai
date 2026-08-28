"""Language detection for video metadata.

Uses the langdetect package on title plus description. langdetect is
statistical and gets shaky on short text, so romaji titles (Japanese
names written in Latin letters, like "Seiwa Gakuen vs Aomori Yamada")
often come back as a low-confidence guess for some other language. The
tiebreak for those cases is the ASCII ratio of the title: a title that
is almost entirely plain ASCII is treated as English.
"""

from __future__ import annotations

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

# langdetect samples randomly internally. A fixed seed makes results
# deterministic across runs, which the tests rely on.
DetectorFactory.seed = 42

# Below this top-guess probability the detector is treated as uncertain
# and the ASCII tiebreak decides.
CONFIDENCE_THRESHOLD = 0.90

# A title whose characters are almost all ASCII is treated as English
# when the detector is uncertain.
ASCII_RATIO_THRESHOLD = 0.9


def ascii_ratio(text: str) -> float:
    """Fraction of characters that are plain ASCII. Empty text gives 0."""
    if not text:
        return 0.0
    ascii_count = sum(1 for ch in text if ord(ch) < 128)
    return ascii_count / len(text)


def detect_language(title: str, description: str = "") -> str:
    """Return a short language code ("en", "ja", ...) or "other".

    Runs langdetect on title plus description. If the top guess is
    confident, its code is returned. If the detector is uncertain or
    errors, the ASCII ratio of the title breaks the tie: mostly-ASCII
    titles pass as "en", everything else becomes "other".
    """
    text = f"{title or ''} {description or ''}".strip()
    code: str | None = None
    if text:
        try:
            guesses = detect_langs(text)
            if guesses and guesses[0].prob >= CONFIDENCE_THRESHOLD:
                code = guesses[0].lang
        except LangDetectException:
            code = None
    if code is not None:
        return code
    if ascii_ratio(title or "") > ASCII_RATIO_THRESHOLD:
        return "en"
    return "other"
