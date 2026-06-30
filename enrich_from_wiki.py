"""Parse Toyama Nao filmography from Wikipedia wikitext and merge into nao_characters.json."""
import json
import re
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent
WIKI = BASE / "_wiki.txt"
JSON_IN = BASE / "nao_characters.json"
JSON_OUT = BASE / "nao_characters.json"
BACKUP = BASE / "nao_characters.json.bak"

SECTION_MEDIA = {
    "テレビアニメ": ["TV动画"],
    "OVA": ["OVA"],
    "劇場アニメ": ["电影"],
    "Webアニメ": ["Web动画"],
    "ゲーム": ["游戏"],
    "ドラマCD": ["Drama CD"],
    "ラジオドラマ": ["广播剧"],
    "吹き替え": ["吹替"],
    "テレビドラマ": ["电视剧"],
    "舞台": ["舞台剧"],
    "パチンコ": ["老虎机"],
    "ボイスドラマ": ["Drama CD"],
    "ナレーション": ["朗读剧"],
    "アニメ": ["TV动画"],
    "VOMIC": ["Web动画"],
}

WORK_GENRE_HINTS = [
    (r"プリキュア|光之美少女", ["变身", "战斗", "子供向"]),
    (r"艦これ|舰队", ["战斗", "军事", "科幻"]),
    (r"ラブライブ|偶像大师|アイドル", ["校园", "偶像", "音乐"]),
    (r"ニセコイ|恋愛|婚約|彼女", ["恋爱", "喜剧", "校园"]),
    (r"ゆるキャン|日常|きんいろ", ["日常", "喜剧", "青春"]),
    (r"ゴブリン|オーバーロード|鬼滅|戦姫|魔法少女", ["奇幻", "战斗", "黑暗"]),
    (r"ボルテックス|ロボット|マクロス|機動", ["科幻", "机器人", "战斗"]),
    (r"魔王|異世界|転生|ファンタジー", ["奇幻", "冒险", "喜剧"]),
]

MALE_HINTS = re.compile(
    r"サスケ|幼少|乳児|少年|男子|ゴマちゃん|阿南スガオ|ピポ|カリバーン|ニーちゃん|ボブちゃん|ソウタ"
)
KANMUSU = re.compile(r"艦これ|金剛|比叡|榛名|霧島|高雄|愛宕|摩耶|鳥海|綾波|敷波|Jervis")
NON_HUMAN = [
    (re.compile(r"艦これ|金剛|比叡|榛名|霧島|高雄|愛宕|摩耶|鳥海|綾波|敷波|Jervis"), ["军舰拟人"]),
    (re.compile(r"パフ|妖精|エルフ|魔族|悪魔|ロボ|アンドロイド|AI"), None),
]


def strip_links(text: str) -> str:
    while "[[" in text:
        text = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", text)
    return text


def clean_wiki(text: str) -> str:
    text = strip_links(text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"<ref[^/]*/>", "", text)
    while "{{" in text:
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = text.replace("'''", "").replace("''", "")
    return text.strip()


INVALID = re.compile(r"\[\[|のテレビアニメ|公式サイト|スタッフ|http|{{|}}|Cite |ref>")
ALLOWED_SECTIONS = {
    "テレビアニメ", "劇場アニメ", "OVA", "Webアニメ", "ゲーム",
    "ドラマCD", "吹き替え", "舞台", "パチンコ・パチスロ",
    "オーディオドラマ", "ASMR", "デジタルコミック", "人形劇",
}


def is_valid_name(name: str) -> bool:
    if not name or len(name) < 1 or len(name) > 40:
        return False
    if INVALID.search(name):
        return False
    if name in ("他", "ほか", "など", "他キャラ", "（无名角色）"):
        return False
    return True


def extract_jp_name(display_name: str) -> str:
    m = re.search(r"（([^）]+)）\s*$", display_name)
    if m:
        return m.group(1).split("·")[0].split("/")[0].strip()
    return display_name.split("（")[0].strip()


def normalize_key(name: str, work: str) -> tuple[str, str]:
    jp = extract_jp_name(name)
    jp = re.sub(r"\s+", "", jp)
    work_n = re.sub(r"\s+", "", work)
    return jp, work_n


def guess_genres(work: str) -> list[str]:
    for pat, genres in WORK_GENRE_HINTS:
        if re.search(pat, work, re.I):
            return genres
    return ["动画"]


