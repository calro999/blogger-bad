import os
import random
import requests
import time
import base64
import json
import tempfile
from playwright.sync_api import sync_playwright

CACHE_FILE = "posted_cache.txt"


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
    url_pattern = r'https?://[^\s"<>\'\)]+'
    def replace_url(match):
        found_url = match.group(0)
        if "room.rakuten.co.jp" in found_url or "hb.afl.rakuten.co.jp" in found_url or ("rakuten.co.jp" in found_url and "affiliateId" in found_url):
            return found_url
        return valid_affiliate_url if valid_affiliate_url else "https://room.rakuten.co.jp/jack555/items"
    
    sanitized = re.sub(url_pattern, replace_url, content)
    sanitized = sanitized.replace("Amazon", "楽天市場").replace("アマゾン", "楽天市場").replace("ヤフー", "楽天市場").replace("Yahoo!", "楽天市場")
    return sanitized

def fetch_rakuten_item():
    app_id = os.environ.get("RAKUTEN_APP_ID")
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY")
    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID")
    if not app_id or not access_key:
        raise ValueError("RAKUTEN_APP_ID and RAKUTEN_ACCESS_KEY must be set in environment variables.")

    attributes = ["ばつ丸", "バッドばつ丸", "ブラック", "サンリオ", "限定", "グッズ"]
    selected_attribute = random.choice(attributes)
    keyword = f"サンリオ {selected_attribute}"
    print(f"Searching Rakuten for keyword: {keyword}")

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

    response = requests.get(url, params=params)
    if response.status_code != 200:
        raise RuntimeError(f"Failed to fetch from Rakuten API: {response.status_code} - {response.text}")

    data = response.json()
    items = data.get("Items", [])
    if not items:
        raise RuntimeError(f"No items found for keyword: {keyword}")

    posted_cache = load_posted_cache()
    for item_wrapper in items:
        item = item_wrapper.get("Item", {})
        item_code = item.get("itemCode")
        if item_code and item_code not in posted_cache:
            return item

    raise RuntimeError("All fetched items have already been posted.")

