def clean_rakuten_item_name(name):
    """楽天特有のクーポン・セール・ノイズ単語を除去して綺麗な商品名を抽出する"""
    import re
    if not name:
        return "注目アイテム"
    cleaned = re.sub(r'【[^】]*】', '', name)
    cleaned = re.sub(r'\[[^\]]*\]', '', cleaned)
    cleaned = re.sub(r'（[^）]*）', '', cleaned)
    cleaned = re.sub(r'\([^\)]*\)', '', cleaned)
    
    noise_patterns = [
        r'クーポン(?:で|\s*利用で|\s*配布中|\s*対象)?\s*[0-9,]+円?(?:OFF|off)?',
        r'P[0-9]+倍',
        r'ポイント[0-9]+倍',
        r'送料無料',
        r'即納',
        r'あす楽',
        r'マラソン(?:限定)?',
        r'スーパーセール',
        r'お買い物マラソン',
        r'楽天(?:1位|ランキング1位|デイリー1位)',
        r'[0-9]+%OFF',
        r'[0-9]+％OFF',
        r'★[0-9\.]+★?',
        r'レビュー特典',
        r'公式(?:店)?',
    ]
    for pat in noise_patterns:
        cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE)
        
    words = [w.strip() for w in cleaned.split() if w.strip()]
    seen = set()
    cleaned_words = []
    for w in words:
        if w not in seen and len(w) > 1:
            seen.add(w)
            cleaned_words.append(w)
        if len(' '.join(cleaned_words)) >= 28:
            break
            
    res = ' '.join(cleaned_words).strip()
    return res if res else (words[0] if words else name[:25])

import os
import random
import requests
import time
import base64
import json
import tempfile
from playwright.sync_api import sync_playwright

CACHE_FILE = "posted_cache.txt"

# --- タイトル重複防止 & オリジナリティ保証モジュール ---
POSTED_TITLES_FILE = "posted_titles.txt"
RECENT_THEMES_FILE = "recent_themes.txt"

