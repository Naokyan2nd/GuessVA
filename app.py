import json

import random

import secrets

import time

from pathlib import Path



from flask import Flask, flash, get_flashed_messages, jsonify, redirect, render_template, request, session, url_for



from game_logic import (
    build_indexes,
    compare_hints,
    describe_room_config,
    ensure_character_metadata,
    filter_characters,
    filter_from_config,
    normalize_room_config,
    quality_pool_enabled,
    resolve_character,
    search_characters,
    character_search_payload,
    secret_key,
)



BASE_DIR = Path(__file__).resolve().parent

JSON_PATH = BASE_DIR / 'nao_characters.json'

STATIC_DIR = BASE_DIR / 'static'



app = Flask(__name__)

app.secret_key = secret_key()



with open(JSON_PATH, 'r', encoding='utf-8') as f:

    characters = json.load(f)



if ensure_character_metadata(characters, STATIC_DIR):

    JSON_PATH.write_text(json.dumps(characters, ensure_ascii=False, indent=2), encoding='utf-8')



with open(BASE_DIR / 'similar_attributes.json', 'r', encoding='utf-8') as f:

    相似属性 = json.load(f)



CHAR_BY_ID, NAME_TO_IDS = build_indexes(characters)

ALL_YEARS = [int(char.get('初声出演の年', 0)) for char in characters if char.get('初声出演の年')]

MIN_YEAR = min(ALL_YEARS) if ALL_YEARS else 2010

MAX_YEAR = max(ALL_YEARS) if ALL_YEARS else 2025



ROOM_TTL = 7200

MAX_GUESTS = 8

MP_ROOMS = {}





def _cleanup_rooms():

    now = time.time()

    expired = [code for code, room in MP_ROOMS.items() if now - room['created'] > ROOM_TTL]

    for code in expired:

        MP_ROOMS.pop(code, None)





def get_guess_chance_from_request(req):

    try:

        guess_chance = int(req.cookies.get('guessChance', 10))

        return max(3, min(guess_chance, 20))

    except (ValueError, TypeError):

        return 10





def get_year_range_from_request(req):

    try:

        min_year = int(req.cookies.get('minYear', MIN_YEAR))

        max_year = int(req.cookies.get('maxYear', MAX_YEAR))

        min_year = max(MIN_YEAR, min(min_year, max_year))

        max_year = min(MAX_YEAR, max(min_year, max_year))

        return min_year, max_year

    except (ValueError, TypeError):

        return MIN_YEAR, MAX_YEAR





def get_filtered_characters(req):

    min_year, max_year = get_year_range_from_request(req)

    only_main = req.cookies.get('onlyMain', '0') == '1'

    quality_only = quality_pool_enabled(req)

    pool = filter_characters(

        characters,

        min_year=min_year,

        max_year=max_year,

        only_main=only_main,

        quality_only=quality_only,

    )

    return pool if pool else list(characters)





def get_answer_char():

    answer_id = session.get('answer_id')

    if answer_id:

        return CHAR_BY_ID.get(answer_id)

    answer_name = session.get('answer_name')

    if answer_name:

        return resolve_character(CHAR_BY_ID, NAME_TO_IDS, guess_id=None, guess_name=answer_name)

    return None





def clear_game_session():

    session.pop('answer_id', None)

    session.pop('answer_name', None)

    session.pop('attempts', None)

    session.pop('guessed', None)

    session.pop('closeness', None)





def end_game(answer_char, result_msg):

    session['revealed_answer_id'] = answer_char['id']

    session.pop('answer_id', None)

    session.pop('answer_name', None)

    return result_msg





def start_new_game(filtered_characters):

    session.pop('revealed_answer_id', None)

    session.pop('attempts', None)

    session.pop('guessed', None)

    session.pop('closeness', None)

    answer_char = random.choice(filtered_characters)

    session['answer_id'] = answer_char['id']

    session['answer_name'] = answer_char['名前']

    session['attempts'] = 0

    session['guessed'] = []

    session['closeness'] = {}





def mark_session_modified():

    session.modified = True





def normalize_guessed_ids(guessed, allowed_ids: set[str]) -> list[str]:

    if not guessed:

        return []

    out = []

    for item in guessed:

        if item in CHAR_BY_ID and item in allowed_ids:

            out.append(item)

            continue

        char = resolve_character(

            CHAR_BY_ID, NAME_TO_IDS,

            guess_id=None, guess_name=item, allowed_ids=allowed_ids,

        )

        if char:

            out.append(char['id'])

    return out





def _get_room(code):

    _cleanup_rooms()

    return MP_ROOMS.get(code)





def _get_room_pool(room: dict) -> list[dict]:
    config = room.get('config') or {}
    pool = filter_from_config(characters, config, abs_min_year=MIN_YEAR, abs_max_year=MAX_YEAR)
    return pool if pool else list(characters)


