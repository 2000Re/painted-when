"""Painted When? の再生リストの決め方(playlists.py が使う)。"""
HISTORIES = ["upload_history.json", "longform_history.json"]

LONG = ("Art History Timeline Challenge: Full Quizzes",
        "10 famous paintings in every episode: guess when each was painted, then see them on a timeline.")

ALL = ("Guess the Year: Famous Paintings Art Quiz",
       "When was this painted? A short art history quiz with famous public-domain paintings.")
FASHION = ("Fashion Clues: Date the Painting by the Clothes",
           "Ruffs, wigs, tricorn hats and bustles: guess the century of a painting from the clothes alone.")

UKIYOE = ("Ukiyo-e Quiz: Guess the Year of Japanese Woodblock Prints",
          "Hokusai, Hiroshige, Utamaro and more: guess when each Japanese woodblock print was made.")


def for_record(rec):
    if "keys" in rec:                       # longform_history.json(通常動画)
        return [LONG]
    return [{"fashion": FASHION, "ukiyoe": UKIYOE}.get(rec.get("format"), ALL)]
