"""Second-pass enrichment: AniList Staff bulk + heuristics + Wikipedia."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from enrich_characters import (
    JSON_PATH,
    UA,
    infer_titles_from_work,
    jawiki_infobox,
    parse_age,
    parse_gender,
    parse_hair,
    parse_origin,
    parse_race,
    parse_titles,
)
from enrich_from_wiki import extract_jp_name, guess_gender, guess_hair, guess_race

BASE = Path(__file__).resolve().parent
ANILIST_CACHE = BASE / "_anilist_staff_chars.json"

GENERIC_NAME_TITLES: list[tuple[str, list[str]]] = [
    (r"^女子高生$|^女子学生$|^女学生$", ["高中生"]),
    (r"^男子高生$|^男子学生$|^男学生$", ["高中生"]),
    (r"^女子大学生$|^女大学生$", ["大学生"]),
    (r"^通行人$|^歩行者$|^モブ$|^モブキャラ$", ["路人"]),
    (r"^ナレーション$|^ナレーター$|^語り$", ["旁白"]),
    (r"^幼児$|^赤ん坊$|^乳児$|^赤ちゃん$|^婴儿$", ["婴儿"]),
    (r"^店員$|^店員さん$", ["店员"]),
    (r"^教師$|^先生$", ["教师"]),
    (r"^メイド$", ["女仆"]),
    (r"^看護師$|^ナース$", ["护士"]),
    (r"^巫女$", ["巫女"]),
    (r"^花魁$", ["花魁"]),
    (r"^忍者$", ["忍者"]),
    (r"^騎士$", ["骑士"]),
    (r"^王女$|^公主$", ["公主"]),
    (r"^魔王$", ["魔王"]),
    (r"^勇者$", ["勇者"]),
    (r"^アイドル$", ["偶像"]),
    (r"^声優$", ["声优"]),
    (r"^娘$", ["少女"]),
    (r"^少年$", ["少年"]),
    (r"^老人$|^おばあさん$|^おじいさん$", ["老人"]),
    (r"高生$", ["高中生"]),
]

SCHOOL_AGE = {
    "初中生": "14",
    "高中生": "16",
    "大学生": "20",
    "学生": "16",
}


def http_json(url: str, data: bytes | None = None, headers: dict | None = None) -> dict:
    hdr = {**UA, **(headers or {})}
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, data=data, headers=hdr)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    return {}


def find_staff_id() -> int:
    return 106184


def fetch_all_staff_characters(staff_id: int) -> dict[str, dict]:
    if ANILIST_CACHE.exists():
        cached = json.loads(ANILIST_CACHE.read_text(encoding="utf-8"))
        if cached.get("staff_id") == staff_id and cached.get("chars"):
            return cached["chars"]

    chars: dict[str, dict] = {}
    page = 1
    while True:
        q = """