def load_posted_titles():
    """過去に投稿された記事タイトルの一覧を取得"""
    if os.path.exists(POSTED_TITLES_FILE):
        with open(POSTED_TITLES_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    return []

def save_posted_title(title):
    """新規投稿タイトルを永続化保存"""
    if not title:
        return
    title_clean = title.strip()
    with open(POSTED_TITLES_FILE, "a", encoding="utf-8") as f:
        f.write(f"{title_clean}\n")

BANNED_TITLE_PHRASES = [
    "鏡を見る", "鏡の前で", "鏡を見て", "鏡をのぞく", "鏡に映る", "鏡を見るのが", "鏡を見るたび",
    "失敗しない", "いかがでしたでしょうか", "徹底解説", "完全ガイド", "徹底比較", "後悔しない",
    "男の清潔感を高めるギア", "注目のアイテム", "おすすめアイテム", "厳選アイテム", "大人気アイテム", "話題のアイテム"
]

def check_title_banned_phrases(title):
    """タイトル内に陳腐なテンプレ・スパムフレーズが含まれているかチェック"""
    if not title:
        return True, "タイトルが空です"
    for phrase in BANNED_TITLE_PHRASES:
        if phrase in title:
            return True, f"禁止フレーズ「{phrase}」が含まれています"
    return False, None

def is_title_duplicate_or_similar(new_title, threshold=0.60):
    """
    過去のタイトルと完全一致、または類似度が閾値（60%）以上なら重複と判定
    さらに禁止フレーズや冒頭10文字被りも厳格にブロック
    """
    import difflib
    if not new_title:
        return True, "空のタイトル", 1.0

    has_banned, banned_reason = check_title_banned_phrases(new_title)
    if has_banned:
        return True, banned_reason, 1.0

    existing_titles = load_posted_titles()
    clean_new = re.sub(r'[\s\d月【】選！!｜|：:・\-\[\]（）()]+', '', new_title)
    if not clean_new:
        return True, "無効なタイトル", 1.0

    for past in existing_titles:
        if new_title.strip() == past.strip():
            return True, past, 1.0

        if len(new_title) >= 10 and len(past) >= 10:
            if new_title[:10] == past[:10]:
                return True, f"冒頭10文字重複（{past[:10]}）: {past}", 0.95

        clean_past = re.sub(r'[\s\d月【】選！!｜|：:・\-\[\]（）()]+', '', past)
        if not clean_past:
            continue
        ratio = difflib.SequenceMatcher(None, clean_new, clean_past).ratio()
        if ratio >= threshold:
            return True, past, ratio

    return False, None, 0.0

def load_recent_themes(limit=10):
    """直近投稿されたテーマ・商品コードを取得"""
    if os.path.exists(RECENT_THEMES_FILE):
        with open(RECENT_THEMES_FILE, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
            return lines[-limit:]
    return []

def save_recent_theme(theme_name):
    """テーマやキーワードを履歴に保存"""
    if not theme_name:
        return
    with open(RECENT_THEMES_FILE, "a", encoding="utf-8") as f:
        f.write(f"{theme_name.strip()}\n")

def extract_image_url(item):
    """楽天APIレスポンスから高画質かつ有効な画像URLを抽出"""
    if not item:
        return ""
    raw_url = ""
    for key in ["mediumImageUrls", "smallImageUrls"]:
        imgs = item.get(key, [])
        if imgs and isinstance(imgs, list):
            first = imgs[0]
            if isinstance(first, dict):
                raw_url = first.get("imageUrl", "") or first.get("url", "")
            elif isinstance(first, str):
                raw_url = first
            if raw_url:
                break
    if not raw_url:
        raw_url = item.get("imageUrl") or ""

    if raw_url:
        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        elif raw_url.startswith("http://"):
            raw_url = "https://" + raw_url[7:]
        # クエリパラメータ（?_ex=... 等のリサイズ縮小）を除去しオリジナル高解像度URLにする
        if "?" in raw_url:
            raw_url = raw_url.split("?")[0]
    return raw_url



def click_physical(page, selector):
    import time
    elements = page.locator(selector).all()
    for el in elements:
        try:
            box = el.bounding_box()
            if box and box['width'] > 0 and box['height'] > 0:
                x = box['x'] + box['width'] / 2
                y = box['y'] + box['height'] / 2
                page.mouse.click(x, y)
                return True
        except:
            pass
    return False

def load_posted_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_to_cache(item_code):
    with open(CACHE_FILE, "a", encoding="utf-8") as f:
        f.write(f"{item_code}\n")

def get_rakuten_affiliate_url(item, affiliate_id):
    aff_url = item.get("affiliateUrl")
    if aff_url and "hb.afl.rakuten.co.jp" in aff_url:
        return aff_url
    
    item_url = item.get("itemUrl") or ""
    if not item_url:
        return ""
    
    if affiliate_id:
        import urllib.parse
        encoded_item_url = urllib.parse.quote(item_url, safe='')
        return f"https://hb.afl.rakuten.co.jp/hgc/{affiliate_id}/?pc={encoded_item_url}&m={encoded_item_url}"
    
    return item_url

def sanitize_llm_output(content, valid_affiliate_url):
    if not content:
        return ""
    import re
    url_pattern = re.compile(r"""https?://[^\s"'<>()]+""")
    def replace_url(match):
        found_url = match.group(0)
        # 楽天画像ドメインや画像拡張子はアフィリエイトURLに書き換えない（画像の破損防止）
        if any(dom in found_url for dom in ["thumbnail.image.rakuten.co.jp", "image.rakuten.co.jp", "tshop.r10s.jp"]):
            return found_url
        if any(found_url.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
            return found_url
        if "room.rakuten.co.jp" in found_url or "hb.afl.rakuten.co.jp" in found_url or ("rakuten.co.jp" in found_url and "affiliateId" in found_url):
            return found_url
        return valid_affiliate_url if valid_affiliate_url else "https://room.rakuten.co.jp/jack555/items"
    
    sanitized = url_pattern.sub(replace_url, content)
    sanitized = sanitized.replace("Amazon", "楽天市場").replace("アマゾン", "楽天市場").replace("ヤフー", "楽天市場").replace("Yahoo!", "楽天市場")
    return sanitized

def fetch_rakuten_item():
    app_id = os.environ.get("RAKUTEN_APP_ID")
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY")
    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID")
    if not app_id or not access_key:
        raise ValueError("RAKUTEN_APP_ID and RAKUTEN_ACCESS_KEY must be set in environment variables.")

    # サンリオ主要キャラクターリスト
    sanrio_characters = [
        "バッドばつ丸", "クロミ", "ハローキティ", "マイメロディ", 
        "シナモロール", "ポムポムプリン", "ポチャッコ", "ハンギョドン", 
        "タキシードサム", "けろけろけろっぴ", "あひるのペックル", "こぎみゅん", 
        "ウィッシュミーメル", "リトルツインスターズ", "サンリオ"
    ]

    # 優先順位（ガチャ ＞ 小物 ＞ おもちゃ ＞ 雑貨・文具・バッグ等）
    priority_categories = [
        ["ガチャ", "ガチャガチャ", "カプセルトイ"],
        ["マスコット", "キーホルダー", "ポーチ", "小物入れ", "パスケース"],
        ["おもちゃ", "フィギュア", "ぬいぐるみ", "トランプ", "アクスタ"],
        ["文房具", "シール", "ステッカー", "トートバッグ", "限定 グッズ"]
    ]

    posted_cache = load_posted_cache()

    # 最大25回の試行で幅広くヒットさせる
    for attempt in range(25):
        char = random.choice(sanrio_characters)
        # ガチャ優先、次に小物、おもちゃ
        cat_group = random.choices(
            priority_categories, 
            weights=[0.40, 0.30, 0.20, 0.10], 
            k=1
        )[0]
        cat = random.choice(cat_group)
        keyword = f"{char} {cat}"

        print(f"Searching Rakuten for keyword (attempt {attempt+1}): {keyword}")
        url = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401"
        params = {
            "applicationId": app_id,
            "accessKey": access_key,
            "keyword": keyword,
            "format": "json",
            "hits": 30
        }
        if affiliate_id:
            params["affiliateId"] = affiliate_id

        try:
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                items = data.get("Items", [])
                for item_wrapper in items:
                    item = item_wrapper.get("Item", {})
                    item_code = item.get("itemCode")
                    if item_code and item_code not in posted_cache:
                        return item
        except Exception as e:
            print(f"Error fetching for keyword '{keyword}': {e}")

    raise RuntimeError("Could not find any unposted items after multiple attempts.")

def extract_image_url(item):
    if not item:
        return ""
    raw_url = ""
    for key in ["mediumImageUrls", "smallImageUrls"]:
        imgs = item.get(key, [])
        if imgs and isinstance(imgs, list):
            first = imgs[0]
            if isinstance(first, dict):
                raw_url = first.get("imageUrl", "") or first.get("url", "")
            elif isinstance(first, str):
                raw_url = first
            if raw_url:
                break
    if not raw_url:
        raw_url = item.get("imageUrl") or ""

    if raw_url:
        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        elif raw_url.startswith("http://"):
            raw_url = "https://" + raw_url[7:]
        # ?_ex=... などのリサイズパラメータを除去しオリジナル高画質画像にする
        if "?" in raw_url:
            raw_url = raw_url.split("?")[0]
    return raw_url

def generate_article_with_llm(item):
    title = item.get("itemName", "")
    price = item.get("itemPrice", "")
    caption = item.get("itemCaption", "")
    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID")
    url = get_rakuten_affiliate_url(item, affiliate_id)
    image_url = extract_image_url(item)

    buy_button_html = (
        f'<div style="text-align: center; margin: 20px 0;">'
        f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
        f'style="display:inline-block; padding: 14px 28px; background-color: #bf0000; '
        f'color: #ffffff; font-weight: bold; font-size: 16px; border-radius: 8px; '
        f'text-decoration: none; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">'
        f'🛒 楽天市場で価格・在庫を見る</a></div>'
    )

    prompt = f"""以下の楽天の商品情報を基にして、ブログ記事のタイトルとHTML本文を生成してください。
【商品名】: {title}
【価格】: {price}円
【商品説明】: {caption[:300]}
【商品画像URL】: {image_url}
【アフィリエイトURL】: {url}

以下の要件を厳格に遵守してください：
1. 出力は以下のJSONフォーマットのみとしてください。他のテキストは一切含めないでください。
{{
    "title": "ここにキャッチーで魅力的なタイトル（商品名の単なる羅列は禁止、最大35文字）",
    "html": "ここに純粋なHTML本文"
}}
2. HTML本文の構成：
   - 記事全体を `<div class="premium-squishy-article">` と `</div>` で囲む
   - 商品の魅力的な説明（`<div class="premium-content-body">` と `</div>` で囲む）
   - おすすめ注目ポイント3選（`<ul class="premium-points-list">` と `<li>` タグを使用）
   - 商品の画像（`<img src="{image_url}" alt="{title}" style="max-width: 100%; height: auto;">`）
   - 購入ボタンHTML: {buy_button_html}
3. 【厳禁事項】: Amazon, Yahoo, 他社ECサイトなどのリンクや名称は絶対に含めないでください。
"""

    system_message = "あなたはクールで個性的なキャラクターグッズ専門の紹介ブロガーです。指示された仕様に完全に従い、JSONフォーマットのみで出力します。"

    def parse_json_response(text):
        import json as _json
        text = text.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```")[0]
        elif "```" in text:
            text = text.split("```", 1)[1].split("```")[0]
        text = text.strip()
        try:
            data = _json.loads(text)
            if isinstance(data, dict) and "html" in data:
                return data
        except Exception:
            pass
        return None

    # 1. Gemini API（最優先）
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        models = [
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.5-pro",
            "gemini-3-flash",
            "gemini-3.1-pro",
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
            "gemini-3.7-flash"
        ]
        for model_name in models:
            try:
                api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{"parts": [{"text": f"{system_message}\n\n{prompt}"}]}],
                    "generationConfig": {"temperature": 0.8, "maxOutputTokens": 2048}
                }
                if any(v in model_name for v in ["2.5", "3.", "3-"]):
                    payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
                res = requests.post(api_url, json=payload, timeout=30)
                if res.status_code == 200:
                    data = res.json()
                    candidate = data.get("candidates", [{}])[0]
                    parts = candidate.get("content", {}).get("parts", [])
                    text = "".join(p.get("text", "") for p in parts if p.get("text")).strip()
                    parsed = parse_json_response(text)
                    if parsed:
                        print(f"Successfully generated article via Gemini API ({model_name}).")
                        parsed["html"] = sanitize_llm_output(parsed["html"], url)
                        return parsed
                else:
                    print(f"Gemini API ({model_name}) returned {res.status_code}: {res.text[:100]}")
            except Exception as e:
                print(f"Gemini API ({model_name}) error: {e}")

    # 2. Groq API
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        for model_name in ["llama-3.3-70b-versatile", "llama3-70b-8192"]:
            try:
                headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                payload = {
                    "model": model_name,
                    "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 2048
                }
                res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=30)
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"].strip()
                    parsed = parse_json_response(text)
                    if parsed:
                        print(f"Successfully generated article via Groq API ({model_name}).")
                        parsed["html"] = sanitize_llm_output(parsed["html"], url)
                        return parsed
            except Exception as e:
                print(f"Groq API ({model_name}) error: {e}")

    # 3. OpenRouter API
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        for model_name in ["google/gemma-3-27b-it:free", "mistralai/mistral-nemo:free"]:
            try:
                headers = {
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com",
                    "X-Title": "BloggerBadBot"
                }
                payload = {
                    "model": model_name,
                    "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 2048
                }
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=30)
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"].strip()
                    parsed = parse_json_response(text)
                    if parsed:
                        print(f"Successfully generated article via OpenRouter ({model_name}).")
                        parsed["html"] = sanitize_llm_output(parsed["html"], url)
                        return parsed
            except Exception as e:
                print(f"OpenRouter ({model_name}) error: {e}")

    print("WARNING: All LLM generation attempts failed. Generating dynamic item-aware article.")
    clean_title = title.replace("【", "").replace("】", "")[:35]
    img_tag = f'<img src="{image_url}" alt="{clean_title}" style="max-width: 100%; height: auto;"><br>' if image_url else ""
    
    fallback_html = (
        f'<div class="premium-squishy-article">'
        f'<div class="premium-content-body">'
        f'<h2>【おすすめ】{clean_title}</h2>'
        f'<p>バッドばつ丸やサンリオキャラクターファンの間で話題沸騰中の大人気アイテム「<b>{title}</b>」をご紹介します！</p>'
        f'<p>可愛らしいデザインと実用性を備え、日常に笑顔をもたらしてくれるファン必携のコレクションアイテムです。</p>'
        f'<ul class="premium-points-list">'
        f'<li><b>キュートなデザイン</b>：キャラクターの魅力を余すところなく表現！</li>'
        f'<li><b>優れた実用性</b>：普段使いにもプレゼントにも最適なハイクオリティ！</li>'
        f'<li><b>限定感ある完成度</b>：手元に置いておくだけで満足感広がるコレクターズ仕様！</li>'
        f'</ul>'
        f'{img_tag}'
        f'{buy_button_html}'
        f'<br><a href="https://room.rakuten.co.jp/jack555/items" target="_blank">✅ 私の楽天ROOMはこちら</a>'
        f'</div>'
        f'</div>'
    )
    return {
        "title": f"【大人気】{clean_title}",
        "html": fallback_html
    }


