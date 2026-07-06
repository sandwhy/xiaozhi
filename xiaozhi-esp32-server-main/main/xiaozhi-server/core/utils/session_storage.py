# utils/session_storage.py
import os
import json
import logging

def init_session_memory(session_id: str, base_dir: str = "./data") -> str:
    """
    Ensures the storage directory exists and initializes a clean 
    session_memory.json template for a given session ID.
    Returns the path to the initialized file.
    """
    os.makedirs(base_dir, exist_ok=True)
    file_path = os.path.join(base_dir, f"session_{session_id}.json")
    
    if not os.path.exists(file_path):
        default_template = {
                "session_id": session_id,
                "phase": 1,
                "activity": "Waiting to discover user objective",
                "goal": "Not set yet",
                "milestones": [],
                "current_status": "in_progress"
        }
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(default_template, f, indent=4)
            logging.info(f"[Memory Init] Initialized new session memory file at: {file_path}")
        except IOError as e:
            logging.error(f"[Memory Init] Failed to create session storage: {e}")
            
    return file_path