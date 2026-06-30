import json
import urllib.request

q = """
query {
  Staff(search: "Toyama Nao", sort: SEARCH_MATCH) {
    nodes {
      id
      name { full native }
      characterMedia(perPage: 5) {
        nodes {
          title { native romaji }
          characters(perPage: 8) {
            nodes { name { native } age gender }
          }
        }
      }
    }
  }
}
"""
body = json.dumps({"query": q}).encode()
req = urllib.request.Request(
    "https://graphql.anilist.co",
    data=body,
    headers={"Content-Type": "application/json", "User-Agent": "NaoGame/1.0"},
)
with urllib.request.urlopen(req, timeout=30) as r:
    d = json.loads(r.read())
staff = d["data"]["Staff"]["nodes"][0]
print("id", staff["id"], staff["name"])
for m in staff["characterMedia"]["nodes"]:
    print("work", m["title"]["native"])
    for c in m["characters"]["nodes"]:
        print(" ", c["name"]["native"], c.get("age"), c.get("gender"))
