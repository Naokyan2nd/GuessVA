"""Shared game rules: character metadata, filters, hint comparison."""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path

from character_i18n import display_value

UNKNOWN_AGE = frozenset({'???', '未知', '?', '', None})


def parse_numeric_age(value) -> int | None:
    if value is None:
        return None
    s = str(value).strip()
    if s in UNKNOWN_AGE:
        return None
    m = re.search(r'(\d{1,3})', s)
    if m:
        return int(m.group(1))
    return None


def ensure_character_metadata(characters: list[dict], static_dir: Path) -> bool:
    """Add id / image / has_image / has_age. Returns True if data changed."""
    changed = False
    for i, char in enumerate(characters):
        if 'id' not in char:
            char['id'] = f'c{i:04d}'
            changed = True
        png = static_dir / f"{char['名前']}.png"
        has_image = png.is_file()
        image = f"/static/{char['名前']}.png" if has_image else '/static/char_placeholder.png'
        has_age = parse_numeric_age(char.get('初登場の年齢')) is not None
        for key, val in (('image', image), ('has_image', has_image), ('has_age', has_age)):
            if char.get(key) != val:
                char[key] = val
                changed = True
    return changed


def build_indexes(characters: list[dict]) -> tuple[dict, dict]:
    by_id = {c['id']: c for c in characters}
    by_name: dict[str, list[str]] = defaultdict(list)
    for c in characters:
        names = {c['名前']}
        for localized in c.get('_i18n', {}).values():
            if localized.get('名前'):
                names.add(localized['名前'])
        for name in names:
            by_name[name].append(c['id'])
    return by_id, dict(by_name)


def quality_pool_enabled(req) -> bool:
    return req.cookies.get('qualityPool', '1') == '1'


def filter_from_config(
    characters: list[dict],
    config: dict,
    *,
    abs_min_year: int,
    abs_max_year: int,
) -> list[dict]:
    min_year = max(abs_min_year, int(config.get('minYear', abs_min_year)))
    max_year = min(abs_max_year, int(config.get('maxYear', abs_max_year)))
    if min_year > max_year:
        min_year, max_year = max_year, min_year
    return filter_characters(
        characters,
        min_year=min_year,
        max_year=max_year,
        only_main=bool(config.get('onlyMain')),
        quality_only=bool(config.get('qualityPool', True)),
    )


def normalize_room_config(raw: dict | None, abs_min_year: int, abs_max_year: int) -> dict:
    raw = raw or {}
    try:
        min_year = int(raw.get('minYear', abs_min_year))
        max_year = int(raw.get('maxYear', abs_max_year))
    except (TypeError, ValueError):
        min_year, max_year = abs_min_year, abs_max_year
    min_year = max(abs_min_year, min(min_year, abs_max_year))
    max_year = min(abs_max_year, max(min_year, max_year))
    return {
        'minYear': min_year,
        'maxYear': max_year,
        'onlyMain': bool(raw.get('onlyMain')),
        'qualityPool': raw.get('qualityPool', True) is not False and str(raw.get('qualityPool')) != '0',
    }


def describe_room_config(config: dict, pool_count: int | None = None) -> dict:
    labels = [
        f"初声出演：{config['minYear']}年 ～ {config['maxYear']}年",
        'メインキャラのみ' if config.get('onlyMain') else 'メイン＋サブキャラ',
        '充実データのみ' if config.get('qualityPool') else '全キャラ',
    ]
    if pool_count is not None:
        labels.append(f'候補 {pool_count} キャラ')
    return {
        'minYear': config['minYear'],
        'maxYear': config['maxYear'],
        'onlyMain': config.get('onlyMain', False),
        'qualityPool': config.get('qualityPool', True),
        'poolCount': pool_count,
        'labels': labels,
        'summary': ' · '.join(labels),
    }


def filter_characters(
    characters: list[dict],
    *,
    min_year: int,
    max_year: int,
    only_main: bool,
    quality_only: bool,
) -> list[dict]:
    pool = []
    for char in characters:
        try:
            year = int(char.get('初声出演の年', 0))
        except (TypeError, ValueError):
            continue
        if not (min_year <= year <= max_year):
            continue
        if only_main and char.get('メインキャラかどうか') != '是':
            continue
        if quality_only and not (char.get('has_image') and char.get('has_age')):
            continue
        pool.append(char)
    return pool


def compare_hints(guess_char: dict, answer_char: dict, similar_rules: dict) -> dict:
    closeness = {}
    for key, answer_value in answer_char.items():
        if key in ('名前', 'id', 'image', 'has_image', 'has_age') or key.startswith('_'):
            continue
        guess_value = guess_char.get(key)
        if guess_value is None or answer_value is None:
            continue

        rule = similar_rules.get(key)

        if rule == 'numeric':
            if str(guess_value) == str(answer_value):
                continue
            guess_num = parse_numeric_age(guess_value)
            answer_num = parse_numeric_age(answer_value)
            if guess_num is None or answer_num is None:
                continue
            diff = guess_num - answer_num
            closeness[key] = 'close' if abs(diff) <= 5 else 'far'
            closeness[key + '_arrow'] = '↑' if diff < 0 else '↓'

        elif isinstance(rule, dict):
            if isinstance(guess_value, list) and isinstance(answer_value, list):
                close_list = []
                for g in guess_value:
                    if g in answer_value:
                        continue
                    for a in answer_value:
                        if g in rule.get(a, []) or a in rule.get(g, []):
                            close_list.append(g)
                            break
                if close_list:
                    closeness[key] = close_list
            elif guess_value != answer_value:
                if guess_value in rule.get(answer_value, []) or answer_value in rule.get(guess_value, []):
                    closeness[key] = ['close']
    return closeness


def resolve_character(
    by_id: dict[str, dict],
    by_name: dict[str, list[str]],
    *,
    guess_id: str | None,
    guess_name: str | None,
    allowed_ids: set[str] | None = None,
) -> dict | None:
    if guess_id and guess_id in by_id:
        if allowed_ids is None or guess_id in allowed_ids:
            return by_id[guess_id]

    if not guess_name:
        return None

    ids = by_name.get(guess_name, [])
    if allowed_ids is not None:
        ids = [i for i in ids if i in allowed_ids]
    if len(ids) == 1:
        return by_id[ids[0]]
    return None


def search_characters(pool: list[dict], query: str, limit: int = 20) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    results = []
    for char in pool:
        localized = char.get('_i18n', {})
        searchable = {
            char.get('名前', ''),
            char.get('初登場の作品', ''),
            *(values.get('名前', '') for values in localized.values()),
            *(values.get('初登場の作品', '') for values in localized.values()),
        }
        if any(q in str(value).lower() for value in searchable):
            results.append(char)
            if len(results) >= limit:
                break
    return results


def character_search_payload(char: dict, language: str = 'ja') -> dict:
    return {
        'id': char['id'],
        'name': display_value(char, '名前', char['名前'], language),
        'work': display_value(char, '初登場の作品', char['初登場の作品'], language),
        'image': char.get('image', '/static/char_placeholder.png'),
    }


def migrate_json_file(json_path: Path, static_dir: Path) -> None:
    characters = json.loads(json_path.read_text(encoding='utf-8'))
    if ensure_character_metadata(characters, static_dir):
        json_path.write_text(json.dumps(characters, ensure_ascii=False, indent=2), encoding='utf-8')


def secret_key() -> str:
    return os.environ.get('FLASK_SECRET_KEY', 'dev-only-change-me-in-production')
