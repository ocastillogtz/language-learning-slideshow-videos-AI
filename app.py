"""
app.py
Main Flask application — routes live in routes/.
"""
import logging
from flask import Flask, render_template

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

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

app.register_blueprint(projects_bp)
app.register_blueprint(assets_bp)
app.register_blueprint(pipeline_bp)
app.register_blueprint(images_bp)
app.register_blueprint(prompts_bp)

if __name__ == "__main__":
    app.run(debug=True)