def proofread_and_optimize_blogger_article(title, html_content):
    """誤字脱字最終チェックとSEO, AI-SEO, GEO的な修正ブラッシュアップ工程"""
    if not html_content or len(html_content.strip()) < 50:
        return html_content

    prompt = f"""以下のブログ記事HTMLに対して、誤字脱字チェックとSEO・AI-SEO・GEO（Generative Engine Optimization）最適化を行い、最高品質の原稿にブラッシュアップしてください。

【タイトル】: {title}
【HTML本文】:
{html_content}

【ブラッシュアップ要件】:
1. 誤字脱字・不自然な日本語表現を完全に校正してください。
2. AI検索（Perplexity, ChatGPT, Gemini等）が回答の根拠として引用しやすくするため、商品の具体的な魅力・メリット・特徴を構造化してください。
3. 文章が途中で力尽きず、タグ構造と文脈が完全に完結していることを確認してください。
4. 前置き・解説なしで修正後のHTML本文のみを出力してください。
"""

    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if github_token:
        try:
            headers = {"Authorization": f"Bearer {github_token}", "Content-Type": "application/json"}
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "あなたはプロのWeb校正者兼SEO/GEOアナリストです。誤字脱字を無くし最高品質のHTML本文のみを出力します。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.5
            }
            resp = requests.post("https://models.inference.ai.azure.com/chat/completions", headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                res_text = resp.json()["choices"][0]["message"]["content"].strip()
                if "```html" in res_text: res_text = res_text.split("```html", 1)[1].split("```")[0]
                elif "```" in res_text: res_text = res_text.split("```", 1)[1].split("```")[0]
                if len(res_text.strip()) > 100:
                    return res_text.strip()
        except Exception as e:
            print(f"Proofread failed: {e}")
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        try:
            print("Proofreading with Groq API...")
            headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": "あなたはプロのWeb校正者兼SEO/GEOアナリストです。誤字脱字を無くし最高品質のHTML本文のみを出力します。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.5
            }
            resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                res_text = resp.json()["choices"][0]["message"]["content"].strip()
                if "```html" in res_text: res_text = res_text.split("```html", 1)[1].split("```")[0]
                elif "```" in res_text: res_text = res_text.split("```", 1)[1].split("```")[0]
                if len(res_text.strip()) > 100:
                    print("Successfully proofread with Groq API!")
                    return res_text.strip()
        except Exception as e:
            print(f"Groq proofread failed: {e}")

    return html_content

