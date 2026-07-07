from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

def load_phase_prompt(phase_id: int) -> str:
    """
    Safely reads and returns the text content of a targeted phase prompt file.
    
    Args:
        phase_id (int): The current state/phase tracking number (e.g., 1 or 2).
        
    Returns:
        str: The raw plaintext prompt rules, or an empty string if missing.
    """
    # 1. Build an absolute-safe relative path platform-independently
    base_dir = os.path.dirname(os.path.abspath(__file__)) # Context location helper
    
    # Alternatively, use your hardcoded project root data directory directly:
    file_path = os.path.join(".", "data", "phases", f"Phase{phase_id}_prompt.txt")
    
    # 2. Guard rail checking for file existence before reading
    if not os.path.exists(file_path):
        logger.bind(tag=TAG).warning(f"Phase prompt file not found at: {file_path}")
        return ""
        
    try:
        # 3. Read using explicit utf-8 matching your system configs
        with open(file_path, "r", encoding="utf-8") as f:
            prompt_content = f.read()
            
        logger.bind(tag=TAG).info(f"Successfully loaded prompt block from: {file_path}")
        return prompt_content
        
    except Exception as e:
        logger.bind(tag=TAG).error(f"Failed to read phase prompt file {file_path}: {e}")
        return ""

get_read_SN_function_desc = {
    "type": "function",
    "function": {
        "name": "read_session_notes",
        "description": "Reads the current session memory parameters json. Used to find out current: active phase, overall activity, milestones, and goals.",
        "parameters": {
            "type": "object",
            "properties": {
                "notes": {
                    "type": "string",
                    "description": "something you want to say"
                }
            },
            "required": ["notes"],
        },
    },
}

@register_function("read_session_notes", get_read_SN_function_desc, ToolType.WAIT)
def read_session_notes(conn: "ConnectionHandler", notes: str = None):
    """Reads the local session memory JSON manifest."""
    # res = f"Just so you know, we are currently drawing a dog."
    # return ActionResponse(action=Action.REQLLM, result="Function successfully called, action called", response=res)

    if not os.path.exists(MEMORY_FILE_PATH):
        error_msg = f"memory is not found in {MEMORY_FILE_PATH}"
        logger.bind(tag=TAG).error(error_msg)
        return ActionResponse(Action.ERROR, error_msg, None)

    # math = do_someMATHS()
    # logger.bind(tag=TAG).info(f"[DEBUG----------------------] math: {math}")
    # textFile = load_phase_prompt(phase_id=1)
    # logger.bind(tag=TAG).info(f"[DEBUG----------------------] textFile: {textFile}")


    try:
        with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # logger.bind(tag=TAG).info(f"[ Read Session Notes ]session_notes: {data}")
        logger.bind(tag=TAG).info(f"[ Read Session Notes ] Successfully executed")

        current_phase = data.get("phase", 1)

        # Enforce that it's typed as an int if it comes down parsed as a string template
        try:
            current_phase = int(current_phase)
        except (ValueError, TypeError):
            logger.bind(tag=TAG).warning(f"Invalid phase format: {current_phase}. Resetting conversion to 1.")
            current_phase = 1
        
        logger.bind(tag=TAG).info(f"[ FSM Pipeline Trigger ] Extracted current phase id: {current_phase}")
        
        active_phase_rules = load_phase_prompt(current_phase)

        logger.bind(tag=TAG).info(f"[ FSM Pipeline Trigger ] Successfully executed (load_phase_prompt)")
        logger.bind(tag=TAG).info(f"[ FSM Pipeline Trigger ] current active rules: {active_phase_rules}")


        conn.change_system_prompt(active_phase_rules)

        # logger.bind(tag=TAG).info(f"[ FSM Pipeline Trigger ] Successfully executed (change_system_prompt)")
        return ActionResponse(action=Action.REQLLM, result="FSM Pipeline Trigger", response=f"recount what you have seen from: <session_notes>{data}</session_notes>")

    except Exception as e:
        error_msg = f"Failed to read session memory: {str(e)}"
        logger.bind(tag=TAG).error(error_msg)
        return ActionResponse(Action.ERROR, error_msg, None)
