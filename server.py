from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def index():
    return 'server is running'

def run():
    app.run(host='0.0.0.0', port=80)

def keep_alive():
    web_thread = Thread(target=run)
    web_thread.start()