def generate_article_with_llm(item):
    title = item.get("itemName", "")
    price = item.get("itemPrice", "")
    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID")
    url = get_rakuten_affiliate_url(item, affiliate_id)
    
    image_url = ""
    medium_images = item.get("mediumImageUrls", [])
    if medium_images:
        image_url = medium_images[0]
    else:
        small_images = item.get("smallImageUrls", [])
        if small_images:
            image_url = small_images[0]

    buy_button_html = f'<div style="text-align: center; margin: 20px 0;"><a href="{url}" target="_blank" rel="noopener noreferrer" style="display:inline-block; padding: 14px 28px; background-color: #bf0000; color: #ffffff; font-weight: bold; font-size: 16px; border-radius: 8px; text-decoration: none; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">🛒 楽天市場で価格・在庫を見る</a></div>'

    prompt = f"""以下の楽天の商品情報を基にして、ブログ記事のタイトルとHTML本文を生成してください。
【商品名】: {title}
【価格】: {price}円
【商品画像URL】: {image_url}
【アフィリエイトURL】: {url}
【楽天ROOM】: https://room.rakuten.co.jp/jack555/items

以下の要件を厳格に遵守してください：
1. 出力は以下のJSONフォーマットのみとしてください。他のテキストは一切含めないでください。
{{
    "title": "ここにキャッチーで魅力的なタイトル（商品名の単なる羅列は禁止、最大35文字）",
    "html": "ここに純粋なHTML本文（以下の構成に従う）"
}}
2. HTML本文の構成：
   - 記事全体を `<div class="premium-squishy-article">` と `</div>` で囲む
   - 商品の魅力的な説明（`<div class="premium-content-body">` と `</div>` で囲む）
   - おすすめ注目ポイント3選（`<ul class="premium-points-list">` と `<li>` タグを使用）
   - 商品の画像（`<img src="{image_url}" alt="{title}" style="max-width: 100%; height: auto;">`）
   - 楽天市場への購入アフィリエイトボタン（必ず以下のHTMLを配置すること）:
     {buy_button_html}
   - 楽天ROOMへのリンク（`<br><a href="https://room.rakuten.co.jp/jack555/items" target="_blank">✅ 私の楽天ROOMはこちら</a>`）
3. 【厳禁事項】: Amazon, Yahoo, 他社ECサイト, メーカー公式サイト等のURLや名称は絶対に含めないでください。商品リンクは提供したアフィリエイトURLのみを使用してください。
"""

    system_message = "あなたはクールで個性的なキャラクターグッズ専門の紹介ブロガーです。指示された仕様に完全に従い、Amazon等の無関係な外部サイトリンクを一切含めない純粋なHTML本文を出力します。"

    # 1. GitHub Models API
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if github_token:
        for model_name in ["gpt-4o-mini", "gpt-4o", "Phi-3.5-mini-instruct"]:
            try:
                headers = {"Authorization": f"Bearer {github_token}", "Content-Type": "application/json"}
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7
                }
                res = requests.post("https://models.inference.ai.azure.com/chat/completions", headers=headers, json=payload, timeout=25)
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"].strip()
                    if "```json" in text: text = text.split("```json", 1)[1].split("```")[0].strip()
                    elif "```" in text: text = text.split("```", 1)[1].split("```")[0].strip()
                    parsed = json.loads(text)
                    parsed["html"] = sanitize_llm_output(parsed["html"], url)
                    return parsed
            except Exception as e:
                print(f"GitHub Models API ({model_name}) article error: {e}")

    # 2. Gemini API
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                url_api = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
                payload = {"contents": [{"parts": [{"text": f"{system_message}\n\n{prompt}"}]}]}
                res = requests.post(url_api, json=payload, timeout=25)
                if res.status_code == 200:
                    text = res.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                    if "```json" in text: text = text.split("```json", 1)[1].split("```")[0].strip()
                    elif "```" in text: text = text.split("```", 1)[1].split("```")[0].strip()
                    parsed = json.loads(text)
                    parsed["html"] = sanitize_llm_output(parsed["html"], url)
                    return parsed
            except Exception as e:
                print(f"Gemini API ({model_name}) article error: {e}")

    # 3. Groq API
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        for model_name in ["llama-3.3-70b-versatile", "llama3-8b-8192"]:
            try:
                headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": prompt}
                    ]
                }
                res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=25)
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"].strip()
                    if "```json" in text: text = text.split("```json", 1)[1].split("```")[0].strip()
                    elif "```" in text: text = text.split("```", 1)[1].split("```")[0].strip()
                    parsed = json.loads(text)
                    parsed["html"] = sanitize_llm_output(parsed["html"], url)
                    return parsed
            except Exception as e:
                print(f"Groq API ({model_name}) article error: {e}")

    print("WARNING: All LLM generation attempts failed. Generating dynamic item-aware article.")
    clean_title = title.replace("【", "").replace("】", "")[:35]
    price_str = f"（価格: {price}円）" if price else ""
    
    fallback_html = f"""<div class="premium-squishy-article">
    <div class="premium-content-body">
        <p>バッドばつ丸やサンリオキャラクターファンの間で話題沸騰中の大人気アイテム「<b>{title}</b>」をご紹介します！</p>
        <p>可愛らしいデザインと実用性を備え、日常に笑顔をもたらしてくれるファン必携のコレクションアイテムです。</p>
        <ul class="premium-points-list">
            <li><b>キュートなデザイン</b>：キャラクターの魅力を余すところなく表現！</li>
            <li><b>優れた実用性</b>：普段使いにもプレゼントにも最適なハイクオリティ！</li>
            <li><b>限定感ある完成度</b>：手元に置いておくだけで満足感広がるコレクターズ仕様！</li>
        </ul>
        {"<img src='" + image_url + "' alt='" + title + "' style='max-width: 100%; height: auto;'><br>" if image_url else ""}
        <br><a href="https://room.rakuten.co.jp/jack555/items" target="_blank">✅ 私の楽天ROOMはこちら</a>
    </div>
</div>"""
    return {
        "title": f"【大人気】{title[:25]}",
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
            raise ValueError(f"BLOGGER_SESSION_B64 のデコードに失敗しました: {e}")
    elif os.path.exists("session.json"):
        print("Found local session.json. Using it for Blog Post.")
        session_file_path = "session.json"
    else:
        raise ValueError(f"BLOGGER_SESSION_B64 is not set and local session.json not found.")

    print(f"Posting to Blogger (Blog ID: {blog_id}) using Playwright...")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                storage_state=session_file_path,
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                permissions=['clipboard-read', 'clipboard-write']
            )
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            try:
                time.sleep(random.uniform(3.0, 5.0))

                page.goto(f"https://draft.blogger.com/blog/post/edit/{blog_id}/new", wait_until="networkidle")
                time.sleep(random.uniform(3.0, 5.0))
                
                # もし画面が遷移していなかったら、キーボードショートカット 'c' (新規投稿) を試す
                if "edit" not in page.url:
                    page.keyboard.press('c')
                    time.sleep(random.uniform(3.0, 5.0))
                
                # それでもダメならJSで強制的に「新しい投稿」ボタンをクリックする
                if "edit" not in page.url:
                    page.evaluate('''() => {
                        const btns = Array.from(document.querySelectorAll('div[role="button"]'));
                        const newPostBtn = btns.find(b => (b.getAttribute('aria-label') || '').includes('新しい投稿') || (b.getAttribute('aria-label') || '').includes('New post'));
                        if (newPostBtn) newPostBtn.click();
                    }''')
                    time.sleep(random.uniform(3.0, 5.0))

                # 1. タイトル入力
                title_input = page.locator('.titleField input, input[aria-label*="Title"], input[aria-label*="タイトル"]').first
                title_input.wait_for(state="visible", timeout=30000)
                title_input.click()
                time.sleep(0.5)
                # タイトルを全消去して入力
                page.keyboard.press('Meta+A')
                page.keyboard.press('Control+A')
                page.keyboard.press('Backspace')
                # 1-2. タイトルと本文入力（検証ループ付き）
                max_retries = 3
                success = False
                
                for attempt in range(max_retries):
                    print(f"--- Attempt {attempt+1} / {max_retries} ---")
                    
                    if attempt > 0:
                        print("Reloading page for retry...")
                        page.reload(wait_until="domcontentloaded")
                        time.sleep(3)
                    
                    try:
                        title_input = page.locator('input.titleField, input[aria-label="タイトル"], input[aria-label="Title"]').locator("visible=true").first
                        title_input.fill(title)
                        time.sleep(2)
                        
                        print("Focusing on the rich text editor via Tab navigation...")
                        # タイトル入力後、Tabキーを2回押せば通常本文エリアにフォーカスが当たる
                        page.keyboard.press('Tab')
                        time.sleep(0.5)
                        page.keyboard.press('Tab')
                        time.sleep(1)
                        
                        # 念のためエディタらしきものをクリックも試す
                        try:
                            editor_body = page.locator('div[aria-label="本文"], div[aria-label="Body"], div[role="textbox"], iframe').locator("visible=true").first
                            editor_body.click(timeout=3000)
                        except:
                            pass
                            
                        print("Injecting HTML via Playwright clipboard paste...")
                        # クリップボードにHTMLとしてコピー
                        page.evaluate('''html => {
                            try {
                                const blob = new Blob([html], { type: 'text/html' });
                                const data = [new ClipboardItem({ 'text/html': blob })];
                                navigator.clipboard.write(data);
                            } catch (e) {
                                console.error('Clipboard write failed:', e);
                            }
                        }''', content)
                        time.sleep(2)
                        
                        # ペースト実行
                        page.keyboard.press('Control+V')
                        page.keyboard.press('Meta+V') # Mac用
                        time.sleep(2)
                        
                        # Wizオートセーブ誘発のためのダミータイピング
                        print("Triggering Wiz autosave...")
                        page.keyboard.press('Space')
                        time.sleep(0.5)
                        page.keyboard.press('Backspace')
                        time.sleep(3)
                        
                        # --- 本文入力の検証 ---
                        print("Validating injected content...")
                        # 特定の要素にこだわらず、ページ全体のHTMLを取得して画像タグが含まれるか確認する
                        page_html = page.content()
                        
                        if "<img" in page_html and ("href" in page_html or "http" in page_html):
                            print("Validation passed: Body content (image and links) successfully detected in page!")
                            success = True
                            break
                        else:
                            print("Validation failed: Body seems empty or missing images in page DOM.")
                            print("Page HTML snippet:", page_html[:200])
                            
                    except Exception as e:
                        print(f"Error during injection attempt {attempt+1}: {e}")
                        
                    time.sleep(3)
                
                if not success:
                    raise Exception("Critical Failure: Could not inject body content after 3 attempts. Aborting save to prevent empty drafts.")

                # 3. 公開ボタンのクリック
                print("Publishing post...")
                try:
                    pub_btn = page.locator('[aria-label="公開"], [aria-label="Publish"]').locator("visible=true").first
                    pub_btn.scroll_into_view_if_needed()
                    time.sleep(1)
                    pub_btn.click(force=True, timeout=10000)
                    print("Clicked publish button.")
                except Exception as e:
                    print("Failed to click publish button:", e)
                    # ショートカットフォールバック
                    page.keyboard.press('Control+Shift+P')
                    page.keyboard.press('Meta+Shift+P')
                
                time.sleep(4)

                # 4. 確認ダイアログの「確認」ボタン
                try:
                    conf_btn = page.locator('[aria-label="確認"], [aria-label="Confirm"], div[role="button"]:has-text("確認")').locator("visible=true").first
                    conf_btn.scroll_into_view_if_needed()
                    time.sleep(1)
                    conf_btn.click(force=True, timeout=10000)
                    print("Clicked confirm button.")
                except Exception as e:
                    print("Failed to click confirm button:", e)
                    page.keyboard.press('Enter')
                
                # 公開通信完了まで十分待機
                time.sleep(10)
                print("Successfully published post using Playwright!")
            except Exception as e:
                print(f"Error occurred. Current URL: {page.url}")
                print(f"Page Title: {page.title()}")
                print(f"Page Content Snippet: {page.content()[:1000]}")
                raise e

    finally:
        if os.path.exists(session_file_path):
            os.remove(session_file_path)


