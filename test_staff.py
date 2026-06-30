import json
import time
import urllib.request

UA = {"User-Agent": "NaoGame/1.0", "Content-Type": "application/json"}


def gql(query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request("https://graphql.anilist.co", data=body, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


# search staff
r = gql("""
query {
  Page(page: 1, perPage: 5) {
    staff(search: "東山奈央") {
      id
      name { native full }
    }
  }
}
""")
print("search", json.dumps(r, ensure_ascii=False, indent=2)[:800])

time.sleep(1.5)

sid = r["data"]["Page"]["staff"][0]["id"]
print("using id", sid)

r2 = gql(
    """
query ($id: Int) {
  Staff(id: $id) {
    id
    name { native }
    characters(perPage: 5, sort: FAVOURITES_DESC) {
      nodes { name { native } age gender }
    }
  }
}
""",
    {"id": sid},
)
print("chars", json.dumps(r2, ensure_ascii=False, indent=2)[:1200])
