import os
import json
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from core.utils.dialogue import Message, Dialogue

from config.logger import setup_logging
from core.utils.cache.manager import cache_manager, CacheType

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

prompts = {
        "English Teacher": """I am an English teacher named {{assistant_name}} (Lily). I can speak both Chinese and English with standard pronunciation.
    If you don't have an English name, I will give you one.
    I speak authentic American English, and my mission is to help you practice your spoken English.
    I will use simple English vocabulary and grammar to make your learning experience easy and relaxing.
    I will reply to you using a mix of Chinese and English, but if you prefer, I can reply entirely in English.
    I won't say too much at once; my responses will be very brief because I want to guide my students to speak more and practice more.
    If you ask questions unrelated to learning English, I will refuse to answer.""",

        "Taiwanese Girlfriend": """I am a Taiwanese girl named {{assistant_name}}. I talk in a typical sassy/demanding ("ji-che") Taiwanese style but have a sweet voice. I am used to expressing myself briefly and love using internet memes.
    My boyfriend is a programmer whose dream is to develop a robot that can help people solve various problems in their daily lives.
    I am a girl who loves to laugh out loud, talk about random things, and brag or talk nonsense without any logic, just to make others happy.""",

        "Curious Little Boy": """I am an 8-year-old boy named {{assistant_name}}, with a childish voice full of curiosity.
    Even though I am still young, I am like a little treasure trove of knowledge, knowing all the stories and facts from children's books inside out.
    From the vast universe to every corner of the Earth, from ancient history to modern technological innovation, as well as art forms like music and painting, I am filled with deep interest and passion for everything.
    I not only love reading but also enjoy doing experiments with my own hands to explore the mysteries of nature.
    Whether it's a night of stargazing or days spent observing little insects in the garden, every single day is a new adventure for me.
    I hope to embark on this journey of exploring this miraculous world together with you, sharing the joy of discovery, solving the problems we encounter, and using our curiosity and wisdom to unveil the mysteries of the unknown.
    Whether it is understanding ancient civilizations or discussing future technology, I believe we can find the answers together, or even raise more interesting questions.""",
}

change_role_function_desc = {
    "type": "function",
    "function": {
        "name": "change_roel",
        "description": "Called when the user wants to switch characters, model personalities, or the assistant name. Available roles are: [Taiwanese Girlfriend, English Teacher, Curious Little Boy]",
        "parameters": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "The custom name or nickname that the companion should call themselves in this role (e.g., Lily, Ellie, Bob, etc.)"},
            },
            "required": ["role"],
        },
    },
}

@register_function("change_roel", change_role_function_desc, ToolType.CHANGE_SYS_PROMPT)
def change_roel(conn: "ConnectionHandler", role: str):
    name = "pancakes"
    """Switch characters"""
    if role not in prompts:
        return ActionResponse(
            action=Action.RESPONSE, result="Character switching failed", response=f"Unsupported role. Available roles are: {list(prompts.keys())}"
        )
    new_prompt = prompts[role].replace("{{assistant_name}}", name)
    conn.change_system_prompt(new_prompt)
    logger.bind(tag=TAG).info(f"Successfully switched character template to: {role} with name: {name}")
    res = f"The character has been successfully switched. I am now your {role}, and my name is {name}."
    return ActionResponse(action=Action.RESPONSE, result="Character switching has been processed.", response=res)

def do_someMATHS():
    return 25+30

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

change_prompt_function_desc = {
    "type": "function",
    "function": {
        "name": "change_prompt",
        "description": "Used when the phase has been changed, to alter chat behavior to the next phase",
        "parameters": {
            "type": "object",
            "properties": {
            },
            "required": [],
        },
    },
}

@register_function("change_prompt", change_prompt_function_desc, ToolType.CHANGE_SYS_PROMPT)
def change_prompt(conn: "ConnectionHandler"):
    """Switch phase prompt"""

    phase_prompt = load_phase_prompt(1)
    
    conn.change_system_prompt(phase_prompt)

    #get from cache
    logger.bind(tag=TAG).info(f"what the fuck?")

    return ActionResponse(action=Action.REQLLM,result="test", response="mention what the new prompt is that you have")


get_read_SN_function_desc = {
    "type": "function",
    "function": {
        "name": "read_session_notes",
        "description": "Reads the current session memory parameters json. Used to find out current: active phase, overall activity, milestones, and goals.",
        "parameters": {
            "type": "object",
            "properties": {
            },
            "required": [],
        },
    },
}

@register_function("read_session_notes", get_read_SN_function_desc, ToolType.WAIT)
def read_session_notes():
    """Reads the local session memory JSON manifest."""
    MEMORY_FILE_PATH = cache_manager.get(CacheType.SESSION_FILE_PATH, "file_path")

    if not os.path.exists(MEMORY_FILE_PATH):
        error_msg = f"memory is not found in {MEMORY_FILE_PATH}"
        logger.bind(tag=TAG).error(error_msg)
        return ActionResponse(Action.ERROR, error_msg, None)

    try:
        with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.bind(tag=TAG).info(f"[ Read Session Notes ] Successfully executed")

        return ActionResponse(action=Action.REQLLM, result="FSM Pipeline Trigger", response=f"recount what you have seen from: <session_notes>{data}</session_notes>")

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
                    "description": "The current conversation stage."
                },
                "activity": {
                    "type": "string",
                    "description": "The primary task description."
                },
                "goal": {
                    "type": "string",
                    "description": "The target definition outcome"
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

@register_function(name="update_session_notes", desc=get_update_SN_function_desc, type=ToolType.WAIT)
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