"""Quick API probes for character enrichment."""
import json
import urllib.parse
import urllib.request

UA = {"User-Agent": "NaoCharacterGame/1.0 (educational project)"}


def wikidata_roles():
    sparql = """
SELECT ?char ?charLabel ?series ?seriesLabel ?genderLabel ?instanceLabel WHERE {
  ?char wdt:P725 wd:Q865906.
  OPTIONAL { ?char wdt:P21 ?gender. }
  OPTIONAL { ?char wdt:P31 ?instance. }
  OPTIONAL { ?char wdt:P1441 ?series. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en,zh". }
}
"""
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": sparql, "format": "json"})
    req = urllib.request.Request(url, headers={**UA, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    return data["results"]["bindings"]


def anilist_char(name: str):
    q = """
query ($search: String) {
  Page(page: 1, perPage: 3) {
    characters(search: $search) {
      name { full native alternative }
      gender
      age
      description(asHtml: false)
    }
  }
}
"""
    body = json.dumps({"query": q, "variables": {"search": name}}).encode()
    req = urllib.request.Request(
        "https://graphql.anilist.co",
        data=body,
        headers={**UA, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def wiki_search(name: str, lang="ja"):
    params = urllib.parse.urlencode({
        "action": "query", "list": "search", "srsearch": name, "srlimit": 3, "format": "json",
    })
    url = f"https://{lang}.wikipedia.org/w/api.php?{params}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


if __name__ == "__main__":
    roles = wikidata_roles()
    print("wikidata roles:", len(roles))
    for b in roles[:3]:
        print(" ", b.get("charLabel", {}).get("value"), "->", b.get("seriesLabel", {}).get("value"))

    for name in ["須磨", "由比ヶ浜結衣", "中川かのん"]:
        print("\nAniList", name)
        try:
            r = anilist_char(name)
            chars = r["data"]["Page"]["characters"]
            for c in chars:
                print(" ", c["name"], c.get("gender"), c.get("age"))
        except Exception as e:
            print("  err", e)

    print("\nWiki search 須磨")
    print(wiki_search("須磨 鬼滅の刃"))