@app.route('/api/search')
def api_search():
    q = request.args.get('q', '')
    room_code = request.args.get('room', '').strip()
    if room_code:
        room = _get_room(room_code)
        pool = _get_room_pool(room) if room else get_filtered_characters(request)
    else:
        pool = get_filtered_characters(request)
    guessed = set(request.args.get('exclude', '').split(',')) - {''}
    results = [
        character_search_payload(c)
        for c in search_characters(pool, q)
        if c['id'] not in guessed
    ]
    return jsonify(results)


@app.route('/api/mp/preview', methods=['POST'])
def mp_preview_pool():
    data = request.get_json(silent=True) or {}
    config = normalize_room_config(data.get('config'), MIN_YEAR, MAX_YEAR)
    pool = filter_from_config(characters, config, abs_min_year=MIN_YEAR, abs_max_year=MAX_YEAR)
    return jsonify(describe_room_config(config, len(pool)))





@app.route('/')
def index():
    default_pool = filter_characters(
        characters,
        min_year=MIN_YEAR,
        max_year=MAX_YEAR,
        only_main=False,
        quality_only=True,
    )
    return render_template(
        'index.html',
        total_chars=len(characters),
        playable_chars=len(default_pool),
    )


@app.route('/solo', methods=['GET', 'POST'])

def solo():

    filtered_characters = get_filtered_characters(request)

    allowed_ids = {c['id'] for c in filtered_characters}

    guess_chance = get_guess_chance_from_request(request)



    if 'answer_id' not in session and 'revealed_answer_id' not in session and 'answer_name' not in session:

        start_new_game(filtered_characters)



    answer = get_answer_char()

    if answer is None and session.get('revealed_answer_id'):

        answer = CHAR_BY_ID.get(session['revealed_answer_id'])

    if answer is None:

        start_new_game(filtered_characters)

        answer = get_answer_char()



    attempts = session.get('attempts', 0)

    guessed = normalize_guessed_ids(session.get('guessed', []), allowed_ids)

    if guessed != session.get('guessed', []):

        session['guessed'] = guessed

        mark_session_modified()

    closeness = session.get('closeness', {})

    result = error = None



    if request.method == 'POST':

        if 'answer_id' not in session:

            return redirect(url_for('solo'))



        if request.form.get('give_up') == '1':

            result = end_game(answer, f"❌ お前はまだまだだ...正解は{answer['名前']}...")

        else:

            guess_id = (request.form.get('guess_id') or '').strip()

            guess_name = (request.form.get('guess_name') or '').strip()

            guessed_char = resolve_character(

                CHAR_BY_ID, NAME_TO_IDS,

                guess_id=guess_id or None,

                guess_name=guess_name or None,

                allowed_ids=allowed_ids,

            )



            if not guess_name and not guess_id:

                error = '❗ キャラ名を入力してください。'

            elif guessed_char is None:

                error = '❗ そのキャラクターは見つかりませんでした。もう一度入力してください。'

            elif guessed_char['id'] in guessed:

                error = f"⚠️  {guessed_char['名前']} はすでに推測されています。別のキャラを試してください。"

            else:

                session['attempts'] = attempts + 1

                attempts = session['attempts']

                guessed = session['guessed']

                guessed.append(guessed_char['id'])

                mark_session_modified()



                if guessed_char['id'] == answer['id']:

                    result = end_game(answer, f'✅ 正解です！正解は{guessed_char["名前"]}！')

                else:

                    closeness = session['closeness']

                    closeness[guessed_char['id']] = compare_hints(guessed_char, answer, 相似属性)

                    mark_session_modified()



                    if attempts >= guess_chance:

                        result = end_game(answer, f"❌ お前はまだまだだ...正解は{answer['名前']}...")



        if error:

            flash(error, 'error')

        if result:

            flash(result, 'result')

        return redirect(url_for('solo'))



    error = result = None

    for category, message in get_flashed_messages(with_categories=True):

        if category == 'error':

            error = message

        elif category == 'result':

            result = message

    answer_exists = 'answer_id' in session



    pool_stats = {

        'total': len(filtered_characters),

        'quality': quality_pool_enabled(request),

    }



    return render_template(

        'guess.html',

        characters=filtered_characters,

        chars_by_id=CHAR_BY_ID,

        error=error,

        result=result,

        attempts=attempts,

        guessed=guessed,

        closeness=closeness,

        answer_exists=answer_exists,

        answer_id=answer['id'],

        answer=answer,

        guess_chance=guess_chance,

        all_characters=characters,

        min_year=MIN_YEAR,

        max_year=MAX_YEAR,

        pool_stats=pool_stats,

    )





@app.route('/restart')

