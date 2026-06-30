"""Enrich nao_characters.json from AniList, Jikan/MAL, Wikidata, and Wikipedia."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from enrich_from_wiki import (
    WORK_CN_FALLBACK,
    extract_jp_name,
    guess_gender,
    guess_genres,
    guess_hair,
    guess_race,
)

BASE = Path(__file__).resolve().parent
JSON_PATH = BASE / "nao_characters.json"
CACHE_PATH = BASE / "_enrich_cache.json"
UA = {"User-Agent": "NaoCharacterGame/1.0 (local fan project)"}

TOYAMA_NAMES = {"Touyama, Nao", "Toyama Nao", "Nao Toyama", "東山奈央", "東山 奈央"}

HAIR_PATTERNS = [
    (r"粉|ピンク|桃|桜|さくら|pink", "粉"),
    (r"金|ブロンド|blonde|yellow hair|golden hair", "金"),
    (r"銀|シルバー|silver", "银"),
    (r"青|ブルー|blue hair|navy hair", "蓝"),
    (r"緑|グリーン|green hair", "绿"),
    (r"赤|紅|red hair|crimson", "红"),
    (r"白|ホワイト|white hair", "白"),
    (r"紫|パープル|violet hair|purple hair", "紫"),
    (r"黒|ブラック|black hair", "黑"),
    (r"茶|褐|brown hair|brunette", "褐"),
]

RACE_PATTERNS = [
    (r"神(?!秘|話|話)|女神|goddess|deity", "神"),
    (r"魔族|demon(?!\s*slayer)|恶魔|devil|fiend", "魔族"),
    (r"恶魔(?!猎)|悪魔", "恶魔"),
    (r"精灵|エルフ|elf", "精灵"),
    (r"机器人|ロボ|android|人造人", "机器人"),
    (r"舰|艦|kanmusu|ship girl", "军舰拟人"),
    (r"吸血鬼|vampire", "吸血鬼"),
    (r"天使|angel", "天使"),
    (r"妖精|fairy", "妖精"),
    (r"龙|ドラゴン|dragon", "龙"),
    (r"兽人|獣人|beastman", "兽人"),
    (r"魔剑|sentient sword", "魔剑"),
    (r"坠天", "坠天"),
]

TITLE_PATTERNS = [
    (r"高校生|high school student|高中生|中学生|middle school|大学生|college student", "高中生"),
    (r"偶像|idol|歌手|singer", "偶像"),
    (r"女仆|maid", "女仆"),
    (r"忍者|ninja", "忍者"),
    (r"武士|samurai", "武士"),
    (r"骑士|knight|騎士", "骑士"),
    (r"公主|princess|王女", "公主"),
    (r"女王|queen", "女王"),
    (r"巫女|shrine maiden", "巫女"),
    (r"魔法师|魔法使|mage|magician|witch|魔女", "魔法使"),
    (r"护士|nurse", "护士"),
    (r"医生|doctor|医者", "医生"),
    (r"教师|老师|teacher|sensei", "教师"),
    (r"学生|student|生徒", "学生"),
    (r"花魁|oiran|courtesan", "花魁"),
    (r"忍者|ninja", "忍者"),
    (r"队长|captain|リーダー|leader", "队长"),
    (r"魔王|demon king|maou", "魔王"),
    (r"勇者|hero|heroine", "勇者"),
    (r"声优|voice actress|seiyuu", "声优"),
    (r"模特|model", "模特"),
    (r"店员|shop clerk|店員", "店员"),
    (r"女仆咖啡店|maid cafe", "女仆咖啡店员工"),
]

GENDER_MAP = {
    "female": "女", "male": "男", "女": "女", "男": "男",
    "Female": "女", "Male": "男",
}

ORIGIN_PATTERNS = [
    (r"日本|japan|tokyo|osaka", "日本"),
    (r"天界|heaven|celestial", "天界"),
    (r"魔界|demon world|hell", "妖魔界"),
    (r"异世界|another world|isekai", "异世界"),
    (r"英国|britain|england|london", "英国"),
    (r"法国|france|paris", "法国"),
    (r"美国|america|usa", "美国"),
    (r"中国|china", "中国"),
]


def load_cache() -> dict:
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    else:
        cache = {}
    cache.setdefault("chars", {})
    cache.setdefault("names", {})
    cache.setdefault("media", {})
    cache.setdefault("wikidata", None)
    return cache


def save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def http_json(url: str, data: bytes | None = None, headers: dict | None = None, retries: int = 3) -> dict:
    hdr = {**UA, **(headers or {})}
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdr)
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and i < retries - 1:
                time.sleep(2 ** (i + 1))
                continue
            raise
        except urllib.error.URLError:
            if i < retries - 1:
                time.sleep(2)
                continue
            raise
    return {}


def normalize_text(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s.lower())


def work_match_score(work_cn: str, work_jp: str, api_titles: list[str]) -> int:
    keys = {normalize_text(work_cn), normalize_text(work_jp)}
    for jp, cn in WORK_CN_FALLBACK.items():
        if work_cn == cn or work_jp == jp or jp in work_jp:
            keys.add(normalize_text(jp))
            keys.add(normalize_text(cn))
    best = 0
    for title in api_titles:
        nt = normalize_text(title)
        if not nt:
            continue
        for k in keys:
            if not k:
                continue
            if k == nt or k in nt or nt in k:
                best = max(best, 100)
            elif len(k) >= 4 and len(nt) >= 4 and (k[:4] in nt or nt[:4] in k):
                best = max(best, 60)
    return best


def parse_age(raw: str | int | None) -> str:
    if raw is None:
        return "???"
    if isinstance(raw, int):
        return str(raw) if raw > 0 else "???"
    s = str(raw).strip()
    if not s or s in ("未知", "?", "??", "???", "—", "-", "不明"):
        return "???"
    m = re.search(r"(\d{1,3})", s)
    if m:
        return m.group(1)
    return "???"


def parse_hair(*texts: str) -> list[str]:
    joined = " ".join(t for t in texts if t)
    for pat, color in HAIR_PATTERNS:
        if re.search(pat, joined, re.I):
            return [color]
    return []


def parse_race(char_jp: str, work: str, *texts: str) -> list[str]:
    joined = " ".join(texts) + " " + char_jp + " " + work
    for pat, race in RACE_PATTERNS:
        if re.search(pat, joined, re.I):
            return [race]
    return guess_race(char_jp, work)


def parse_origin(race: list[str], *texts: str) -> list[str]:
    if race != ["人类"]:
        for pat, place in ORIGIN_PATTERNS:
            if pat.startswith("天界") or pat.startswith("魔界"):
                if re.search(pat, " ".join(texts), re.I):
                    return [place]
        return ["日本"] if race == ["军舰拟人"] else [race[0]] if race else ["日本"]
    found = []
    joined = " ".join(texts)
    for pat, place in ORIGIN_PATTERNS:
        if re.search(pat, joined, re.I) and place not in found:
            found.append(place)
    if "日本" not in found:
        found.insert(0, "日本")
    if race == ["人类"] and "地球" not in found:
        found.append("地球")
    return found[:3] if found else ["日本", "地球"]


def parse_titles(*texts: str, role: str | None = None) -> list[str]:
    joined = " ".join(t for t in texts if t)
    titles = []
    for pat, title in TITLE_PATTERNS:
        if re.search(pat, joined, re.I) and title not in titles:
            titles.append(title)
    if role and re.search(r"main", role, re.I) and "主角" not in titles:
        pass
    return titles[:5]


def parse_gender(*values: str | None) -> list[str]:
    for v in values:
        if not v:
            continue
        for key, out in GENDER_MAP.items():
            if key.lower() in v.lower():
                return [out]
    return []


def fetch_wikidata(cache: dict) -> dict[str, dict]:
    if cache.get("wikidata"):
        return cache["wikidata"]
    sparql = """
