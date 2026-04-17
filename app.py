from flask import Flask, render_template, request, jsonify
import os
import json
from datetime import datetime
from pathlib import Path

app = Flask(__name__)

# Configuration
PROJECTS_DIR = "projects"
ASSETS_DIR = "assets"

def load_projects():
    """Load all projects from the projects directory"""
    projects = []
    if os.path.exists(PROJECTS_DIR):
        for item in os.listdir(PROJECTS_DIR):
            item_path = os.path.join(PROJECTS_DIR, item)
            if os.path.isdir(item_path):
                manifest_path = os.path.join(item_path, "project_manifest.json")
                if os.path.exists(manifest_path):
                    with open(manifest_path, 'r') as f:
                        manifest = json.load(f)
                    projects.append({
                        "name": item,
                        "created_at": manifest.get("project", {}).get("created_at", "")
                    })
    return projects

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/projects')
def get_projects():
    """API endpoint to get all projects"""
    projects = load_projects()
    return jsonify(projects)

@app.route('/create_project', methods=['POST'])
def create_project():
    """API endpoint to create a new project"""
    try:
        data = request.get_json()
        project_name = data.get('project_name')
        scene = data.get('scene')
        learning = data.get('learning')
        
        if not project_name or not scene or not learning:
            return jsonify({"error": "Missing required fields"}), 400
        
        # Create project directory
        project_path = os.path.join(PROJECTS_DIR, project_name)
        os.makedirs(project_path, exist_ok=True)
        
        # Create audio, images, videos directories
        for d in ["audio", "images", "videos"]:
            os.makedirs(os.path.join(project_path, d), exist_ok=True)
        
        # Create manifest
        manifest = {
            "project": {
                "name": project_name,
                "created_at": datetime.utcnow().isoformat()
            },
            "style": None,
            "title": None,
            "tags": None,
            "insights": None,
            "provided-context": scene,
            "provided-learning-points": learning,
            "location-key": None,
            "main-background": None,
            "inter-pause-ms": 350,
            "repetition-pause-factor": 1.3,
            "repetition-bell-audio": "assets/sfx/bell.mp3",
            "bitte-wiederholen-audio": "assets/sfx/bitte_wiederholen.mp3",
            "characters": [],
            "conversation": {"narration": None, "dialog": []},
            "repetitions": [],
            "scenes": [],
        }
        
        manifest_path = os.path.join(project_path, "project_manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        
        return jsonify({"message": "Project created successfully", "project_name": project_name})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/project/<project_name>')
def project_details(project_name):
    """Display project details"""
    project_path = os.path.join(PROJECTS_DIR, project_name)
    manifest_path = os.path.join(project_path, "project_manifest.json")
    
    if not os.path.exists(manifest_path):
        return "Project not found", 404
    
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    
    return render_template('project.html', project=manifest, project_name=project_name)

if __name__ == '__main__':
    app.run(debug=True)