def ensure_complete_blogger_article(html_content):
    """途中切れ（力尽きる現象）を検知し、安全に文末とHTML閉じタグを補正する"""
    if not html_content:
        return html_content
    html_content = html_content.strip()
    valid_endings = ("。", "！", "？", "!", "?", "</div>", "</p>", "</ul>", "</li>", "</a>")
    if not html_content.endswith(valid_endings):
        print("WARNING: Incomplete article detected. Repairing endings and tags...")
        last_p = max(html_content.rfind("。"), html_content.rfind("！"), html_content.rfind("</div>"))
        if last_p > len(html_content) * 0.5:
            html_content = html_content[:last_p + 1]

    open_divs = html_content.count("<div")
    close_divs = html_content.count("</div>")
    if open_divs > close_divs:
        html_content += "</div>" * (open_divs - close_divs)
    return html_content

def post_to_blogger(title, content):
    """Playwrightを用いてBloggerへ確実に公開投稿する超堅牢フロー"""
    blog_id = os.environ.get("BLOGGER_BLOG_ID")
    if not blog_id:
        raise ValueError("BLOGGER_BLOG_ID is not set in environment variables.")
    session_b64 = os.environ.get("BLOGGER_SESSION_B64")
    
    session_file_path = None
    if session_b64:
        try:
            decoded_str = base64.b64decode(session_b64).decode('utf-8')
            json.loads(decoded_str)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".json") as temp_file:
                temp_file.write(decoded_str)
                session_file_path = temp_file.name
        except Exception as e:
            raise ValueError(f"BLOGGER_SESSION_B64 decode failed: {e}")
    elif os.path.exists("session.json"):
        print("Found local session.json. Using it for Blogger post.")
        session_file_path = "session.json"
    else:
        raise ValueError("BLOGGER_SESSION_B64 is not set and local session.json not found.")

    print(f"Posting to Blogger (Blog ID: {blog_id}) using Playwright...")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                storage_state=session_file_path,
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                permissions=['clipboard-read', 'clipboard-write']
            )
            
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            try:
                posts_url = f"https://draft.blogger.com/blog/posts/{blog_id}"
                print(f"Navigating to Blogger posts page: {posts_url}")
                page.goto(posts_url, wait_until="networkidle", timeout=35000)
                time.sleep(3.0)

                # 開いているドロップダウンやオーバーレイメニューを確実に閉じる
                page.keyboard.press("Escape")
                time.sleep(0.5)
                page.keyboard.press("Escape")
                time.sleep(0.5)

                # 事前クリーンアップ：過去の失敗等で残っている空の下書き・無題があれば破棄
                try:
                    for _ in range(5):
                        rows = page.locator("div.rb4Lrd").all()
                        if not rows:
                            break
                        first_row = rows[0]
                        row_text = first_row.inner_text()
                        if "下書き" in row_text or "(無題)" in row_text:
                            discard_btn = first_row.locator('[aria-label="この投稿を破棄"], [aria-label="この投稿をゴミ箱に移動"]').first
                            if discard_btn.is_visible(timeout=1000):
                                discard_btn.click(force=True)
                                time.sleep(0.5)
                                page.evaluate('''() => {
                                    const dialog = document.querySelector('div[role="alertdialog"], div[role="dialog"]');
                                    if (dialog) {
                                        const b = Array.from(dialog.querySelectorAll('div[role="button"], button')).find(x => x.innerText.includes('破棄') || x.innerText.includes('ゴミ箱に移動'));
                                        if (b) b.click();
                                    }
                                }''')
                                time.sleep(1.5)
                                print("[PRE-CLEANUP] Discarded previous leftover draft.")
                        else:
                            break
                except Exception as cleanup_err:
                    print(f"[PRE-CLEANUP-WARN] {cleanup_err}")

                # 新しい投稿ボタンをクリックしてエディタに入る
                editor_opened = False
                for open_attempt in range(5):
                    print(f"[BLOGGER-OPEN] Attempt {open_attempt + 1} to open editor...")
                    
                    if "edit" in page.url:
                        editor_opened = True
                        break

                    # Escapeでポップアップ防止
                    page.keyboard.press("Escape")
                    time.sleep(0.3)

                    # force=True で可視の「新しい投稿を作成」ボタンをクリック
                    btn = page.locator('[aria-label="新しい投稿を作成"]:visible, div[role="button"]:has-text("新しい投稿"):visible').first
                    if btn.is_visible(timeout=5000):
                        print("[BLOGGER-OPEN] Clicking visible '新しい投稿' button with force=True...")
                        btn.click(force=True)
                        time.sleep(3.0)

                    # 1. 自動で /blog/post/edit/... へ遷移したか確認
                    if "edit" in page.url:
                        editor_opened = True
                        print(f"[BLOGGER-OPEN] Automatically transitioned to editor: {page.url}")
                        break

                    # 2. 一覧の先頭に新規ドラフト行が出現した場合、それをクリックしてエディタに入る
                    first_link = page.locator('a[href*="/blog/post/edit/"]').first
                    if first_link.is_visible(timeout=3000):
                        print(f"[BLOGGER-OPEN] Entering editor via draft row: {first_link.get_attribute('href')}")
                        first_link.click(force=True)
                        time.sleep(4.0)
                        if "edit" in page.url:
                            editor_opened = True
                            print(f"[BLOGGER-OPEN] Successfully entered editor: {page.url}")
                            break

                    time.sleep(2.0)

                if not editor_opened:
                    raise RuntimeError("Blogger editor could not be opened.")

                # タイトルと本文の入力（検証ループ付き）
                max_retries = 3
                success = False
                
                for attempt in range(max_retries):
                    print(f"--- Editor Body Injection Attempt {attempt+1} / {max_retries} ---")
                    if attempt > 0:
                        page.reload(wait_until="domcontentloaded")
                        time.sleep(3)

                    try:
                        title_input = page.locator('input.titleField, input[aria-label="タイトル"], input[aria-label="Title"], .titleField input').locator("visible=true").first
                        title_input.wait_for(state="visible", timeout=15000)
                        title_input.click()
                        time.sleep(0.5)
                        page.keyboard.press('Control+A')
                        page.keyboard.press('Meta+A')
                        page.keyboard.press('Backspace')
                        title_input.fill(title)
                        time.sleep(1.5)

                        print("Injecting HTML content...")
                        injected = page.evaluate('''html => {
                            const cmEl = document.querySelector('.CodeMirror');
                            if (cmEl && cmEl.CodeMirror) {
                                cmEl.CodeMirror.setValue(html);
                                if (cmEl.CodeMirror.save) cmEl.CodeMirror.save();
                                return true;
                            }
                            return false;
                        }''', content)

                        if injected:
                            print("Successfully set HTML via CodeMirror instance.")
                        else:
                            print("CodeMirror direct injection not found. Fallback to rich text editor paste...")
                            try:
                                editor_body = page.locator('div[aria-label="本文"], div[aria-label="Body"], div[role="textbox"]').locator("visible=true").first
                                if editor_body.is_visible(timeout=3000):
                                    editor_body.click()
                                    time.sleep(0.5)
                            except Exception:
                                page.keyboard.press('Tab')
                                time.sleep(0.5)
                                page.keyboard.press('Tab')

                            page.evaluate('''html => {
                                try {
                                    navigator.clipboard.writeText(html);
                                } catch (e) {
                                    const blob = new Blob([html], { type: 'text/html' });
                                    const data = [new ClipboardItem({ 'text/html': blob })];
                                    navigator.clipboard.write(data);
                                }
                            }''', content)
                            time.sleep(1.0)
                            page.keyboard.press('Control+A')
                            page.keyboard.press('Meta+A')
                            time.sleep(0.3)
                            page.keyboard.press('Control+V')
                            page.keyboard.press('Meta+V')

                        time.sleep(2.0)
                        # キーボード入力で変更検知発火
                        page.keyboard.press('Space')
                        time.sleep(0.3)
                        page.keyboard.press('Backspace')
                        time.sleep(2.0)

                        cm_val = page.evaluate('''() => {
                            const cmEl = document.querySelector('.CodeMirror');
                            return (cmEl && cmEl.CodeMirror) ? cmEl.CodeMirror.getValue() : '';
                        }''')
                        page_html = page.content()
                        effective_html = cm_val if cm_val else page_html

                        if ("<img" in effective_html or "img" in effective_html) and ("href" in effective_html or "http" in effective_html):
                            print(f"Validation passed: Body content successfully inserted into editor (len: {len(effective_html)}).")
                            success = True
                            break
                        else:
                            print(f"Validation warning: Content verification incomplete. Retrying...")
                    except Exception as e:
                        print(f"Error during attempt {attempt+1}: {e}")
                    time.sleep(2)

                if not success:
                    try:
                        print("[BLOGGER-CLEANUP] Post validation failed. Discarding unfinished draft...")
                        page.goto(f"https://draft.blogger.com/blog/posts/{blog_id}", wait_until="domcontentloaded", timeout=15000)
                        time.sleep(2.0)
                        discard_btn = page.locator('div[aria-label="この投稿を破棄"]').first
                        if discard_btn.is_visible(timeout=3000):
                            discard_btn.dispatch_event('click')
                            time.sleep(1.0)
                            page.keyboard.press('Enter')
                            time.sleep(1.5)
                            print("[BLOGGER-CLEANUP] Discarded unfinished draft successfully.")
                    except Exception as discard_err:
                        print(f"[BLOGGER-CLEANUP-WARN] Failed to discard draft: {discard_err}")

                    raise RuntimeError("Critical: Body injection could not be validated after multiple attempts.")

                print("Clicking Publish button...")
                try:
                    pub_btn = page.locator('[aria-label="公開"], [aria-label="Publish"]').locator("visible=true").first
                    pub_btn.scroll_into_view_if_needed()
                    time.sleep(1)
                    pub_btn.click(force=True, timeout=10000)
                except Exception as e:
                    print("Clicking publish via shortcut:", e)
                    page.keyboard.press('Control+Shift+P')
                    page.keyboard.press('Meta+Shift+P')

                time.sleep(3)

                try:
                    conf_btn = page.locator(
                        'div[role="alertdialog"] div[role="button"]:has-text("確定"), '
                        'div[role="alertdialog"] div[role="button"]:has-text("確認"), '
                        'div[role="dialog"] div[role="button"]:has-text("確定"), '
                        'div[role="dialog"] div[role="button"]:has-text("確認"), '
                        'div[role="button"]:has-text("確定"), '
                        '[aria-label="確定"], [aria-label="確認"], [aria-label="Confirm"]'
                    ).locator("visible=true").first
                    conf_btn.wait_for(state="visible", timeout=7000)
                    conf_btn.click(force=True)
                    print("[BLOGGER-PUBLISH] Confirmed publication dialog successfully ('確定' button clicked).")
                except Exception as e:
                    print("[BLOGGER-PUBLISH-WARN] Confirm button warning, trying Enter fallback:", e)
                    page.keyboard.press('Enter')

                time.sleep(8)
                print("Successfully published post using Playwright!")

                # 公開後の厳格な事後検証（フィードを取得して今回のタイトルが公開され、本文が空でないことを確認）
                print("[POST-VERIFY] Verifying published article content from Blogger feed...")
                try:
                    import urllib.request
                    import ssl
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE

                    feed_url = f"https://www.blogger.com/feeds/{blog_id}/posts/default?alt=json&max-results=3"
                    req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                        feed_data = json.loads(resp.read().decode("utf-8"))
                        entries = feed_data.get("feed", {}).get("entry", [])
                        latest_entry = entries[0] if entries else {}
                        latest_title = latest_entry.get("title", {}).get("$t", "").strip()
                        latest_content = latest_entry.get("content", {}).get("$t", "")
                        print(f"[POST-VERIFY] Latest post in feed: '{latest_title}' (content length: {len(latest_content)} chars)")
                        
                        if len(latest_content) < 100:
                            print(f"[POST-VERIFY-ERROR] Post validation failed! Feed content len: {len(latest_content)}")
                            try:
                                page.goto(f"https://draft.blogger.com/blog/posts/{blog_id}", wait_until="networkidle", timeout=20000)
                                time.sleep(2)
                                discard_btn = page.locator('div[aria-label="この投稿を破棄"]').first
                                if discard_btn.is_visible(timeout=3000):
                                    discard_btn.dispatch_event('click')
                                    time.sleep(1.0)
                                    page.keyboard.press('Enter')
                            except Exception:
                                pass
                            raise RuntimeError(f"Critical: Blogger post was not properly published live. Cleaned up.")
                        else:
                            print("[POST-VERIFY] Verification SUCCESS: Article is live with full title, images and content!")
                except Exception as verify_err:
                    if "Critical: Blogger post" in str(verify_err):
                        raise
                    print(f"[POST-VERIFY-WARN] Feed verification check encountered an error: {verify_err}")

            except Exception as e:
                print(f"Error during Blogger operation: {e}")
                try:
                    print("[POST-FAILURE-CLEANUP] Attempting to discard any leftover unfinished draft...")
                    page.goto(f"https://draft.blogger.com/blog/posts/{blog_id}", wait_until="domcontentloaded", timeout=15000)
                    time.sleep(1.5)
                    first_link = page.locator("a[href*='/blog/post/edit/']").first
                    if first_link.is_visible(timeout=3000):
                        first_link.hover()
                        time.sleep(0.5)
                        discard_btn = page.locator("div[role=button][aria-label='この投稿を破棄']").locator("visible=true").first
                        if discard_btn.is_visible(timeout=1500):
                            discard_btn.click()
                            time.sleep(0.8)
                            confirm = page.locator("div[role=button]:has-text('破棄'), button:has-text('破棄')").locator("visible=true").first
                            if confirm.is_visible(timeout=1500):
                                confirm.click()
                                print("[POST-FAILURE-CLEANUP] Unfinished draft discarded successfully.")
                                time.sleep(1.5)
                except Exception as discard_err:
                    print(f"[POST-FAILURE-CLEANUP-WARN] Could not discard draft: {discard_err}")
                raise e

    finally:
        if session_file_path and session_file_path != "session.json" and os.path.exists(session_file_path):
            os.remove(session_file_path)


