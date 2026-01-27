from flask import Flask, request
import os
import main
import threading

app = Flask(__name__)

# シンプルな実行用エンドポイント
@app.route('/run')
def run_bot():
    # セキュリティのため、GITHUB_TOKENを簡易的なパスワードとしてチェック（任意）
    token = request.args.get('token')
    if os.environ.get('GITHUB_TOKEN') and token != os.environ.get('GITHUB_TOKEN'):
        return "Unauthorized", 401
    
    # 実行中かどうかをチェックする仕組みがあると良いですが、ひとまずスレッドで開始
    thread = threading.Thread(target=main.main)
    thread.start()
    
    return "Process started: AI News collection is running in the background."


@app.route('/')
def index():
    return "AI News Bot is running. Use /run to trigger collection."

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