SELECT ?char ?charLabel ?genderLabel WHERE {
  ?char wdt:P725 wd:Q865906.
  OPTIONAL { ?char wdt:P21 ?gender. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". }
}
"""
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": sparql, "format": "json"})
    data = http_json(url, headers={"Accept": "application/sparql-results+json"})
    out: dict[str, dict] = {}
    for row in data.get("results", {}).get("bindings", []):
        name = row.get("charLabel", {}).get("value", "")
        gender = row.get("genderLabel", {}).get("value", "")
        if name:
            out[name] = {"gender": gender}
    cache["wikidata"] = out
    save_cache(cache)
    return out


def anilist_search(name: str) -> list[dict]:
    query = """
query ($search: String) {
  Page(page: 1, perPage: 8) {
    characters(search: $search) {
      id
      name { full native alternative }
      gender
      age
      description(asHtml: false)
      media(perPage: 8) {
        nodes { title { romaji native english } type }
      }
    }
  }
}
"""
    body = json.dumps({"query": query, "variables": {"search": name}}).encode()
    try:
        data = http_json("https://graphql.anilist.co", data=body, headers={"Content-Type": "application/json"})
        return data.get("data", {}).get("Page", {}).get("characters") or []
    except Exception:
        return []


def jikan_search(name: str) -> list[dict]:
    url = "https://api.jikan.moe/v4/characters?" + urllib.parse.urlencode({"q": name, "limit": 8})
    try:
        data = http_json(url)
        return data.get("data") or []
    except Exception:
        return []


def jikan_full(mal_id: int) -> dict | None:
    try:
        data = http_json(f"https://api.jikan.moe/v4/characters/{mal_id}/full")
        return data.get("data")
    except Exception:
        return None


def anilist_media_genres(work: str, cache: dict) -> list[str]:
    if work in cache["media"]:
        return cache["media"][work]
    query = """
query ($search: String) {
  Media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
    genres
    tags { name }
  }
}
"""
    body = json.dumps({"query": query, "variables": {"search": work}}).encode()
    try:
        data = http_json("https://graphql.anilist.co", data=body, headers={"Content-Type": "application/json"})
        media = data.get("data", {}).get("Media")
        if not media:
            cache["media"][work] = []
            return []
        genres = media.get("genres") or []
        mapping = {
            "Action": "动作", "Adventure": "冒险", "Comedy": "喜剧", "Drama": "剧情",
            "Fantasy": "奇幻", "Romance": "恋爱", "Sci-Fi": "科幻", "Slice of Life": "日常",
            "Sports": "运动", "Supernatural": "超自然", "Mystery": "悬疑", "Horror": "恐怖",
            "Ecchi": "H", "Harem": "后宫", "Music": "音乐", "School": "校园",
            "Psychological": "心理", "Thriller": "悬疑", "Mecha": "机器人",
        }
        out = [mapping.get(g, g) for g in genres]
        cache["media"][work] = out
        save_cache(cache)
        time.sleep(0.35)
        return out
    except Exception:
        cache["media"][work] = []
        return []


def jawiki_infobox(name: str) -> dict:
    for lang in ("ja", "zh"):
        base = f"https://{lang}.wikipedia.org"
        params = urllib.parse.urlencode({"action": "opensearch", "search": name, "limit": 3, "format": "json"})
        try:
            data = http_json(f"{base}/api.php?{params}")
            titles = data[1] if len(data) > 1 else []
        except Exception:
            continue
        for title in titles:
            if name not in title and not any(ord(c) > 127 for c in name):
                continue
            raw_params = urllib.parse.urlencode({
                "action": "query", "titles": title, "prop": "revisions",
                "rvslots": "main", "rvprop": "content", "format": "json", "formatversion": "2",
            })
            try:
                page_data = http_json(f"{base}/api.php?{raw_params}")
                pages = page_data.get("query", {}).get("pages", [])
                if not pages or pages[0].get("missing"):
                    continue
                wt = pages[0]["revisions"][0]["slots"]["main"]["content"]
            except Exception:
                continue
            fields = {}
            for key, pat in [
                ("age", r"\|年齢\s*=\s*([^\n|]+)"),
                ("age", r"\|年龄\s*=\s*([^\n|]+)"),
                ("hair", r"\|髪色\s*=\s*([^\n|]+)"),
                ("hair", r"\|发色\s*=\s*([^\n|]+)"),
                ("gender", r"\|性別\s*=\s*([^\n|]+)"),
                ("gender", r"\|性别\s*=\s*([^\n|]+)"),
                ("job", r"\|職業\s*=\s*([^\n|]+)"),
                ("job", r"\|职业\s*=\s*([^\n|]+)"),
            ]:
                m = re.search(pat, wt)
                if m and key not in fields:
                    fields[key] = m.group(1).strip()
            if fields:
                return fields
    return {}


def lookup_by_name(name: str, work: str, cache: dict) -> dict:
    if name in cache["names"]:
        return cache["names"][name]

    result = {
        "age": "???", "gender": [], "hair": [], "race": [], "origin": [],
        "titles": [], "source": [],
    }

    # --- AniList (fast, primary) ---
    anilist_hits = anilist_search(name)
    time.sleep(0.35)
    exact_hits = []
    for ch in anilist_hits:
        native = (ch.get("name") or {}).get("native") or ""
        if normalize_text(native) == normalize_text(name) or name in native:
            exact_hits.append(ch)
    best = None
    best_score = -1
    for ch in exact_hits:
        media_titles = []
        for node in (ch.get("media") or {}).get("nodes") or []:
            t = node.get("title") or {}
            media_titles.extend([t.get("romaji"), t.get("native"), t.get("english")])
        score = work_match_score(work, work, [x for x in media_titles if x])
        if score > best_score:
            best_score = score
            best = ch
    if best is None and exact_hits:
        best = exact_hits[0]
        best_score = 0
    if best:
        result["source"].append("anilist")
        if best.get("age"):
            result["age"] = parse_age(best["age"])
        g = parse_gender(best.get("gender"))
        if g:
            result["gender"] = g
        desc = best.get("description") or ""
        result["hair"] = parse_hair(desc)
        result["titles"] = parse_titles(desc)
        result["race"] = parse_race(name, work, desc)
        result["origin"] = parse_origin(result["race"], desc)

    # --- Jikan (verify Toyama, fill gaps) ---
    need_jikan = result["age"] == "???" or not result["gender"] or not result["titles"]
    if need_jikan:
        jikan_candidates = []
        for item in jikan_search(name)[:4]:
            mal_id = item.get("mal_id")
            if not mal_id:
                continue
            full = jikan_full(mal_id)
            time.sleep(0.35)
            if not full:
                continue
            jp_voices = [
                v["person"]["name"] for v in full.get("voices", [])
                if v.get("language") == "Japanese"
            ]
            if not any(v in TOYAMA_NAMES for v in jp_voices):
                continue
            kanji = full.get("name_kanji") or ""
            if normalize_text(name) not in normalize_text(kanji) and name not in kanji:
                continue
            anime_titles = [a["anime"]["title"] for a in full.get("anime", []) if a.get("anime")]
            score = work_match_score(work, work, anime_titles)
            jikan_candidates.append((score, full))
            if score >= 80:
                break
        jikan_candidates.sort(key=lambda x: -x[0])
        if jikan_candidates:
            full = jikan_candidates[0][1]
            about = full.get("about") or ""
            result["source"].append("jikan")
            if not result["titles"]:
                result["titles"] = parse_titles(about)
            if not result["hair"]:
                result["hair"] = parse_hair(about)
            if not result["race"] or result["race"] == ["人类"]:
                result["race"] = parse_race(name, work, about)
                result["origin"] = parse_origin(result["race"], about)

    cache["names"][name] = result
    save_cache(cache)
    return result


def lookup_character(name: str, work: str, cache: dict) -> dict:
    key = f"{name}|{work}"
    if key in cache["chars"]:
        return cache["chars"][key]
    result = dict(lookup_by_name(name, work, cache))
    cache["chars"][key] = result
    save_cache(cache)
    return result


def is_rich_entry(entry: dict) -> bool:
    age = entry.get("初登場の年齢", "???")
    if age not in ("未知", "???", "?", ""):
        return True
    if len(entry.get("肩書") or []) >= 2:
        return True
    return False


def apply_lookup(entry: dict, lookup: dict, wikidata: dict, cache: dict) -> dict:
    jp = extract_jp_name(entry["名前"])
    work = entry["初登場の作品"]

    if lookup.get("age") and lookup["age"] != "???":
        entry["初登場の年齢"] = lookup["age"]
    elif entry.get("初登場の年齢") == "未知":
        entry["初登場の年齢"] = "???"

    if lookup.get("gender"):
        entry["性別"] = lookup["gender"]
    elif jp in wikidata:
        g = wikidata[jp].get("gender", "")
        if "female" in g.lower() or "女" in g:
            entry["性別"] = ["女"]
        elif "male" in g.lower() or "男" in g:
            entry["性別"] = ["男"]
        elif not entry.get("性別"):
            entry["性別"] = guess_gender(jp)

    if lookup.get("race"):
        entry["種族"] = lookup["race"]
    if lookup.get("origin"):
        entry["出身"] = lookup["origin"]
    if lookup.get("hair"):
        entry["髪色"] = lookup["hair"]
    elif not entry.get("髪色") or entry["髪色"] == ["黑"]:
        entry["髪色"] = guess_hair(jp)

    if lookup.get("titles"):
        merged = list(dict.fromkeys((entry.get("肩書") or []) + lookup["titles"]))
        entry["肩書"] = merged[:6]

    genres = lookup.get("genres") or []
    if not genres:
        genres = guess_genres(work)
    if genres and (not entry.get("作品ジャンル") or entry["作品ジャンル"] == ["动画"]):
        entry["作品ジャンル"] = genres

    return entry


def infer_titles_from_work(work: str, media: list[str], main_flag: str) -> list[str]:
    titles = []
    w = work + " ".join(media)
    rules = [
        (r"高校|学園|学校|部|青春", "高中生"),
        (r"偶像大师|アイドル|ラブライブ|プリキュア|光之美少女", "偶像"),
        (r"艦これ|舰队", "舰娘"),
        (r"魔王|勇者", "冒险者"),
        (r"忍者|火影", "忍者"),
        (r"魔法|魔女|魔导", "魔法使"),
        (r"女仆|メイド", "女仆"),
        (r"游戏|ゲーム", "游戏角色"),
    ]
    for pat, title in rules:
        if re.search(pat, w, re.I) and title not in titles:
            titles.append(title)
    if main_flag == "是" and "主角" not in titles:
        titles.insert(0, "主角")
    return titles[:4]


def apply_manual_by_jp(entry: dict, manual_by_jp: dict[str, dict]) -> bool:
    jp = extract_jp_name(entry["名前"])
    donor = manual_by_jp.get(jp)
    if not donor:
        return False
    for f in ("初登場の年齢", "性別", "種族", "出身", "髪色", "肩書", "作品ジャンル"):
        if donor.get(f) and (not entry.get(f) or entry.get(f) == ["黑"] or entry.get("初登場の年齢") == "未知"):
            entry[f] = donor[f]
    return True


def propagate(entries: list[dict]) -> None:
    by_name: dict[str, list[dict]] = {}
    for e in entries:
        by_name.setdefault(extract_jp_name(e["名前"]), []).append(e)

    fields = ["初登場の年齢", "性別", "種族", "出身", "髪色", "肩書", "作品ジャンル"]
    for group in by_name.values():
        if len(group) < 2:
            continue
        rich = [g for g in group if is_rich_entry(g)]
        if not rich:
            continue
        donor = max(rich, key=lambda g: len(g.get("肩書") or []))
        for target in group:
            if target is donor:
                continue
            for f in fields:
                dv = donor.get(f)
                tv = target.get(f)
                if f == "初登場の年齢":
                    if tv in ("未知", "???", "?", "") and dv not in ("未知", "???", "?", ""):
                        target[f] = dv
                elif isinstance(dv, list) and dv and (not tv or tv == [] or tv == ["黑"] or tv == ["动画"]):
                    target[f] = list(dv)
                elif isinstance(dv, str) and dv and not tv:
                    target[f] = dv


def main():
    cache = load_cache()
    wikidata = fetch_wikidata(cache)
    entries = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    manual = json.loads((BASE / "nao_characters.json.bak").read_text(encoding="utf-8"))
    manual_by = {(extract_jp_name(c["名前"]), c["初登場の作品"]): c for c in manual}
    manual_by_jp: dict[str, dict] = {}
    for c in manual:
        jp = extract_jp_name(c["名前"])
        if jp not in manual_by_jp or len(c.get("肩書") or []) > len(manual_by_jp[jp].get("肩書") or []):
            manual_by_jp[jp] = c

    names_needed: list[str] = []
    name_set: set[str] = set()
    for entry in entries:
        jp = extract_jp_name(entry["名前"])
        work = entry["初登場の作品"]
        if (jp, work) in manual_by or jp in manual_by_jp:
            continue
        if jp not in name_set and jp not in cache["names"]:
            name_set.add(jp)
            names_needed.append(jp)

    print(f"Name lookups needed: {len(names_needed)} (cached names: {len(cache['names'])})", flush=True)
    for idx, jp in enumerate(names_needed):
        lookup_by_name(jp, "", cache)
        if (idx + 1) % 20 == 0:
            print(f"Lookup progress: {idx + 1}/{len(names_needed)}", flush=True)

    enriched = 0
    for entry in entries:
        jp = extract_jp_name(entry["名前"])
        work = entry["初登場の作品"]
        key = (jp, work)

        if key in manual_by:
            entry.clear()
            entry.update(manual_by[key])
            continue

        apply_manual_by_jp(entry, manual_by_jp)

        lookup = cache["names"].get(jp, {})
        entry = apply_lookup(entry, lookup, wikidata, cache)
        if not entry.get("肩書"):
            entry["肩書"] = infer_titles_from_work(
                work, entry.get("出演メディア") or [], entry.get("メインキャラかどうか", "否")
            )
        enriched += 1

    propagate(entries)

    # enrich genres for works still using generic fallback
    generic_works = {
        e["初登場の作品"] for e in entries
        if e.get("作品ジャンル") == ["动画"] and e["初登場の作品"] not in cache["media"]
    }
    print(f"Fetching genres for {len(generic_works)} works...", flush=True)
    for i, work in enumerate(sorted(generic_works)):
        anilist_media_genres(work, cache)
        if (i + 1) % 30 == 0:
            print(f"Genre progress: {i + 1}/{len(generic_works)}", flush=True)
    for entry in entries:
        g = cache["media"].get(entry["初登場の作品"])
        if g and (not entry.get("作品ジャンル") or entry["作品ジャンル"] == ["动画"]):
            entry["作品ジャンル"] = g

    for entry in entries:
        if entry.get("初登場の年齢") == "未知":
            entry["初登場の年齢"] = "???"
        jp = extract_jp_name(entry["名前"])
        if not entry.get("性別"):
            entry["性別"] = guess_gender(jp)
        if not entry.get("種族"):
            entry["種族"] = guess_race(jp, entry["初登場の作品"])
        if not entry.get("出身"):
            entry["出身"] = parse_origin(entry["種族"])
        if not entry.get("髪色"):
            entry["髪色"] = guess_hair(jp)
        if not entry.get("肩書"):
            entry["肩書"] = infer_titles_from_work(
                entry["初登場の作品"], entry.get("出演メディア") or [], entry.get("メインキャラかどうか", "否")
            )
        if not entry.get("作品ジャンル"):
            entry["作品ジャンル"] = guess_genres(entry["初登場の作品"])

    JSON_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    unknown = sum(1 for e in entries if e.get("初登場の年齢") == "???")
    empty_title = sum(1 for e in entries if not e.get("肩書"))
    print(f"Done. Total={len(entries)}, enriched={enriched}", flush=True)
    print(f"Age unknown (???): {unknown}, Empty titles: {empty_title}", flush=True)


if __name__ == "__main__":
    main()