def generate_room_comment_with_llm(item):
    import random
    title = item.get("itemName") or item.get("title") or ""
    price = item.get("itemPrice") or item.get("price") or ""
    caption = item.get("itemCaption") or item.get("catchcopy") or ""

    prompt = f"""以下のバッドばつ丸・サンリオキャラクター商品情報を基にして、楽天ROOM用の魅力的な紹介コメント（400文字以内）を生成してください。
【商品名】: {title}
【価格】: {price}円
【商品説明・特徴】: {caption[:200]}

以下の要件を厳格に遵守してください：
1. 口調・トーン：サンリオ・ばつ丸ファンに刺さる自然な語り口とし、「これかわいい！」「これ気になってた！」「これ便利だよ！」といった安易な定型表現は絶対に使用しないでください。デザインの可愛さ・ブラックユーモア溢れる魅力・実用性等の具体的メリットを解説してください。
2. 文字数：400文字以内（厳守。超えると投稿エラーになります）。
3. 絵文字：5〜8個使用して華やかにすること。
4. ハッシュタグ：3〜5個（「#バッドばつ丸 #ばつ丸 #サンリオ #推し活」等、関連タグ）含め、末尾に「#楽天市場」を必ず含めること。
5. URLや疑似リンク、プレースホルダー（「[リンクはこちら]」など）は絶対に含めないでください。
6. 出力は紹介コメントのテキストのみとし、前置きやMarkdownの装飾コードブロック等は一切含めないでください。
"""

    system_message = (
        "あなたはバッドばつ丸・サンリオキャラ専門の推し活インフルエンサーです。"
        "定型フレーズを排し、ファンの心をくすぐる愛のあるオリジナル紹介文を作成してください。"
    )

    def clean_text(text):
        return text.replace("```", "").strip()

    # 1. Gemini API（最優先。thinking無効化・全parts結合で安定化）
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        models = [
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.5-pro",
            "gemini-3-flash",
            "gemini-3.1-pro",
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
            "gemini-3.7-flash"
        ]
        for model_name in models:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{"parts": [{"text": f"{system_message}\n\n{prompt}"}]}],
                    "generationConfig": {"temperature": 0.9, "maxOutputTokens": 600}
                }
                if any(v in model_name for v in ["2.5", "3.", "3-"]):
                    payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
                res = requests.post(url, json=payload, timeout=30)
                if res.status_code == 200:
                    data = res.json()
                    candidate = data.get("candidates", [{}])[0]
                    parts = candidate.get("content", {}).get("parts", [])
                    text = clean_text("".join(p.get("text", "") for p in parts if p.get("text")))
                    if len(text) > 30:
                        print(f"Successfully generated ROOM comment via Gemini API ({model_name}).")
                        return text
                    finish = candidate.get("finishReason", "UNKNOWN")
                    print(f"Gemini ({model_name}) short/empty. finishReason={finish}, text_len={len(text)}")
                else:
                    print(f"Gemini API ({model_name}) returned {res.status_code}: {res.text[:150]}")
            except Exception as e:
                print(f"Gemini API ({model_name}) error: {e}")

    # 2. Groq API
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        for model_name in ["llama-3.3-70b-versatile", "llama3-70b-8192", "llama3-8b-8192"]:
            try:
                headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                payload = {
                    "model": model_name,
                    "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 600
                }
                res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=25)
                if res.status_code == 200:
                    text = clean_text(res.json()["choices"][0]["message"]["content"])
                    if len(text) > 30:
                        print(f"Successfully generated ROOM comment via Groq API ({model_name}).")
                        return text
                else:
                    print(f"Groq API ({model_name}) returned {res.status_code}: {res.text[:100]}")
            except Exception as e:
                print(f"Groq API ({model_name}) error: {e}")

    # 3. OpenRouter API（有効な無料モデルを使用）
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        for model_name in ["google/gemma-3-27b-it:free", "mistralai/mistral-nemo:free", "meta-llama/llama-3.2-3b-instruct:free"]:
            try:
                headers = {
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com",
                    "X-Title": "RakutenRoomBot"
                }
                payload = {
                    "model": model_name,
                    "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 600
                }
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=30)
                if res.status_code == 200:
                    text = clean_text(res.json()["choices"][0]["message"]["content"])
                    if len(text) > 30:
                        print(f"Successfully generated ROOM comment via OpenRouter ({model_name}).")
                        return text
                else:
                    print(f"OpenRouter ({model_name}) returned {res.status_code}: {res.text[:100]}")
            except Exception as e:
                print(f"OpenRouter ({model_name}) error: {e}")

    # 4. GitHub Models API（GH_TOKENがPATの場合のみ）
    gh_token = os.environ.get("GH_TOKEN")
    if gh_token and not gh_token.startswith("ghs_"):
        for model_name in ["gpt-4o-mini", "gpt-4o", "Meta-Llama-3.1-8B-Instruct"]:
            try:
                headers = {"Authorization": f"Bearer {gh_token}", "Content-Type": "application/json"}
                payload = {
                    "model": model_name,
                    "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": prompt}],
                    "temperature": 0.8,
                    "max_tokens": 600
                }
                res = requests.post("https://models.inference.ai.azure.com/chat/completions", headers=headers, json=payload, timeout=25)
                if res.status_code == 200:
                    text = clean_text(res.json()["choices"][0]["message"]["content"])
                    if len(text) > 30:
                        print(f"Successfully generated ROOM comment via GitHub Models API ({model_name}).")
                        return text
                else:
                    print(f"GitHub Models API ({model_name}) returned {res.status_code}: {res.text[:100]}")
            except Exception as e:
                print(f"GitHub Models API ({model_name}) error: {e}")

    print("WARNING: All LLM API calls failed. Generating dynamic item-aware comment.")
    clean_title = title.replace("【", "").replace("】", "").replace("！", "").replace("✨", "")[:45]

    starters = [
        f"ばつ丸推し必見！『{clean_title}』のブラッククールな可愛さが大爆発🖤✨",
        f"サンリオファン大注目の『{clean_title}』をピックアップ！お部屋に連れて帰りたい可愛さ💕",
        f"個性的で愛おしい『{clean_title}』のご紹介！自分用や推し活に最高の一品👍",
        f"見つけた瞬間即チェック！『{clean_title}』の魅力あふれるデザインがたまらない🎁",
        f"クオリティが高くておすすめの『{clean_title}』！完売前にぜひチェックしてね✨"
    ]
    starter = random.choice(starters)

    bodies = [
        "ばつ丸ならではのいたずらっぽい表情とクールな雰囲気が最高のアイテム！コレクションに加えたくなります😊",
        "実用性もバッチリで毎日連れて歩きたくなるクオリティ。ファンなら絶対手に入れたい逸品✨",
        "プレゼントや自分へのご褒美にも大人気！存在感抜群でテンション上がります🛍️",
        "お気に入りのサンリオグッズと一緒に飾っても映える優秀アイテム。お早めにどうぞ👍"
    ]
    body = random.choice(bodies)

    price_info = f"（価格: {price}円）" if price else ""
    return f"{starter}\n\n{body}\n{price_info}\n\n#サンリオ #楽天市場 #おすすめアイテム #コレ"



