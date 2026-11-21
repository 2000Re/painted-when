"""Painted When? の再生リストの決め方(playlists.py が使う)。"""
HISTORIES = ["upload_history.json"]

ALL = ("Guess the Year: Famous Paintings Art Quiz",
       "When was this painted? A short art history quiz with famous public-domain paintings.")
FASHION = ("Fashion Clues: Date the Painting by the Clothes",
           "Ruffs, wigs, tricorn hats and bustles: guess the century of a painting from the clothes alone.")


def for_record(rec):
    return [FASHION if rec.get("format") == "fashion" else ALL]