query ($id: Int, $page: Int) {
  Staff(id: $id) {
    characters(page: $page, perPage: 50, sort: ID) {
      pageInfo { hasNextPage lastPage }
      nodes {
        name { native full alternative }
        age gender
        description(asHtml: false)
      }
    }
  }
}
"""
        body = json.dumps({"query": q, "variables": {"id": staff_id, "page": page}}).encode()
        data = http_json(
            "https://graphql.anilist.co",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        block = data.get("data", {}).get("Staff", {}).get("characters", {})
        nodes = block.get("nodes") or []
        for ch in nodes:
            native = (ch.get("name") or {}).get("native") or ""
            if not native:
                continue
            desc = ch.get("description") or ""
            entry = {
                "age": parse_age(ch.get("age")),
                "gender": parse_gender(ch.get("gender")),
                "hair": parse_hair(desc),
                "titles": parse_titles(desc),
                "race": parse_race(native, "", desc),
                "origin": [],
                "description": desc,
            }
            entry["origin"] = parse_origin(entry["race"], desc)
            # keep richest entry per native name
            if native not in chars or (
                chars[native]["age"] == "???" and entry["age"] != "???"
            ):
                chars[native] = entry
        info = block.get("pageInfo") or {}
        print(f"AniList page {page}/{info.get('lastPage', '?')}, total {len(chars)}", flush=True)
        if not info.get("hasNextPage"):
            break
        page += 1
        time.sleep(1.2)

    ANILIST_CACHE.write_text(
        json.dumps({"staff_id": staff_id, "chars": chars}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return chars


def titles_from_name(jp: str) -> list[str]:
    for pat, titles in GENERIC_NAME_TITLES:
        if re.search(pat, jp):
            return titles
    return []


def infer_school_age(titles: list[str]) -> str | None:
    for title in titles:
        if title in SCHOOL_AGE:
            return SCHOOL_AGE[title]
    if "校园" in titles:
        return "16"
    return None


def apply_anilist(entry: dict, anilist: dict[str, dict]) -> None:
    jp = extract_jp_name(entry["名前"])
    data = anilist.get(jp)
    if not data:
        for alt_key, val in anilist.items():
            if jp in alt_key or alt_key in jp:
                data = val
                break
    if not data:
        return
    if entry.get("初登場の年齢") == "???" and data.get("age") not in (None, "???"):
        entry["初登場の年齢"] = data["age"]
    if data.get("gender") and (not entry.get("性別") or entry["性別"] == ["女"]):
        entry["性別"] = data["gender"]
    if data.get("hair") and entry.get("髪色") in (None, [], ["黑"]):
        entry["髪色"] = data["hair"]
    if data.get("race") and entry.get("種族") == ["人类"]:
        entry["種族"] = data["race"]
        if data.get("origin"):
            entry["出身"] = data["origin"]
    if data.get("titles"):
        merged = list(dict.fromkeys((entry.get("肩書") or []) + data["titles"]))
        entry["肩書"] = merged[:6]


def apply_heuristics(entry: dict) -> None:
    jp = extract_jp_name(entry["名前"])
    work = entry["初登場の作品"]
    media = entry.get("出演メディア") or []
    main = entry.get("メインキャラかどうか", "否")

    name_titles = titles_from_name(jp)
    if name_titles:
        entry["肩書"] = list(dict.fromkeys((entry.get("肩書") or []) + name_titles))[:6]

    if not entry.get("肩書"):
        entry["肩書"] = infer_titles_from_work(work, media, main)

    if main == "是" and "主角" not in (entry.get("肩書") or []):
        entry["肩書"] = ["主角"] + (entry.get("肩書") or [])
        entry["肩書"] = entry["肩書"][:6]

    if entry.get("初登場の年齢") == "???":
        age = infer_school_age(entry.get("肩書") or [])
        if age:
            entry["初登場の年齢"] = age
        elif re.search(r"高校|学園|学校", work) and "高中生" in (entry.get("肩書") or []):
            entry["初登場の年齢"] = "16"


def try_wikipedia(entry: dict) -> bool:
    if entry.get("初登場の年齢") != "???" and entry.get("肩書"):
        return False
    jp = extract_jp_name(entry["名前"])
    if len(jp) < 2 or re.search(r"^\d|^[『』]", jp):
        return False
    wiki = jawiki_infobox(jp)
    if not wiki:
        return False
    if wiki.get("age") and entry.get("初登場の年齢") == "???":
        entry["初登場の年齢"] = parse_age(wiki["age"])
    if wiki.get("gender") and not entry.get("性別"):
        entry["性別"] = parse_gender(wiki["gender"])
    if wiki.get("hair") and entry.get("髪色") in (None, [], ["黑"]):
        entry["髪色"] = parse_hair(wiki["hair"])
    if wiki.get("job"):
        entry["肩書"] = list(dict.fromkeys((entry.get("肩書") or []) + parse_titles(wiki["job"])))[:6]
    return True


def propagate_rich(entries: list[dict]) -> None:
    by_name: dict[str, list[dict]] = {}
    for e in entries:
        by_name.setdefault(extract_jp_name(e["名前"]), []).append(e)
    fields = ["初登場の年齢", "性別", "種族", "出身", "髪色", "肩書"]
    for group in by_name.values():
        if len(group) < 2:
            continue
        best = max(
            group,
            key=lambda g: (
                0 if g.get("初登場の年齢") in ("???", "未知", "") else 10,
                len(g.get("肩書") or []),
            ),
        )
        for t in group:
            if t is best:
                continue
            for f in fields:
                bv, tv = best.get(f), t.get(f)
                if f == "初登場の年齢":
                    if tv in ("???", "未知", "") and bv not in ("???", "未知", ""):
                        t[f] = bv
                elif isinstance(bv, list) and bv and (not tv or tv == ["黑"]):
                    t[f] = list(bv)


def main():
    print("Finding AniList staff id...", flush=True)
    staff_id = find_staff_id()
    print(f"Staff id: {staff_id}", flush=True)
    time.sleep(1.5)

    anilist = fetch_all_staff_characters(staff_id)
    print(f"AniList characters loaded: {len(anilist)}", flush=True)

    entries = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    for entry in entries:
        apply_anilist(entry, anilist)
        apply_heuristics(entry)

    propagate_rich(entries)

    wiki_hits = 0
    wiki_targets = [
        e for e in entries
        if (e.get("初登場の年齢") == "???" or not e.get("肩書"))
        and len(extract_jp_name(e["名前"])) >= 2
        and not re.search(r"^\d|^[『』]", extract_jp_name(e["名前"]))
    ]
    print(f"Wikipedia targets: {len(wiki_targets)}", flush=True)
    for i, entry in enumerate(wiki_targets[:80]):
        if try_wikipedia(entry):
            wiki_hits += 1
        time.sleep(0.8)
        if (i + 1) % 20 == 0:
            print(f"Wiki pass {i + 1}/{min(80, len(wiki_targets))}", flush=True)

    JSON_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    unknown = sum(1 for e in entries if e.get("初登場の年齢") == "???")
    no_title = sum(1 for e in entries if not e.get("肩書"))
    numeric = sum(1 for e in entries if str(e.get("初登場の年齢", "")).isdigit())
    print(f"Done. numeric age={numeric}, ??? age={unknown}, no title={no_title}, wiki={wiki_hits}", flush=True)


if __name__ == "__main__":
    main()
