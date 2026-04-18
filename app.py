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
            "project":  {
                "name": project_name,
                "created_at": datetime.utcnow().isoformat()    # Add created_at timestamp
            },
            "style": None,
            "title": None,
            "tags": [],   # Replace 'None' with an empty list []
            "insights": None,
            "provided-context": scene,
            "provided-learning-points": learning,
            "location-key": None,
            "main-background": None,
            "inter-pause-ms": cfg["inter_pause_ms"],
            "repetition-pause-factor": cfg["repetition_pause_factor"],
            "repetition-bell-audio": "assets/sfx/bell.mp3",
            "bitte-wiederholen-audio": "assets/sfx/bitte_wiederholen.mp3",
            "characters": [],
            "conversation": {"narration": None, "dialog": []},
            "repetitions": [],
            "scenes": [],
        }
        
        manifest_path = os.path.join(project_path, "project_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        return jsonify({"message": "Project created successfully", "project_name": project_name})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
