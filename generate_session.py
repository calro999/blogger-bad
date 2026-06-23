import os
import json
import base64
from playwright.sync_api import sync_playwright

def main():
    print("Blogger と 楽天ROOM にログインしてセッションを保存します...")
    with sync_playwright() as p:
        # 自動化検知を回避するための引数を指定して起動
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        # webdriver検出フラグを無効化
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # 1. Bloggerへのログイン
        page.goto("https://www.blogger.com/")
        print("=========================================================")
        print("【ステップ 1/2】")
        print("ブラウザ上でGoogleアカウント（Blogger）にログインしてください。")
        print("ログイン完了後、Bloggerのダッシュボードが表示されたら、")
        print("このターミナルで Enter キーを押してください。")
        print("=========================================================")
        input("Press Enter after Blogger login...")

        # 2. 楽天へのログイン
        page.goto("https://room.rakuten.co.jp/")
        print("=========================================================")
        print("【ステップ 2/2】")
        print("ブラウザ上で楽天ROOM（楽天アカウント）にログインしてください。")
        print("ログイン完了後、マイページやフィードが表示されたら、")
        print("このターミナルで Enter キーを押してください。")
        print("=========================================================")
        input("Press Enter after Rakuten Room login...")
        
        state = context.storage_state()
        
        with open("session.json", "w") as f:
            json.dump(state, f)
            
        print("session.json を作成しました。")
        
        # Base64エンコードした文字列を直接ターミナルに出力
        session_str = json.dumps(state)
        b64_str = base64.b64encode(session_str.encode('utf-8')).decode('utf-8')
        
        print("\n================== BLOGGER_SESSION_B64 (COPY THIS) ==================")
        print(b64_str)
        print("=====================================================================\n")
        print("上記の長い文字列をすべてコピーして、GitHub Secretsの BLOGGER_SESSION_B64 に設定してください。")
        print("※この値にはBloggerと楽天ROOMの両方のログイン状態が含まれるため、コレ！も同時に動作します。")

        browser.close()

if __name__ == "__main__":
    main()