def guess_race(char: str, work: str) -> list[str]:
    if KANMUSU.search(char) or KANMUSU.search(work):
        return ["军舰拟人"]
    for pat, race in NON_HUMAN:
        if pat.search(char):
            return race or ["人类"]
    return ["人类"]


def guess_gender(char: str) -> list[str]:
    return ["男"] if MALE_HINTS.search(char) else ["女"]


def guess_hair(char: str) -> list[str]:
    for color, keys in [
        ("粉", ["桃", "ピンク", "さくら", "桜"]),
        ("金", ["金", "ブロンド", "イエロー"]),
        ("银", ["銀", "シルバー"]),
        ("蓝", ["青", "ブルー", "アオ"]),
        ("绿", ["緑", "グリーン"]),
        ("红", ["赤", "紅"]),
        ("白", ["白", "ホワイト"]),
        ("紫", ["紫", "パープル"]),
        ("黑", ["黒", "ブラック"]),
        ("褐", ["茶", "ブラウン"]),
    ]:
        if any(k in char for k in keys):
            return [color]
    return ["黑"]


def make_display_name(char_jp: str) -> str:
    char_jp = char_jp.strip()
    if re.search(r"[\u4e00-\u9fff]", char_jp) and not re.search(r"[ぁ-んァ-ン]", char_jp):
        return f"{char_jp}（{char_jp}）"
    return char_jp


def parse_char_block(block: str, default_year: str) -> list[dict]:
    mains = set(re.findall(r"'''([^']+)'''", block))
    block = clean_wiki(block)
    if not block:
        return []

    year = default_year
    chars_part = block

    year_m = re.match(r"^(\d{4})年(?:\s*-\s*\d{4}年)?[、,]?\s*(.*)$", block)
    if year_m:
        year = year_m.group(1)
        chars_part = year_m.group(2)

    chars_part = re.sub(r"\s*-\s*\d+\s*シリーズ.*$", "", chars_part)
    chars_part = re.sub(r"\s*-\s*\d+作品.*$", "", chars_part)
    chars_part = chars_part.strip(" ）)")

    if not chars_part or chars_part in ("-", "―"):
        return []

    names = re.split(r"\s*/\s*|、|,", chars_part)
    results = []
    for raw in names:
        raw = raw.strip()
        if not is_valid_name(raw):
            continue
        raw = re.sub(r"〈[^〉]+〉", "", raw).strip()
        main = raw in mains or raw.replace(" ", "") in {m.replace(" ", "") for m in mains}
        results.append({"name": raw, "year": year, "main": main})
    return results


def parse_wiki_roles(text: str) -> list[dict]:
    m = re.search(r"== 出演 ==(.*?)== ディスコグラフィ ==", text, re.S)
    if not m:
        return []
    filmography = m.group(1)

    roles = []
    sections = re.findall(r"=== (.+?) ===(.*?)(?=\n=== |\Z)", filmography, re.S)
    current_year = "2010"

    for section_title, body in sections:
        if section_title not in ALLOWED_SECTIONS:
            continue
        media = SECTION_MEDIA.get(section_title, ["TV动画"])

        lines = body.split("\n")
        for line in lines:
            line = line.strip()
            if re.match(r"^\|\s*(\d{4})年\s*\|", line):
                current_year = re.match(r"^\|\s*(\d{4})年", line).group(1)
                continue
            if not line.startswith("*"):
                continue

            line = clean_wiki(line.lstrip("* ").strip())
            if not line or INVALID.search(line):
                continue

            work_m = re.match(r"^([^\（(]+)(?:\（([^\）]+)\）|\(([^)]+)\))?", line)
            if not work_m:
                continue
            work = work_m.group(1).strip()
            paren = work_m.group(2) or work_m.group(3) or ""

            if not is_valid_name(work) and len(work) < 2:
                continue
            if INVALID.search(work):
                continue
            if not paren:
                continue

            for item in parse_char_block(paren, current_year):
                roles.append({
                    "work_jp": work,
                    "char_jp": item["name"],
                    "year": item["year"],
                    "main": item["main"],
                    "media": media,
                })
    return roles


def build_work_cn_map(existing: list[dict], roles: list[dict]) -> dict[str, str]:
    jp_to_cn: dict[str, str] = {}
    char_to_work_cn: dict[str, str] = {}
    for c in existing:
        jp = extract_jp_name(c["名前"])
        char_to_work_cn[jp] = c["初登場の作品"]

    for r in roles:
        cn = char_to_work_cn.get(r["char_jp"])
        if cn:
            jp_to_cn[r["work_jp"]] = cn
    return jp_to_cn


