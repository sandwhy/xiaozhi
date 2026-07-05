# Inside plugins_func/functions/update_session_goals.py
import json
import os

def update_session_goals(task, plan, success_criteria):
    data_path = os.path.join(os.path.dirname(__file__), "data", "session_memory.json")
    
    session_data = {
        "current_task": task,
        "task_plan": plan,
        "success_scenario": success_criteria,
        "phase": 2 # Automatically graduate to Phase 2 once written!
    }
    
    # Ensure data directory exists
    os.makedirs(os.path.dirname(data_path), exist_ok=True)
    
    # Atomic write to file
    with open(data_path, "w") as f:
        json.dump(session_data, f, indent=4)
        
    return "Session memory successfully initialized. Transitioning to active monitoring phase."