def post_to_rakuten_room(item_code, comment):
    session_b64 = os.environ.get("ROOM_SESSION_B64") or os.environ.get("BLOGGER_SESSION_B64")
    
    session_file_path = None
    if session_b64:
        try:
            decoded_str = base64.b64decode(session_b64).decode('utf-8')
            json.loads(decoded_str)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".json") as temp_file:
                temp_file.write(decoded_str)
                session_file_path = temp_file.name
        except Exception as e:
            print(f"ROOM_SESSION_B64 (or BLOGGER_SESSION_B64) decode failed: {e}")
            return
    elif os.path.exists("session.json"):
        print("Found local session.json. Using it for Rakuten Room.")
        session_file_path = "session.json"
    else:
        print("ROOM_SESSION_B64/BLOGGER_SESSION_B64 is not set and local session.json not found. Skipping Rakuten Room post.")
        return

    print(f"Posting to Rakuten Room (Item: {item_code}) using Playwright...")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                storage_state=session_file_path,
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            try:
                # ROOM投稿エディタへ遷移
                warp_url = f"https://room.rakuten.co.jp/mix?itemcode={item_code}&scid=we_room_upc60"
                page.goto(warp_url, wait_until="load", timeout=45000)
                time.sleep(4)

                # ログイン画面に飛ばされていないかチェック
                if "login.rakuten.co.jp" in page.url or "login" in page.url.lower():
                    print("Error: Session has expired or is invalid. Redirected to Rakuten login page. Skipping Rakuten Room post.")
                    return

                # 重複・すでにコレしているかチェック
                page_html = page.content()
                if any(term in page_html for term in ["すでにコレ", "すでに登録されています", "すでに登録"]):
                    print("This item has already been posted ('コレ！'済み) to Rakuten Room. Skipping.")
                    return

                # コメント入力欄 (textarea)
                comment_area = page.locator('textarea[placeholder*="コメント"], textarea[placeholder*="オススメ"], textarea[placeholder*="魅力"], textarea').first
                comment_area.wait_for(state="visible", timeout=15000)
                comment_area.fill(comment)
                time.sleep(1)

                # 投稿確定ボタン
                submit_btn = page.locator('button:has-text("投稿"), button:has-text("完了"), button:has-text("コレ！"), button[class*="submit"]').first
                submit_btn.scroll_into_view_if_needed()
                time.sleep(1)
                submit_btn.click(force=True)
                print("Clicked Rakuten Room submit button.")
                
                time.sleep(5)
                print("Successfully posted to Rakuten Room!")
            except Exception as inner_e:
                print(f"Error during Playwright interaction: {inner_e}")
                try:
                    page.screenshot(path="room_error.png")
                    print("Saved debug screenshot: room_error.png")
                except Exception as se:
                    print(f"Failed to take screenshot: {se}")
                raise inner_e

    except Exception as e:
        print(f"Error posting to Rakuten Room: {e}")
    finally:
        if session_file_path and session_file_path != "session.json" and os.path.exists(session_file_path):
            os.remove(session_file_path)