def restart():

    session.pop('revealed_answer_id', None)

    clear_game_session()

    return redirect(url_for('solo'))





@app.route('/multiplayer')

def multiplayer():

    filtered_characters = get_filtered_characters(request)

    return render_template(

        'multiplayer.html',

        characters=characters,

        filtered_characters=filtered_characters,

        similar_attributes=相似属性,

        all_characters=characters,

        min_year=MIN_YEAR,

        max_year=MAX_YEAR,

        join_code=request.args.get('join', ''),

        pool_stats={

            'total': len(filtered_characters),

            'quality': quality_pool_enabled(request),

        },

    )





@app.route('/api/mp/room', methods=['POST'])

def mp_create_room():
    _cleanup_rooms()
    data = request.get_json(silent=True) or {}
    config = normalize_room_config(data.get('config'), MIN_YEAR, MAX_YEAR)
    host_name = (data.get('host_name') or 'ホスト').strip()[:20] or 'ホスト'
    pool = filter_from_config(characters, config, abs_min_year=MIN_YEAR, abs_max_year=MAX_YEAR)
    if not pool:
        return jsonify({'error': '条件に合うキャラがいません。設定を変更してください。'}), 400
    config_info = describe_room_config(config, len(pool))
    for _ in range(20):
        code = f"{random.randint(100000, 999999)}"
        if code not in MP_ROOMS:
            MP_ROOMS[code] = {
                'created': time.time(),
                'host_events': [],
                'guests': {},
                'config': config,
                'config_info': config_info,
                'host_name': host_name,
            }
            return jsonify({
                'room_code': code,
                'config': config_info,
                'host_name': host_name,
            })
    return jsonify({'error': '部屋の作成に失敗しました'}), 500





@app.route('/api/mp/room/<code>/join', methods=['POST'])

def mp_join_room(code):

    room = _get_room(code)

    if not room:

        return jsonify({'error': '部屋が見つかりません'}), 404

    if len(room['guests']) >= MAX_GUESTS:

        return jsonify({'error': '部屋が満員です'}), 403



    data = request.get_json(silent=True) or {}

    player_name = (data.get('player_name') or 'プレイヤー').strip()[:20] or 'プレイヤー'

    guest_id = secrets.token_hex(8)



    room['guests'][guest_id] = {

        'player_name': player_name,

        'signals': [],

        'joined': time.time(),

    }

    room['host_events'].append({

        'type': 'guest_joined',

        'guest_id': guest_id,

        'player_name': player_name,

    })

    return jsonify({
        'guest_id': guest_id,
        'room_code': code,
        'config': room.get('config_info') or describe_room_config(room.get('config', {})),
        'host_name': room.get('host_name', 'ホスト'),
    })





@app.route('/api/mp/room/<code>/signal', methods=['POST'])

def mp_post_signal(code):

    room = _get_room(code)

    if not room:

        return jsonify({'error': '部屋が見つかりません'}), 404



    data = request.get_json(silent=True) or {}

    role = data.get('role')

    guest_id = data.get('guest_id')

    payload = data.get('payload')



    if payload is None:

        return jsonify({'error': 'invalid payload'}), 400



    message = {'type': data.get('type', 'signal'), 'payload': payload, 'ts': time.time()}



    if role == 'host' and guest_id in room['guests']:

        room['guests'][guest_id]['signals'].append(message)

    elif role == 'guest' and guest_id in room['guests']:

        message['guest_id'] = guest_id

        room['host_events'].append(message)

    else:

        return jsonify({'error': 'invalid role'}), 400



    return jsonify({'ok': True})





@app.route('/api/mp/room/<code>/poll')

def mp_poll_signals(code):

    room = _get_room(code)

    if not room:

        return jsonify({'error': '部屋が見つかりません'}), 404



    role = request.args.get('role')

    guest_id = request.args.get('guest_id')



    if role == 'host':

        events = room['host_events'][:]

        room['host_events'].clear()

        guests = [

            {'guest_id': gid, 'player_name': g['player_name']}

            for gid, g in room['guests'].items()

        ]

        return jsonify({
            'events': events,
            'guests': guests,
            'config': room.get('config_info'),
            'host_name': room.get('host_name'),
        })



    if role == 'guest' and guest_id in room['guests']:

        signals = room['guests'][guest_id]['signals'][:]

        room['guests'][guest_id]['signals'].clear()

        return jsonify({
            'signals': signals,
            'config': room.get('config_info'),
            'host_name': room.get('host_name'),
        })



    return jsonify({'error': 'invalid poll'}), 400





@app.route('/api/mp/room/<code>', methods=['DELETE'])

def mp_close_room(code):

    MP_ROOMS.pop(code, None)

    return jsonify({'ok': True})





if __name__ == '__main__':

    app.run(debug=True, host='0.0.0.0', port=5000)


