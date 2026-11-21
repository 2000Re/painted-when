"""答えの年を、だれでも知っている出来事と比べる一文(「Painted 13 years before the Titanic sank」)。

画面に出すだけで、読み上げはしない(動画を長くしないため)。出来事と年は、教科書にのる確かなものだけ。
制作年に幅がある・「ca.」などのあいまいな年のときは「about」を付ける。1969年より後の作品は出さない。
"""
import re

# (年, 「before」のあとに続く言い方)
EVENTS = [
    (1492, "Columbus reached the Americas"),
    (1543, "Copernicus published his Sun-centered model"),
    (1564, "Shakespeare was born"),
    (1620, "the Mayflower sailed to America"),
    (1687, "Newton published his laws of motion"),
    (1776, "the US Declaration of Independence"),
    (1789, "the French Revolution began"),
    (1825, "the first public steam railway opened"),
    (1839, "photography was announced to the world"),
    (1876, "the telephone was patented"),
    (1886, "the first car was patented"),
    (1903, "the Wright brothers' first flight"),
    (1912, "the Titanic sank"),
    (1969, "the first Moon landing"),
]


def fact(art, year):
    """year(クイズの答えの年)のあとで、いちばん近い出来事との差。出せなければ None。"""
    if not year:
        return None
    nxt = next(((y, t) for y, t in EVENTS if y > year), None)
    if not nxt:
        return None
    gap = nxt[0] - year
    end = art.get("year_end")
    approx = (end is not None and end != art.get("year_start")) or bool(
        re.search(r"\b(ca\.?|c\.|about|circa)\b|[–-]", str(art.get("date") or ""), re.I))
    return f"Painted {'about ' if approx else ''}{gap} year{'s' if gap != 1 else ''} before {nxt[1]}"
