import json
import time
import urllib.request

UA = {"User-Agent": "NaoGame/1.0", "Content-Type": "application/json"}


def gql(query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request("https://graphql.anilist.co", data=body, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


r = gql(
    """
query {
  Staff(id: 106184) {
    characters(perPage: 3) {
      nodes {
        name { native }
        image { large medium }
      }
    }
  }
}
"""
)
for n in r["data"]["Staff"]["characters"]["nodes"]:
    print(n["name"]["native"], n["image"]["large"])
