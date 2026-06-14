import os
import google_auth_oauthlib.flow

# ダウンロードしたOAuthクライアントのJSONファイル名
CLIENT_SECRETS_FILE = "client_secret.json"

# Blogger APIを操作するための権限（スコープ）
SCOPES = ['https://www.googleapis.com/auth/blogger']

def main():
    # ローカルサーバーを立ち上げてGoogleの認証画面を開く
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, SCOPES)
    
    # ブラウザが開き、のび太社長のアカウントで「許可」を押すと認証完了
    credentials = flow.run_local_server(port=0)

    # 取得した最強の鍵（リフレッシュトークン）を出力
    print("\n=== 🎯 大成功！以下のリフレッシュトークンをコピーしてね ===")
    print(credentials.refresh_token)
    print("====================================================\n")

if __name__ == '__main__':
    main()