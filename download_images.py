"""Download character images from AniList and Jikan into static/{名前}.png"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image

from enrich_from_wiki import extract_jp_name

BASE = Path(__file__).resolve().parent
JSON_PATH = BASE / "nao_characters.json"
STATIC = BASE / "static"
CACHE_PATH = BASE / "_image_urls.json"
STAFF_ID = 106184
UA = {"User-Agent": "NaoCharacterGame/1.0 (local fan project)"}
SKIP_FILES = {"nao_logo.png", "nao_shark.png"}
TOYAMA_NAMES = {"Touyama, Nao", "Toyama Nao", "Nao Toyama", "東山奈央", "東山 奈央"}


def http_bytes(url: str, retries: int = 5) -> bytes:
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and i < retries - 1:
                time.sleep(2 ** (i + 1))
                continue
            raise
    return b""


def gql(query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    for i in range(8):
        try:
            req = urllib.request.Request(
                "https://graphql.anilist.co",
                data=body,
                headers={**UA, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < 7:
                wait = min(90, 5 * (i + 1))
                print(f"AniList rate limit, wait {wait}s...", flush=True)
                time.sleep(wait)
                continue
            raise
    return {}


def normalize_key(name: str) -> str:
    return re.sub(r"\s+", "", name)


def fetch_anilist_image_map() -> dict[str, str]:
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {"jikan": {}}
    mapping: dict[str, str] = dict(cache.get("anilist", {}))
    start_page = cache.get("anilist_page_done", 0) + 1
    if mapping and cache.get("anilist_complete"):
        print(f"Using cached AniList images: {len(mapping)}", flush=True)
        return mapping

    page = start_page
    while True:
        try:
            data = gql(
                """
query ($id: Int, $page: Int) {
  Staff(id: $id) {
    characters(page: $page, perPage: 50, sort: ID) {
      pageInfo { hasNextPage lastPage }
      nodes {
        name { native full alternative }
        image { large }
      }
    }
  }
}
""",
                {"id": STAFF_ID, "page": page},
            )
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"AniList stopped at page {page}, using {len(mapping)} cached URLs", flush=True)
                break
            raise
        if not data.get("data", {}).get("Staff"):
            break
        block = data["data"]["Staff"]["characters"]
        for ch in block["nodes"]:
            url = (ch.get("image") or {}).get("large")
            if not url:
                continue
            native = (ch.get("name") or {}).get("native") or ""
            if native:
                mapping[normalize_key(native)] = url
                mapping[native] = url
        info = block["pageInfo"]
        cache["anilist"] = mapping
        cache["anilist_page_done"] = page
        cache["anilist_complete"] = not info.get("hasNextPage")
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"AniList images page {page}/{info.get('lastPage', '?')} -> {len(mapping)}", flush=True)
        if not info.get("hasNextPage"):
            break
        page += 1
        time.sleep(3.0)
    return mapping


def jikan_image(name: str, cache: dict, retry_failed: bool = False) -> str | None:
    cached = cache.get("jikan", {}).get(name)
    if cached and not retry_failed:
        return cached or None
    if cached == "" and not retry_failed:
        return None

    url = "https://api.jikan.moe/v4/characters?" + urllib.parse.urlencode({"q": name, "limit": 6})
    img_url = None
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        for item in data.get("data") or []:
            kanji = item.get("name_kanji") or ""
            if normalize_key(name) not in normalize_key(kanji) and name not in kanji:
                continue
            mal_id = item["mal_id"]
            time.sleep(0.4)
            req2 = urllib.request.Request(f"https://api.jikan.moe/v4/characters/{mal_id}/full", headers=UA)
            with urllib.request.urlopen(req2, timeout=30) as r2:
                full = json.loads(r2.read())["data"]
            voices = [
                v["person"]["name"] for v in full.get("voices", [])
                if v.get("language") == "Japanese"
            ]
            if voices and not any(v in TOYAMA_NAMES for v in voices):
                continue
            img_url = (full.get("images") or {}).get("jpg", {}).get("image_url")
            if img_url:
                break
    except Exception:
        img_url = None

    cache.setdefault("jikan", {})[name] = img_url or ""
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    time.sleep(1.0)
    return img_url


def lookup_url(jp: str, anilist: dict[str, str], cache: dict, retry_failed: bool = False) -> str | None:
    for key in (jp, normalize_key(jp)):
        if key in anilist:
            return anilist[key]
    return jikan_image(jp, cache, retry_failed=retry_failed)


def save_as_png(data: bytes, dest: Path) -> bool:
    try:
        img = Image.open(BytesIO(data))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, format="PNG", optimize=True)
        return True
    except Exception:
        return False


def main():
    STATIC.mkdir(exist_ok=True)
    chars = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    existing = {p.name for p in STATIC.glob("*.png")} - SKIP_FILES

    targets = []
    for c in chars:
        fname = f"{c['名前']}.png"
        if fname not in existing:
            targets.append(c)

    print(f"Missing images: {len(targets)}", flush=True)
    anilist = fetch_anilist_image_map()
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {"jikan": {}}

    ok = skip = fail = 0
    done_file = BASE / "_images_downloaded.json"
    done_set = set(json.loads(done_file.read_text(encoding="utf-8"))) if done_file.exists() else set()
    # only treat as done when the png file actually exists
    done_set = {n for n in done_set if (STATIC / f"{n}.png").exists()}

    for i, c in enumerate(targets):
        fname = c["名前"]
        dest = STATIC / f"{c['名前']}.png"
        if dest.exists():
            skip += 1
            continue
        jp = extract_jp_name(c["名前"])
        img_url = lookup_url(jp, anilist, cache, retry_failed=True)
        if not img_url:
            fail += 1
            done_set.add(fname)
            continue
        try:
            data = http_bytes(img_url)
            if save_as_png(data, dest):
                ok += 1
                existing.add(dest.name)
            else:
                fail += 1
        except Exception:
            fail += 1
        done_set.add(fname)
        if (i + 1) % 10 == 0:
            done_file.write_text(json.dumps(sorted(done_set), ensure_ascii=False, indent=2), encoding="utf-8")
        if (i + 1) % 25 == 0:
            print(f"Download {i + 1}/{len(targets)} ok={ok} skip={skip} fail={fail}", flush=True)

    done_file.write_text(json.dumps(sorted(done_set), ensure_ascii=False, indent=2), encoding="utf-8")

    still = sum(1 for c in chars if f"{c['名前']}.png" not in existing)
    print(f"Done. downloaded={ok}, failed={fail}, still missing={still}", flush=True)


if __name__ == "__main__":
    main()
