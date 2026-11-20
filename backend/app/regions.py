"""Region helpers for matching: city extraction and rough straight-line distance.

The coordinates are approximate city centres for the demo city list. They are only
used to rank candidates ("가까운 순") and to show an approximate distance, never as
a transport route or a quote basis.
"""
import math
import re

from .request_chat import CITIES

CITY_PATTERN = re.compile(rf"({CITIES})")

# Approximate city-hall coordinates (latitude, longitude).
CITY_COORDINATES: dict[str, tuple[float, float]] = {
    "서울": (37.5665, 126.9780),
    "전주": (35.8242, 127.1480),
    "익산": (35.9483, 126.9577),
    "완주": (35.9047, 127.1622),
    "군산": (35.9676, 126.7369),
    "김제": (35.8036, 126.8809),
    "부안": (35.7317, 126.7335),
    "수원": (37.2636, 127.0286),
    "인천": (37.4563, 126.7052),
    "대전": (36.3504, 127.3845),
    "광주": (35.1595, 126.8526),
    "부산": (35.1796, 129.0756),
    "대구": (35.8714, 128.6014),
    "울산": (35.5384, 129.3114),
    "세종": (36.4800, 127.2890),
    "청주": (36.6424, 127.4890),
    "천안": (36.8151, 127.1139),
}


def city_of(text: str | None) -> str | None:
    """Return the first known city in free text such as '전북 전주시 덕진구'."""
    if not text:
        return None
    match = CITY_PATTERN.search(text)
    return match[1] if match else None


def normalized_region(region: str) -> str:
    city = city_of(region)
    if city:
        return city
    return region.strip().removesuffix("시").removesuffix("군")


def same_region(left: str, right: str) -> bool:
    return normalized_region(left) == normalized_region(right)


def distance_km(origin: str | None, destination: str | None) -> float | None:
    """Rough straight-line distance between two places, or None when unknown."""
    a = CITY_COORDINATES.get(normalized_region(origin or ""))
    b = CITY_COORDINATES.get(normalized_region(destination or ""))
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(h)), 1)