WORK_CN_FALLBACK = {
    "神のみぞ知るセカイ": "只有神知道的世界",
    "やはり俺の青春ラブコメはまちがっている。": "我的青春恋爱物语果然有问题",
    "ニセコイ": "伪恋",
    "きんいろモザイク": "黄金拼图",
    "ゆるキャン△": "摇曳露营△",
    "マクロスΔ": "超时空要塞Δ",
    "ゴブリンスレイヤー": "哥布林杀手",
    "青春ブタ野郎シリーズ": "青春猪头少年不会梦到兔女郎学姐",
    "青春ブタ野郎はバニーガール先輩の夢を見ない": "青春猪头少年不会梦到兔女郎学姐",
    "かくりよの宿飯": "鹿枫堂",
    "鬼滅の刃": "鬼灭之刃",
    "鬼滅の刃 ヒノカミ血風譚2": "鬼灭之刃 火之神血风谭2",
    "鬼滅の刃 ヒノカミ血風譚": "鬼灭之刃 火之神血风谭",
    "ようこそ実力至上主義の教室へ": "欢迎来到实力至上主义的教室",
    "彼女、お借りします": "租借女友",
    "カッコウの許嫁": "杜鹃的婚约",
    "艦隊これくしょん -艦これ-": "舰队Collection",
    "アイドルマスター シンデレラガールズ": "偶像大师 灰姑娘女孩",
    "グランブルーファンタジー The Animation": "碧蓝幻想",
    "GATE 自衛隊 彼の地にて、斯く戦えり": "GATE 奇幻自卫队",
    "Go!プリンセスプリキュア": "Go!PRINCESS光之美少女",
    "BEATLESS": "BEATLESS",
    "オーバーロードII": "OVERLORD II",
    "オーバーロード": "OVERLORD",
    "はたらく魔王さま！": "打工吧！魔王大人",
    "はたらく魔王さま!": "打工吧！魔王大人",
    "境界線上のホライゾン": "境界线上的地平线",
    "咲-Saki- シリーズ": "天才麻将少女",
    "咲-Saki-": "天才麻将少女",
    "ラブライブ!": "Love Live!",
    "SHIROBAKO": "SHIROBAKO",
    "はたらく細胞": "工作细胞",
    "Re:ゼロから始める異世界生活": "Re:从零开始的异世界生活",
    "盾の勇者の成り上がり": "盾之勇者成名录",
    "スパイ教室": "间谍教室",
    "名探偵プリキュア!": "名侦探光之美少女",
    "SAKAMOTO DAYS": "坂本日常",
    "合コンに行ったら女がいなかった話": "联谊会上找不到女生",
    "恋する小惑星": "恋爱小行星",
    "SHY": "SHY",
    "スローループ": "慢活开始",
    "この音とまれ！": "一弦定音！",
    "ばくおん!!": "爆音少女!!",
    "色づく世界の明日から": "来自多彩世界的明天",
    "蜘蛛ですが、なにか?": "不过是蜘蛛什么的",
    "機械じかけのマリー": "机械构造的玛丽",
    "愚かな天使は悪魔と踊る": "愚蠢天使与恶魔共舞",
    "声優ラジオのウラオモテ": "声优广播的台前幕后",
    "神クズ☆アイドル": "神废柴☆偶像",
    "ゆびさきと恋々": "指尖相触，恋恋不舍",
    "片田舎のおっさん、剣聖になる": "乡下大叔成为剑圣",
    "いずれ最強の錬金術師?": "终究最强炼金术师？",
    "うたごえはミルフィーユ": "歌声是法式千层酥",
    "阿波連さんははかれない": "不会拿捏距离的阿波连同学",
    "グレンダイザーU": "盖塔机器人U",
    "精霊幻想記": "精灵幻想记",
    "百妖譜": "百妖谱",
    "ドラえもん（テレビ朝日版第2期）": "哆啦A梦",
    "映画ドラえもん のび太の南極カチコチ大冒険": "哆啦A梦 大雄的南极冰冰凉大冒险",
    "フー子": "风子",
    "ユア・フォルマ": "你的形貌",
    "大室家": "大室家",
    "夫婦以上、恋人未満。": "夫妇以上，恋人未满",
    "魔王学院の不適合者": "魔王学院的不适任者",
    "シャングリラ・フロンティア": "香格里拉边境",
    "ダンジョンに出会いを求めるのは間違っているだろうか": "在地下城寻求邂逅是否搞错了什么",
    "ダンまち": "在地下城寻求邂逅是否搞错了什么",
    "僕の心のヤバイやつ": "我心里危险的东西",
    "終末のイゼッタ": "终末的伊泽塔",
    "響け！ユーフォニアム": "吹响吧！上低音号",
    "ワンパンマン": "一拳超人",
    "ワンパンマン3": "一拳超人",
    "薬屋のひとりごと": "药屋少女的呢喃",
    "ダンダダン": "胆大党",
    "青の祓魔師": "青之驱魔师",
    "STAR DRIVER 輝きのタクト": "STAR DRIVER 闪亮的塔科特",
    "異国迷路のクロワーゼ The Animation": "异国迷宫的十字路口",
    "トリニティセブン": "TRINITY SEVEN 七人魔法使",
    "魔法少女育成計画": "魔法少女育成计划",
    "魔法戦争": "魔法战争",
    "落第騎士の英雄譚": "落第骑士英雄谭",
    "学戦都市アスタリスク": "学战都市Asterisk",
    "空戦魔導士候補生の教官": "空战魔导士培训生的教官",
    "みりたり!": "军人少女！",
    "蒼き鋼のアルペジオ -アルス・ノヴァ-": "苍蓝钢铁的琶音",
    "銀河機攻隊 マジェスティックプリンス": "银河机攻战队 Majestic Prince",
    "英雄教室": "英雄教室",
    "この美術部には問題がある!": "这个美术社大有问题！",
    "さばげぶっ!": "生存游戏社",
    "犬神さんと猫山さん": "犬神同学和猫山同学",
    "俺の彼女と幼なじみが修羅場すぎる": "我女友与青梅竹马的惨烈修罗场",
    "THE UNLIMITED 兵部京介": "THE UNLIMITED 兵部京介",
    "たまゆら": "玉响",
    "ココロコネクト": "心灵链环",
    "さくら荘のペットな彼女": "樱花庄的宠物女孩",
    "エウレカセブンAO": "交响诗篇AO",
    "AKB0048": "AKB0048",
    "戦姫絶唱シンフォギア": "战姬绝唱SYMPHOGEAR",
    "ラストエグザイル-銀翼のファム-": "最终流放-银翼之法姆-",
    "アスタロッテのおもちゃ!": "萝黛的后宫玩具",
    "青の祓魔師": "青之驱魔师",
    "BORUTO-ボルト- NARUTO NEXT GENERATIONS": "博人传-火影次世代-",
    "18if": "18if",
    "異世界食堂": "异世界食堂",
    "月がきれい": "月色真美",
    "デビルズライン": "恶魔战线",
    "重神機パンドーラ": "重神机潘多拉",
    "あかねさす少女": "茜色少女",
    "おとなの防具屋さん": "大人的防具店",
    "叛逆性ミリオンアーサー": "叛逆性百万亚瑟王",
    "ラディアン": "虚空魔境",
    "ラクエンロジック": "幸运逻辑",
    "田中くんはいつもけだるげ": "田中君总是如此慵懒",
    "レガリア The Three Sacred Stars": "雷加利亚三圣星",
    "少年アシベ GO! GO! ゴマちゃん": "少年阿贝 GO!GO!小芝麻",
    "NARUTO -ナルト- 疾風伝": "火影忍者疾风传",
    "ノブナガ・ザ・フール": "愚者信长",
    "愛・天地無用!": "爱·天地无用！",
    "ガールフレンド（仮）": "临时女友",
    "クロスアンジュ 天使と竜の輪舞": "Cross Ange",
    "魔法科高校の劣等生": "魔法科高中的劣等生",
    "グラスリップ": "玻璃lip",
    "のうりん": "农林",
    "ロボットガールズZ": "机器人少女Z",
    "幻影ヲ駆ケル太陽": "穿透幻影的太阳",
    "ガリレイドンナ": "伽利略少女",
    "まおゆう魔王勇者": "魔王勇者",
    "パパのいうことを聞きなさい!": "要听爸爸的话！",
    "べるぜバブ": "恶魔奶爸",
    "よんでますよ、アザゼルさん。": "恶魔阿萨谢尔在召唤你",
    "戦国乙女〜桃色パラドックス〜": "战国乙女",
    "閃光のナイトレイド": "闪光夜袭",
    "アイドル事変": "偶像事变",
    "デジモンユニバース アプリモンスターズ": "数码宝贝宇宙 应用怪兽",
    "バトルガール ハイスクール": "战斗女子学园",
    "GRANBLUE FANTASY The Animation": "碧蓝幻想",
    "アイドルマスター シンデレラガールズ劇場": "偶像大师 灰姑娘女孩",
    "天才王子の赤字国家再生術": "天才王子的赤字国家重生术",
    "メルティナ": "盾之勇者成名录",
    "ロウェルミナ": "天才王子的赤字国家重生术",
    "シャングリラ・フロンティア": "香格里拉边境",
    "夫婦以上、恋人未満。": "夫妇以上，恋人未满",
    "ダンジョンに出会いを求めるのは間違っているだろうかV": "在地下城寻求邂逅是否搞错了什么",
}


