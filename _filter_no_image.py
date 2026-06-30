"""Remove characters without a matching PNG in static/."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATIC = BASE / 'static'
JSON_PATH = BASE / 'nao_characters.json'

with open(JSON_PATH, encoding='utf-8') as f:
    chars = json.load(f)

kept = []
removed = []
for c in chars:
  png = STATIC / f"{c['名前']}.png"
  if png.is_file():
    kept.append(c)
  else:
    removed.append(c['名前'])

for i, c in enumerate(kept):
  c['id'] = f'c{i:04d}'
  c['image'] = f"/static/{c['名前']}.png"
  c['has_image'] = True

print(f'Total before: {len(chars)}')
print(f'Kept (has image): {len(kept)}')
print(f'Removed (no image): {len(removed)}')
if removed:
  print('Removed names:')
  for n in removed:
    print(f'  - {n}')

JSON_PATH.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding='utf-8')
print('Updated nao_characters.json')
