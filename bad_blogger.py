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
   - 極上の贅沢ポイント3選（`<ul class="premium-points-list">` と `<li>` タグを使用）
   - 商品の画像（`<img src="{image_url}" alt="{title}" style="max-width: 100%; height: auto;">`）
   - アフィリエイトリンク（`<a class="premium-affiliate-btn" href="{url}" target="_blank" rel="noopener noreferrer">商品詳細を見る ＞</a>`）
   - 楽天ROOMへのリンク（`<br><a href="https://room.rakuten.co.jp/jack555/items" target="_blank">✅ 私の楽天ROOMはこちら</a>`）を必ず含めること
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
                result_text = response.json()["choices"][0]["message"]["content"].strip()
                import json
                try:
                    # Markdownブロック等を取り除く
                    if "```json" in result_text: result_text = result_text.split("```json", 1)[1]
                    if "```" in result_text: result_text = result_text.split("```")[0]
                    result_text = result_text.strip()
                    parsed = json.loads(result_text)
                    return parsed # 辞書を返す
                except Exception as e:
                    print("JSON Parse error:", e)
                    return {"title": "【注目】" + title[:20] + "...", "html": result_text}
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
                result_text = response.text.strip()
                    import json
                    try:
                        if "```json" in result_text: result_text = result_text.split("```json", 1)[1]
                        if "```" in result_text: result_text = result_text.split("```")[0]
                        result_text = result_text.strip()
                        parsed = json.loads(result_text)
                        return parsed
                    except:
                        return {"title": "【注目】" + title[:20] + "...", "html": result_text}
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
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                permissions=['clipboard-read', 'clipboard-write']
            )
            ) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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

                # 3. 下書き保存処理（公開ボタンを押さない）
                print("Saving as draft...")
                try:
                    # Bloggerの「保存」ボタン（雲にチェックアイコンなど）
                    save_btn = page.locator('[aria-label="保存"], [aria-label="Save"]').first
                    if save_btn.is_visible():
                        save_btn.click(force=True)
                        print("Clicked save button.")
                    else:
                        page.keyboard.press('Control+s')
                        page.keyboard.press('Meta+s')
                        print("Pressed Ctrl+S to save.")
                    time.sleep(5)
                except Exception as e:
                    print("Failed to click save button:", e)

                time.sleep(3)
                print("Successfully saved draft using Playwright!")
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
            html_content = f'<h2>{gen_title}</h2><br><br><img src="{image_url}" alt="商品画像" style="max-width: 100%; height: auto;"><br><br><a href="{url}" target="_blank">商品詳細を見る ＞</a><br><br><a href="https://room.rakuten.co.jp/jack555/items" target="_blank">✅ 私の楽天ROOMはこちら</a>'
            
        print("--- Generated HTML Content Snippet ---")
        print(html_content[:200])
        print("--------------------------------------")
        
        post_to_blogger(gen_title, html_content)

        # 4. キャッシュに保存
        save_to_cache(item_code)
        print("Process completed successfully.")

    except Exception as e:
        print(f"Error in execution: {e}")
        exit(1)

if __name__ == "__main__":
    main()