def generate_room_comment_with_llm(item):
    import urllib.parse
    import random
    title = item.get("itemName") or item.get("title") or ""
    price = item.get("itemPrice") or item.get("price") or ""
    caption = item.get("itemCaption") or item.get("catchcopy") or ""
    
    prompt = f"""以下の楽天の商品情報を基にして、楽天ROOM用の紹介コメント（400文字以内）を生成してください。
【商品名】: {title}
【価格】: {price}円
【商品説明・特徴】: {caption[:200]}

以下の要件を厳格に遵守してください：
1. 口調・トーン：「これ気になってた！」「これかわいい！」「これ便利だよ！」といった親しみやすく共感できる会話調にすること。
2. 文字数：400文字以内（厳守。超えると投稿エラーになります）。
3. 絵文字：5〜8個使用して華やかにすること。
4. ハッシュタグ：3〜5個（商品のカテゴリや関連するもの）含め、末尾に「#楽天市場」を必ず含めること。
5. URLや疑似リンク、プレースホルダー（「[リンクはこちら]」など）は絶対に含めないでください。
6. 出力は紹介コメントのテキストのみとし、前置きやMarkdownの装飾コードブロック等は一切含めないでください。
"""

    system_message = (
        "あなたは楽天ROOMでフォロワー急増中の人気インフルエンサーです。"
        "「これ気になってた！」「これかわいい！」「これ便利だよ！」などの親しみやすい口調で、"
        "商品の魅力を共感たっぷりに伝えてください。"
    )

    # 1. GitHub Models API
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if github_token:
        for model_name in ["gpt-4o-mini", "gpt-4o", "Phi-3.5-mini-instruct", "Meta-Llama-3.1-8B-Instruct"]:
            try:
                headers = {
                    "Authorization": f"Bearer {github_token}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7
                }
                res = requests.post("https://models.inference.ai.azure.com/chat/completions", headers=headers, json=payload, timeout=20)
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"].strip()
                    if "```" in text:
                        text = text.replace("```", "")
                    text = text.strip()
                    if len(text) > 20:
                        print(f"Successfully generated ROOM comment via GitHub Models API ({model_name}).")
                        return text
                else:
                    print(f"GitHub Models API ({model_name}) returned {res.status_code}: {res.text[:100]}")
            except Exception as e:
                print(f"GitHub Models API ({model_name}) error: {e}")

    # 2. Gemini API
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {"text": f"{system_message}\n\n{prompt}"}
                            ]
                        }
                    ]
                }
                res = requests.post(url, json=payload, timeout=20)
                if res.status_code == 200:
                    data = res.json()
                    text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                    if "```" in text:
                        text = text.replace("```", "")
                    text = text.strip()
                    if len(text) > 20:
                        print(f"Successfully generated ROOM comment via Gemini API ({model_name}).")
                        return text
                else:
                    print(f"Gemini API ({model_name}) returned {res.status_code}: {res.text[:100]}")
            except Exception as e:
                print(f"Gemini API ({model_name}) error: {e}")

    # 3. Groq API
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        for model_name in ["llama-3.3-70b-versatile", "llama3-8b-8192"]:
            try:
                headers = {
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7
                }
                res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"].strip()
                    if "```" in text:
                        text = text.replace("```", "")
                    text = text.strip()
                    if len(text) > 20:
                        print(f"Successfully generated ROOM comment via Groq API ({model_name}).")
                        return text
            except Exception as e:
                print(f"Groq API ({model_name}) error: {e}")

    # 4. OpenRouter API
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        for model_name in ["google/gemini-flash-1.5-exp", "meta-llama/llama-3.2-1b-instruct:free"]:
            try:
                headers = {
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": prompt}
                    ]
                }
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=20)
                if res.status_code == 200:
                    text = res.json()["choices"][0]["message"]["content"].strip()
                    if "```" in text:
                        text = text.replace("```", "")
                    text = text.strip()
                    if len(text) > 20:
                        print(f"Successfully generated ROOM comment via OpenRouter ({model_name}).")
                        return text
            except Exception as e:
                print(f"OpenRouter ({model_name}) error: {e}")

    print("WARNING: All LLM API calls failed. Generating dynamic item-aware comment.")
    clean_title = title.replace("【", "").replace("】", "").replace("！", "").replace("✨", "")[:45]
    words = [w for w in clean_title.split() if len(w) > 1]
    keyword = words[0] if words else "おすすめ"
    
    starters = [
        f"これ気になってた！「{clean_title}」すごく良さそうで目をつけてました✨",
        f"これかわいい！「{clean_title}」のデザインに一目惚れしちゃった💕",
        f"これ便利だよ！「{clean_title}」は持っておくと日常で大活躍しそう👍",
        f"これ気になってた！話題の「{clean_title}」を見つけて即チェック🎁",
        f"これ便利だよ！生活のクオリティが上がりそうな「{clean_title}」✨"
    ]
    starter = random.choice(starters)
    
    bodies = [
        "実用性抜群で見た目のセンスも最高のアイテム！自分用はもちろんギフトにもぴったりだね😊",
        "使ってみた人の評価も高くて期待大！毎日の生活がもっと楽しくなりそう✨",
        "細部までこだわりを感じる優秀アイテム。気になる人はぜひチェックしてみてね🛍️",
        "このクオリティでこの価格は本当に魅力的！見つけたら早めのチェックがおすすめ👍"
    ]
    body = random.choice(bodies)
    
    price_info = f"（価格: {price}円）" if price else ""
    return f"{starter}\n\n{body}\n{price_info}\n\n#{keyword} #楽天市場 #おすすめアイテム #コレ"


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
        print("Process completed successfully.")

    except Exception as e:
        print(f"Error in execution: {e}")
        exit(1)

if __name__ == "__main__":
    main()
