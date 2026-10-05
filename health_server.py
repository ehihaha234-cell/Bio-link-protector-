import os
from flask import Flask

app = Flask(__name__)

@app.get("/")
def root():
    return "Bio Link Protector is running", 200

@app.get("/health")
def health():
    return "OK", 200

def run_health_server():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
