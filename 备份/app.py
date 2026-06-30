import json
import random
from flask import Flask, make_response, render_template, request, session, redirect, url_for

app = Flask(__name__)
app.secret_key = 'supersecretkey'

with open('nao_characters.json', 'r', encoding='utf-8') as f:
    characters = json.load(f)
    names = [char['姓名'] for char in characters]

with open('similar_attributes.json', 'r', encoding='utf-8') as f:
    相似属性 = json.load(f)

def 比对结果(guess_char, answer_char):
    closeness = {}

    for key in answer_char.keys():
        guess_value = guess_char.get(key)
        answer_value = answer_char.get(key)

        if guess_value is None or answer_value is None:
            continue

        rule = 相似属性.get(key)

        if rule == "numeric":
            try:
                diff = int(guess_value) - int(answer_value)
                if abs(diff) <= 5:
                    closeness[key] = "close"  
                else:
                    closeness[key] = "far"  

                closeness[key + "_arrow"] = "↑" if diff < 0 else "↓" if diff > 0 else ""
            except ValueError:
                pass 

        elif isinstance(rule, dict):
            if isinstance(guess_value, list) and isinstance(answer_value, list):
                close_list = []
                for g in guess_value:
                    for a in answer_value:
                        if g == a:
                            continue
                        if g in rule.get(a, []) or a in rule.get(g, []):
                            close_list.append(g)
                if close_list:
                    closeness[key] = close_list
            else:
                if guess_value != answer_value:
                    if guess_value in rule.get(answer_value, []) or answer_value in rule.get(guess_value, []):
                        closeness[key] = ["close"]

    return closeness

def get_guess_chance_from_request(request):
    try:
        guess_chance = int(request.cookies.get('guessChance', 10))
        return max(3, min(guess_chance, 20)) 
    except (ValueError, TypeError):
        return 10
    
def filter_characters_by_main(characters, only_main):
    if only_main:
        return [char for char in characters if char.get('是否为主要角色') == '是']
    return characters
    
def get_year_range_from_request(request):
    try:
        min_year = int(request.cookies.get('minYear', 2010))
        max_year = int(request.cookies.get('maxYear', 2025))
        min_year = max(2010, min(min_year, max_year))
        max_year = min(2025, max(min_year, max_year))
        return min_year, max_year
    except (ValueError, TypeError):
        return 2010, 2025


@app.route('/', methods=['GET', 'POST'])
def guess():
    min_year, max_year = get_year_range_from_request(request)
    only_main_cookie = request.cookies.get('onlyMain')
    only_main = (only_main_cookie == '1')

    filtered_characters = [
        char for char in characters
        if min_year <= int(char.get('初配音年份', 0)) <= max_year
    ]

    filtered_characters = filter_characters_by_main(filtered_characters, only_main)

    if not filtered_characters:
        filtered_characters = characters

    filtered_names = [char['姓名'] for char in filtered_characters]

    if request.method == 'GET':
        session.pop('answer', None)
        session.pop('attempts', None)
        session.pop('guessed', None)
        session.pop('closeness', None)

    if 'answer' not in session:
        session['answer'] = random.choice(filtered_characters)
        session['attempts'] = 0
        session['guessed'] = []
        session['closeness'] = {}

    answer = session['answer']
    attempts = session['attempts']
    guessed = session['guessed']
    closeness = session['closeness']
    result = error = None

    guess_chance = get_guess_chance_from_request(request)

    if request.method == 'POST':
        if request.form.get("give_up") == "1":
            result = f"❌ 你还不够单推...正确答案是{answer['姓名']}..."
            session.pop('answer')
        else:
            guess_name = request.form.get('guess_name')

            if guess_name in guessed:
                error = f"⚠️ 你已经猜过 {guess_name} 了，请换一个试试！"
            elif guess_name not in filtered_names:
                error = "❗ 没有这个角色，请重新输入！"
            else:
                session['attempts'] += 1
                attempts = session['attempts']

                guessed.append(guess_name)

                if guess_name == answer['姓名']:
                    result = f'✅ 你答对了！正确答案就是{guess_name}！'
                    session.pop('answer')
                else:
                    guessed_char = next(char for char in filtered_characters if char['姓名'] == guess_name)
                    closeness[guess_name] = 比对结果(guessed_char, answer)

                    if session['attempts'] >= guess_chance:
                        result = f"❌ 你还不够单推..."
                        session.pop('answer')

    answer_exists = 'answer' in session
    answer_name = answer['姓名']

    return render_template(
    'guess.html',
    names=filtered_names,
    characters=filtered_characters,
    error=error,
    result=result,
    attempts=attempts,
    guessed=guessed,
    closeness=closeness,
    answer_exists=answer_exists,
    answer_name=answer_name,
    answer=answer,
    guess_chance=guess_chance
)

@app.route('/restart')
def restart():
    resp = make_response(redirect(url_for('guess')))
    session.pop('answer', None)
    session.pop('attempts', None)
    session.pop('guessed', None)
    session.pop('closeness', None)
    return resp

if __name__ == '__main__':
    app.run(debug=True)