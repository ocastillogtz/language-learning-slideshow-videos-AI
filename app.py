"""
app.py
Main Flask application — routes live in routes/.
"""
import logging
import sys
from flask import Flask, render_template
from dotenv import load_dotenv

# Load .env at startup so Flask routes can read the app secrets (FB_APP_ID,
# FB_APP_SECRET, GOOGLE_CLIENT_ID/SECRET). Pipeline modules also load it lazily.
load_dotenv()

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
print(f"Python interpreter: {sys.executable}", flush=True)

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


# Register blueprints
from routes.projects import bp as projects_bp
from routes.assets import bp as assets_bp
from routes.pipeline import bp as pipeline_bp
from routes.images import bp as images_bp
from routes.prompts import bp as prompts_bp
from routes.preview import bp as preview_bp
from routes.connections import bp as connections_bp
from routes.styling import bp as styling_bp

app.register_blueprint(projects_bp)
app.register_blueprint(assets_bp)
app.register_blueprint(pipeline_bp)
app.register_blueprint(images_bp)
app.register_blueprint(prompts_bp)
app.register_blueprint(preview_bp)
app.register_blueprint(connections_bp)
app.register_blueprint(styling_bp)

if __name__ == "__main__":
    app.run(debug=True)