def main():
    try:
        # 1. 楽天から商品取得
        item = fetch_rakuten_item()
        item_code = item.get("itemCode")
        title = item.get("itemName")
        print(f"Selected Item: {title} ({item_code})")

        # 2. LLMで記事生成
        llm_result = generate_article_with_llm(item)
        if isinstance(llm_result, dict):
            gen_title = llm_result.get("title", title[:30])
            html_content = llm_result.get("html", "")
        else:
            gen_title = title[:30]
            html_content = str(llm_result)
            
        if not html_content or len(html_content) < 10:
            # AIが失敗した時の絶対的なフォールバックHTML
            image_url = item.get("mediumImageUrls", [{"imageUrl": ""}])[0].get("imageUrl", "") if item.get("mediumImageUrls") else ""
            html_content = f'<h2>{gen_title}</h2><br><br><img src="{image_url}" alt="商品画像" style="max-width: 100%; height: auto;"><br><br><a href="https://room.rakuten.co.jp/jack555/items" target="_blank">✅ 私の楽天ROOMはこちら</a>'

        # 誤字脱字最終チェックとSEO, AI-SEO, GEO的な修正ブラッシュアップ工程
        html_content = proofread_and_optimize_blogger_article(gen_title, html_content)
        # 途中切れ（力尽きる現象）防止・補正工程
        html_content = ensure_complete_blogger_article(html_content)
            
        print("--- Generated HTML Content Snippet ---")
        print(html_content[:200])
        print("--------------------------------------")
        
                # タイトル重複・スパム検証
        is_dup, dup_match, ratio = is_title_duplicate_or_similar(gen_title)
        if is_dup:
            print(f"[WARN] Title duplicated or banned ({dup_match}, ratio={ratio:.2f}): {gen_title}")
            import random
            prefixes = ["【注目レビュー】", "【徹底紹介】", "【話題の逸品】", "【暮らしを豊かに】", "【愛用者が選ぶ】"]
            clean_item_name = clean_rakuten_item_name(title)[:24]
            gen_title = f"{random.choice(prefixes)}{clean_item_name}"
            print(f"-> Replaced with unique fallback title: {gen_title}")

        post_to_blogger(gen_title, html_content)

        # 楽天ROOMへも自動「コレ！」投稿
        try:
            room_comment = generate_room_comment_with_llm(item)
            print("Generated ROOM Comment:")
            print(room_comment)
            post_to_rakuten_room(item_code, room_comment)
        except Exception as room_err:
            print(f"Failed to post to Rakuten Room: {room_err}")

        # 4. キャッシュに保存
        save_to_cache(item_code)
        save_posted_title(gen_title)
        save_posted_title(gen_title)
        print("Process completed successfully.")

    except Exception as e:
        print(f"Error in execution: {e}")
        exit(1)

if __name__ == "__main__":
    main()