def work_cn(work_jp: str, mapping: dict[str, str]) -> str:
    if work_jp in mapping:
        return mapping[work_jp]
    if work_jp in WORK_CN_FALLBACK:
        return WORK_CN_FALLBACK[work_jp]
    # longest prefix match — avoid mapping spin-offs to parent title
    best = ""
    best_cn = ""
    for jp, cn in WORK_CN_FALLBACK.items():
        if work_jp.startswith(jp) and len(jp) > len(best):
            best, best_cn = jp, cn
    if best_cn and work_jp == best:
        return best_cn
    simplified = re.sub(r"\s*\d+(?:st|nd|rd|th)?\s*(?:シーズン|Season|期|編|クール).*$", "", work_jp)
    if simplified in WORK_CN_FALLBACK:
        return WORK_CN_FALLBACK[simplified]
    return simplified


def template_entry(role: dict, work_mapping: dict[str, str]) -> dict:
    char = role["char_jp"]
    work = work_cn(role["work_jp"], work_mapping)
    display = make_display_name(char)
    main = role["main"]
    return {
        "名前": display,
        "初登場の作品": work,
        "初登場の年齢": "未知",
        "性別": guess_gender(char),
        "種族": guess_race(char, role["work_jp"]),
        "出身": ["日本", "地球"] if guess_race(char, role["work_jp"]) == ["人类"] else ["日本"],
        "髪色": guess_hair(char),
        "肩書": ["高中生"] if re.search(r"高校|学園|学校|生徒", role["work_jp"] + char) else [],
        "初声出演の年": role["year"],
        "作品ジャンル": guess_genres(role["work_jp"]),
        "出演メディア": role["media"],
        "メインキャラかどうか": "是" if main else "否",
    }


