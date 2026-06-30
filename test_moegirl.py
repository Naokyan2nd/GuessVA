"""Test Moegirl and Wikipedia infobox parsing."""
import json
import re
import urllib.parse
import urllib.request

UA = {"User-Agent": "NaoCharacterGame/1.0 (educational; contact@example.com)"}


def mediawiki_wikitext(title: str, base: str) -> str | None:
    params = urllib.parse.urlencode({
        "action": "query",
        "titles": title,
        "prop": "revisions",
        "rvprop": "content",
        "format": "json",
        "formatversion": "2",
    })
    url = f"{base}/api.php?{params}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None
    revs = pages[0].get("revisions", [])
    return revs[0]["content"] if revs else None


def parse_moegirl_infobox(wikitext: str) -> dict:
    fields = {}
    patterns = {
        "age": r"\|年龄\s*=\s*([^\n|]+)",
        "hair": r"\|发色\s*=\s*([^\n|]+)",
        "gender": r"\|性别\s*=\s*([^\n|]+)",
        "race": r"\|种族\s*=\s*([^\n|]+)",
        "origin": r"\|出身地区\s*=\s*([^\n|]+)",
        "job": r"\|职业\s*=\s*([^\n|]+)",
        "title": r"\|萌点\s*=\s*([^\n|]+)",
    }
    for k, pat in patterns.items():
        m = re.search(pat, wikitext)
        if m:
            fields[k] = m.group(1).strip()
    return fields


def parse_jawiki_infobox(wikitext: str) -> dict:
    fields = {}
    for key, pat in [
        ("age", r"\|年齢\s*=\s*([^\n|]+)"),
        ("hair", r"\|髪色\s*=\s*([^\n|]+)"),
        ("gender", r"\|性別\s*=\s*([^\n|]+)"),
        ("job", r"\|職業\s*=\s*([^\n|]+)"),
    ]:
        m = re.search(pat, wikitext)
        if m:
            fields[key] = m.group(1).strip()
    return fields


if __name__ == "__main__":
    for title in ["由比滨结衣", "须磨(鬼灭之刃)", "东山奈央"]:
        wt = mediawiki_wikitext(title, "https://zh.moegirl.org.cn")
        if wt:
            print(title, parse_moegirl_infobox(wt))
        else:
            print(title, "NOT FOUND")

    wt = mediawiki_wikitext("由比ヶ浜結衣", "https://ja.wikipedia.org")
    print("jawiki", parse_jawiki_infobox(wt or ""))
