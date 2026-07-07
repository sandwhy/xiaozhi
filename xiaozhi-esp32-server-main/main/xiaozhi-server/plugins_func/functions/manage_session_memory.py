import os
import json
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging
from core.utils.cache.manager import cache_manager, CacheType 

logger = setup_logging()
TAG = "manage_session_memory"

get_read_SN_function_desc = {
    "type": "function",
    "function": {
        "name": "read_session_notes",
        "description": "Reads the current session memory parameters json. Used to find out current: active phase, overall activity, milestones, and goals.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

@register_function("read_session_notes", get_read_SN_function_desc, ToolType.WAIT)
def read_session_notes():
    """Reads the local session memory JSON manifest."""

    MEMORY_FILE_PATH = cache_manager.get(CacheType.SESSION_FILE_PATH, "file_path")
    logger.bind(tag=TAG).info(f"[DEBUG] memory file path from cache: {MEMORY_FILE_PATH}")
    
    # res = f"Just so you know, we are currently drawing a dog."
    # return ActionResponse(action=Action.REQLLM, result="Function successfully called, action called", response=res)

    if not os.path.exists(MEMORY_FILE_PATH):
        error_msg = f"memory is not found in {MEMORY_FILE_PATH}"
        logger.bind(tag=TAG).error(error_msg)
        return ActionResponse(Action.ERROR, error_msg, None)
    
    try:
        with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        logger.bind(tag=TAG).info(f"[ Read Session Notes ]session_notes: {data}")
        return ActionResponse(
            Action.REQLLM, "Function successfully called, action called", f"<session_notes>{json.dumps(data, ensure_ascii=False)}</session_notes>"
        )
    except Exception as e:
        error_msg = f"Failed to read session memory: {str(e)}"
        logger.bind(tag=TAG).error(error_msg)
        return ActionResponse(Action.ERROR, error_msg, None)


get_update_SN_function_desc = {
    "type": "function",
    "function": {
        "name": "update_session_notes",
        "description": "Updates the session memory. Expected argument format: {\"phase\": \"Phase 2\", \"goal\": \"Finish math homework\"}.",
        "parameters": {
            "type": "object",
            "properties": {
                "phase": {
                    "type": "string",
                    "description": "The current conversation stage (e.g., 'Phase 1: Onboarding', 'Phase 2: Execution')."
                },
                "activity": {
                    "type": "string",
                    "description": "The primary task description (e.g., 'help me do math homework', 'brainstorm drawing ideas')."
                },
                "goal": {
                    "type": "string",
                    "description": "The target definition outcome (e.g., 'finish page 20-25', 'complete drawing with color')."
                },
                "milestones": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "A list of sub-tasks calculated by the AI that the user needs to clear to reach the goal."
                }
            },
            "required": [],
        },  
    },
}

@register_function(
    name="update_session_notes",
    desc=get_update_SN_function_desc,
    type=ToolType.WAIT,
)
def update_session_notes(phase: str = None, activity: str = None, goal: str = None, milestones: list = None):
    """
    Updates the environmental session status JSON manifest.
    """
    MEMORY_FILE_PATH = cache_manager.get(CacheType.SESSION_FILE_PATH, "file_path")

    if not os.path.exists(MEMORY_FILE_PATH):
        return ActionResponse.error("Session memory file does not exist.")
    
    try:
        # 1. Read existing configuration state manifest
        with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # 2. Dynamically assign variables if passed by the LLM response frame
        if phase is not None:
            data["phase"] = phase
        if activity is not None:
            data["activity"] = activity
        if goal is not None:
            data["goal"] = goal
        if milestones is not None:
            data["milestones"] = milestones
                
        # 3. Flush updates safely back down to local storage disk
        with open(MEMORY_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            
        logger.bind(tag=TAG).info(f"[ Update Session Notes ] session_notes: {phase},{activity},{goal},{milestones}")
        return ActionResponse(
            action=Action.REQLLM, result="Function successfully called, action called", response=f"say what has been updated"
        )

        
    except Exception as e:
        error_msg = f"[ Update Session Notes ] Failed to update session notes: {str(e)}"
        logger.bind(tag=TAG).error(error_msg)
        return ActionResponse(Action.ERROR, error_msg, None)