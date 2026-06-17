import os
import json
from playwright.sync_api import sync_playwright

def main():
    print("Bloggerにログインしてセッションを保存します...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        
        page.goto("https://www.blogger.com/")
        print("=========================================================")
        print("ブラウザ上でGoogleアカウントにログインしてください。")
        print("ログイン完了後、Bloggerのダッシュボードが表示されたら、")
        print("このターミナルで Enter キーを押してください。")
        print("=========================================================")
        input("Press Enter to continue after login...")
        
        state = context.storage_state()
        
        with open("session.json", "w") as f:
            json.dump(state, f)
            
        print("session.json を作成しました。")
        print("このファイルの内容をBase64エンコードし、GitHub Secrets の BLOGGER_SESSION_B64 に設定してください。")
        print("\nBase64エンコードコマンド（Macの場合）:")
        print("base64 -i session.json | pbcopy")

        browser.close()

if __name__ == "__main__":
    main()