def main():
    text = WIKI.read_text(encoding="utf-8")
    existing = json.loads(JSON_IN.read_text(encoding="utf-8"))
    roles = parse_wiki_roles(text)
    work_mapping = build_work_cn_map(existing, roles)
    work_mapping.update(WORK_CN_FALLBACK)

    existing_keys = {normalize_key(c["名前"], c["初登場の作品"]) for c in existing}
    existing_by_jp = {extract_jp_name(c["名前"]): c for c in existing}

    merged = list(existing)
    added = 0
    for role in roles:
        char_jp = role["char_jp"]
        work = work_cn(role["work_jp"], work_mapping)
        display = make_display_name(char_jp)
        key = normalize_key(display, work)

        if char_jp in existing_by_jp and existing_by_jp[char_jp]["初登場の作品"] == work:
            continue
        if key in existing_keys:
            continue

        entry = template_entry(role, work_mapping)
        # prefer keeping richer manual data if partial match on jp name only
        if char_jp in existing_by_jp:
            old = existing_by_jp[char_jp]
            if old["初登場の作品"] != work:
                merged.append(entry)
                existing_keys.add(key)
                added += 1
            continue

        merged.append(entry)
        existing_keys.add(key)
        added += 1

    merged.sort(key=lambda c: (c["初声出演の年"], c["初登場の作品"], c["名前"]))

    if not BACKUP.exists():
        shutil.copy(JSON_IN, BACKUP)

    JSON_OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Existing: {len(existing)}")
    print(f"Wiki roles parsed: {len(roles)}")
    print(f"Added: {added}")
    print(f"Total: {len(merged)}")


if __name__ == "__main__":
    main()
