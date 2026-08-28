"""Seed keywords and channels for the bootstrap ingest.

The keyword list is frozen before any scoring runs. If it ever changes,
the change and its reason must be recorded in the case study. The list
mixes the demo niche with adjacent niches (similar topics the demo niche
competes with) and contrast niches (clearly different or oversupplied
topics) so the scoring in later phases has something to rank against.
"""

from __future__ import annotations

# All English, all lowercase. Stored as a tuple so it cannot be mutated
# at runtime. Roughly 30 keywords: 4 for the demo niche, the rest for
# adjacent and contrast niches.
SEED_KEYWORDS: tuple[str, ...] = (
    # Demo niche: English-language coverage of Japanese high school soccer.
    "japanese high school soccer",
    "seiwa gakuen soccer",
    "high school soccer japan",
    "japan youth football",
    # Adjacent: other Japanese school sports.
    "japanese high school baseball",
    "koshien baseball highlights",
    "japanese high school basketball",
    "japanese high school volleyball",
    "japanese high school rugby",
    "japan high school track and field",
    # Adjacent: youth and school soccer in other countries.
    "american high school soccer",
    "english football academy",
    "korean high school soccer",
    "brazilian youth soccer",
    "spanish youth football academy",
    "german youth academy football",
    "australian youth soccer",
    # Contrast: generic soccer content.
    "soccer skills tutorial",
    "soccer training drills",
    "premier league highlights",
    "champions league highlights",
    "world cup goals",
    # Contrast: clearly oversupplied topics.
    "football highlights",
    "game highlights",
    "sports highlights",
    # Contrast: unrelated sports.
    "nba highlights",
    "nfl highlights",
    "tennis highlights",
    "sumo wrestling matches",
    "table tennis highlights",
)

# Hand-curated English-language channels that cover the demo niche
# (Japanese high school soccer). Keyword search alone may not surface
# them, and the demo depends on them being in the corpus. This list is
# filled in during the first real bootstrap run, by looking the channels
# up on YouTube and copying their real channel ids. It must contain real
# channel ids only, never invented ones.
SEED_CHANNEL_IDS: list[str] = []

# Lowercase substrings used by Gate B to spot demo-topic videos by
# title match. "takamado" refers to the Prince Takamado Trophy league
# and "inter high" to the Inter-High School Championships, the two main
# national competitions in this niche.
DEMO_TOPIC_TERMS: tuple[str, ...] = (
    "japanese high school soccer",
    "seiwa",
    "takamado",
    "inter high",
    "japan high school",
)
