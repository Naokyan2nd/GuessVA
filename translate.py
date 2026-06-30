import json

# 中文前缀到日文前缀的映射
field_mapping = {
    "姓名": "名前",
    "初登场作品名": "初登場の作品",
    "初登场年龄": "初登場の年齢",
    "性别": "性別",
    "种族": "種族",
    "籍贯": "出身",
    "发色": "髪色",
    "身份": "肩書",
    "初配音年份": "初声出演の年",
    "作品类型": "作品ジャンル",
    "配音类型": "出演メディア",
    "是否为主要角色": "メインキャラかどうか"
}

# 输入输出文件路径
input_file = "nao_characters.json"
output_file = "output.json"

# 读取原始 JSON 数据
with open(input_file, "r", encoding="utf-8") as f:
    data = json.load(f)

# 翻译每个条目的键名
translated_data = []
for entry in data:
    translated_entry = {}
    for key, value in entry.items():
        new_key = field_mapping.get(key, key)  # 若未定义翻译则保持原样
        translated_entry[new_key] = value
    translated_data.append(translated_entry)

# 保存到新 JSON 文件
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(translated_data, f, ensure_ascii=False, indent=2)

print("转换完成，已保存到", output_file)
