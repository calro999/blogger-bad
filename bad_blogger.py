import os
import random
import requests
import time
import base64
import json
import tempfile
from playwright.sync_api import sync_playwright

CACHE_FILE = "posted_cache.txt"

def load_posted_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_to_cache(item_code):
    with open(CACHE_FILE, "a", encoding="utf-8") as f:
        f.write(f"{item_code}\n")

def fetch_rakuten_item():
    app_id = os.environ.get("RAKUTEN_APP_ID")
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY")
    if not app_id or not access_key:
        raise ValueError("RAKUTEN_APP_ID and RAKUTEN_ACCESS_KEY must be set in environment variables.")

    attributes = ["ぬいぐるみ", "マスコット", "ポーチ", "文房具", "キーホルダー", "コラボ", "雑貨", "バッグ", "フィギュア"]
    selected_attribute = random.choice(attributes)
    keyword = f"バッドばつ丸 {selected_attribute}"
    print(f"Searching Rakuten for keyword: {keyword}")

    url = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401"
    params = {
        "applicationId": app_id,
        "accessKey": access_key,
        "keyword": keyword,
        "format": "json",
        "hits": 30
    }

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
    title = item.get("itemName")
    price = item.get("itemPrice")
    url = item.get("affiliateUrl") or item.get("itemUrl")
    
    # 複数画像がある場合は最初の一枚、なければ空文字列
    image_url = ""
    medium_images = item.get("mediumImageUrls", [])
    if medium_images:
        image_url = medium_images[0]
    else:
        # fallback
        small_images = item.get("smallImageUrls", [])
        if small_images:
            image_url = small_images[0]

    prompt = f"""以下の楽天の商品情報を基にして、自動投稿用のHTML記事を生成してください。
【商品名】: {title}
【価格】: {price}円
【商品画像URL】: {image_url}
【アフィリエイトURL】: {url}

以下の要件を厳格に遵守してください：
1. 出力はブログの本文となるHTMLコードのみとし、余計な説明、挨拶、前置きや後書き（例：「以下が記事です」「```html」のようなマークダウンブロック）は絶対に含めず、純粋なHTML文字列のみを出力してください。
2. アイキャッチ画像として、商品画像URL（{image_url}）を直接<img>タグのsrc属性に指定し、記事の最上部に配置してください。
3. 記事構成：
   - キャッチーな見出し（<h2> または <h3> タグを使用）
   - 商品の簡潔な説明（客観的で魅力が伝わる文章。自分語りやポエム調の表現は一切禁止）
   - コレクター向けの魅力3ポイント（必ず <ul> と <li> タグを使用）
   - 購買意欲を促す太字の誘導文（<strong> または <b> タグを使用）
   - 最後にアフィリエイトリンクのボタン（<a>タグでスタイルし、新しいタブで開く target="_blank" rel="noopener noreferrer" を指定。ボタンらしいデザインになるようインラインスタイルを施すこと。例：background-color: #ff6600; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block;）
"""

    # 1. GitHub Models API (GITHUB_TOKENを使用) を最優先
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if github_token:
        try:
            print("Attempting to generate article with GitHub Models API...")
            headers = {
                "Authorization": f"Bearer {github_token}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "あなたはサンリオのキャラクター『バッドばつ丸』専門のコレクター兼紹介ブロガーです。ばつ丸くんの天の邪鬼でいたずら好きな愛らしい魅力が伝わる文章を作成します。指示された仕様に完全に従い、前置きやHTMLタグブロックのマークダウン表現などを含めない純粋なHTML本文のみを出力します。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7
            }
            response = requests.post("https://models.inference.ai.azure.com/chat/completions", headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                result = response.json()["choices"][0]["message"]["content"].strip()
                if "```html" in result:
                    result = result.split("```html", 1)[1]
                if "```" in result:
                    result = result.split("```", 1)[0]
                return result.strip()
            else:
                print(f"GitHub Models API returned status code: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"GitHub Models API failed with exception: {e}")
    else:
        print("GITHUB_TOKEN / GH_TOKEN is not set in environment variables.")

    # 2. Pollinations AI (キー不要、フォールバック)
    pollinations_models = ["openai", "mistral"]
    for model in pollinations_models:
        try:
            print(f"Attempting to generate article with Pollinations AI (model: {model})...")
            response = requests.post(
                "https://text.pollinations.ai/",
                json={
                    "messages": [
                        {"role": "system", "content": "あなたはサンリオのキャラクター『バッドばつ丸』専門のコレクター兼紹介ブロガーです。ばつ丸くんの天の邪鬼でいたずら好きな愛らしい魅力が伝わる文章を作成します。指示された仕様に完全に従い、前置きやHTMLタグブロックのマークダウン表現などを含めない純粋なHTML本文のみを出力します。"},
                        {"role": "user", "content": prompt}
                    ],
                    "model": model
                },
                timeout=45
            )
            if response.status_code == 200 and len(response.text.strip()) > 100:
                result = response.text.strip()
                if "```html" in result:
                    result = result.split("```html", 1)[1]
                if "```" in result:
                    result = result.split("```", 1)[0]
                return result.strip()
            else:
                print(f"Pollinations AI ({model}) returned status code: {response.status_code} - {response.text[:200]}")
        except Exception as e:
            print(f"Pollinations AI ({model}) failed with exception: {e}")
            time.sleep(1)


    raise RuntimeError("All LLM generation attempts failed.")

def post_to_blogger(title, content):
    session_b64 = os.environ.get("BLOGGER_SESSION_B64")
    if not session_b64:
        raise ValueError("BLOGGER_SESSION_B64 is not set in environment variables.")
    
    try:
        decoded_str = base64.b64decode(session_b64).decode('utf-8')
        json.loads(decoded_str) # JSONとして正しいか検証
    except Exception as e:
        raise ValueError(f"BLOGGER_SESSION_B64 のデコードに失敗しました。正しいBase64文字列が設定されているか確認してください。エラー詳細: {e}")

    blog_id = os.environ.get("BLOGGER_BLOG_ID")
    if not blog_id:
        raise ValueError("BLOGGER_BLOG_ID is not set in environment variables.")

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, suffix=".json") as temp_file:
        temp_file.write(decoded_str)
        session_file_path = temp_file.name

    print(f"Posting to Blogger (Blog ID: {blog_id}) using Playwright...")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                storage_state=session_file_path,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
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

                title_input = page.locator('.titleField input, input[aria-label*="Title"], input[aria-label*="タイトル"], input.whsOnd.zHQkBf').first
                title_input.wait_for(state="visible", timeout=30000)
                title_input.click()
                time.sleep(random.uniform(0.5, 1.5))
                title_input.fill(title)
                time.sleep(random.uniform(1.0, 2.0))

                view_switch = page.locator('[aria-label="View mode"], [aria-label="表示モード"]').first
                if view_switch.is_visible():
                    view_switch.click()
                    time.sleep(random.uniform(0.5, 1.0))
                    html_view_btn = page.locator('[aria-label="HTML view"], [aria-label="HTML ビュー"], span:has-text("HTML")').first
                    if html_view_btn.is_visible():
                        html_view_btn.click()
                        time.sleep(random.uniform(1.0, 2.0))

                try:
                    editor_area = page.locator('.CodeMirror, textarea.html-textarea, iframe').last
                    editor_area.click()
                    time.sleep(1)
                    
                    page.keyboard.press('Meta+A')
                    page.keyboard.press('Control+A')
                    page.keyboard.press('Backspace')
                    time.sleep(0.5)
                    
                    page.keyboard.insert_text(content)
                except Exception as e:
                    print("Fallback to JS injection due to error:", e)
                    page.evaluate('''(content) => {
                        const ta = document.querySelector('textarea.html-textarea') || document.querySelector('textarea');
                        if (ta) { ta.value = content; ta.dispatchEvent(new Event('input')); return; }
                        const ce = document.querySelector('[contenteditable="true"]');
                        if (ce) { ce.innerHTML = content; return; }
                        const frames = document.querySelectorAll('iframe');
                        for (let f of frames) {
                            try {
                                const fce = f.contentDocument.querySelector('[contenteditable="true"]');
                                if (fce) { fce.innerHTML = content; return; }
                            } catch(err) {}
                        }
                    }''', content)

                time.sleep(random.uniform(2.0, 3.0))

                # 公開ボタンをクリック（表示されている要素のみを対象にする）
                try:
                    page.evaluate('''() => {
                        const btns = Array.from(document.querySelectorAll('div[role="button"]'));
                        const visibleBtns = btns.filter(b => b.offsetParent !== null);
                        const pubBtn = visibleBtns.find(b => (b.getAttribute('aria-label') || '').includes('公開') || (b.getAttribute('aria-label') || '').includes('Publish'));
                        if (pubBtn) pubBtn.click();
                    }''')
                except Exception as e:
                    print("Publish click error:", e)
                
                time.sleep(random.uniform(2.0, 3.0))

                # 確認ボタンをクリック（表示されている要素のみを対象にする）
                try:
                    page.evaluate('''() => {
                        const btns = Array.from(document.querySelectorAll('div[role="button"]'));
                        const visibleBtns = btns.filter(b => b.offsetParent !== null);
                        const confBtn = visibleBtns.find(b => (b.getAttribute('aria-label') || '').includes('確認') || (b.getAttribute('aria-label') || '').includes('Confirm'));
                        if (confBtn) confBtn.click();
                    }''')
                except Exception as e:
                    print("Confirm click error:", e)
                
                time.sleep(random.uniform(3.0, 5.0))

                print("Successfully posted using Playwright!")
            except Exception as e:
                print(f"Error occurred. Current URL: {page.url}")
                print(f"Page Title: {page.title()}")
                print(f"Page Content Snippet: {page.content()[:1000]}")
                raise e

    finally:
        if os.path.exists(session_file_path):
            os.remove(session_file_path)

def main():
    try:
        # 1. 楽天から商品取得
        item = fetch_rakuten_item()
        item_code = item.get("itemCode")
        title = item.get("itemName")
        print(f"Selected Item: {title} ({item_code})")

        # 2. LLMで記事生成
        content = generate_article_with_llm(item)

        # 3. Bloggerに投稿
        post_to_blogger(title, content)

        # 4. キャッシュに保存
        save_to_cache(item_code)
        print("Process completed successfully.")

    except Exception as e:
        print(f"Error in execution: {e}")
        exit(1)

if __name__ == "__main__":
    main()
