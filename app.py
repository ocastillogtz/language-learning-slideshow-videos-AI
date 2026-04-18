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
                "created_at": datetime.utcnow().isoformat()   # Add created_at timestamp
            },
            "style": None,
            "title": None,
            "tags": None,<｜begin▁of▁sentence｜>
!