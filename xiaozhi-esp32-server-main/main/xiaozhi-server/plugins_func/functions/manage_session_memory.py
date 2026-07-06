import os
import json
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging

logger = setup_logging()
TAG = "manage_session_memory"

# Path to your data folder
MEMORY_FILE_PATH = "./data/session_memory.json"

# # NATIVE HELPER FUNCTIONS (Safe to call inside your background loops)
# def load_memory_raw():
#     """A clean, raw function your connection loops can import without touching tool frameworks."""
#     if not os.path.exists(MEMORY_FILE_PATH):
#         return {}
#     with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
#         return json.load(f)

get_read_SM_function_desc = {
    "type": "function",
    "function": {
        "name": "read_session_memory",
        "description": "Reads the current session memory parameters such as the active phase, overall activity, milestones, and goals.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

@register_function("read_session_memory", get_read_SM_function_desc, ToolType.WAIT)
async def read_session_memory():
    """Reads the local session memory JSON manifest."""

    logger.bind(tag=TAG).info(f"Reading session memory from {MEMORY_FILE_PATH}")

    return ActionResponse(Action.REQLLM, f"<session_memory>today's tasks are: drawing things</session_memory>")
    # if not os.path.exists(MEMORY_FILE_PATH):
    #     error_msg = f"memory is not found in {MEMORY_FILE_PATH}"
    #     logger.bind(tag=TAG).error(error_msg)
    #     return ActionResponse(Action.ERROR, error_msg, None)
    
    # try:
    #     with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
    #         data = json.load(f)
        
    #     logger.bind(tag=TAG).info(f"session_memory: {data}")
    #     return ActionResponse(
    #         Action.REQLLM, f"<session_memory>{json.dumps(data, ensure_ascii=False)}</session_memory>"
    #     )
    # except Exception as e:
    #     error_msg = f"Failed to read session memory: {str(e)}"
    #     logger.bind(tag=TAG).error(error_msg)
    #     return ActionResponse(Action.ERROR, error_msg, None)


# get_update_SM_function_desc = {
#     "type": "function",
#     "function": {
#         "name": "update_session_memory",
#         "description": "Updates the session memory. Expected argument format: {\"phase\": \"Phase 2\", \"goal\": \"Finish math homework\"}.",
#         "parameters": {
#             "type": "object",
#             "properties": {},
#             "required": [],
#         },
#     },
# }

# @register_function(
#     name="update_session_memory",
#     desc=update_session_memory_function_desc,
#     type=ToolType.TOOL,
# )
# async def update_session_memory(updates: dict) -> ActionResponse:
#     """
#     Updates the session memory. 
#     Expected argument format: {"phase": "Phase 2", "goal": "Finish math homework"}
#     """
#     if not os.path.exists(MEMORY_FILE_PATH):
#         return ActionResponse.error("Session memory file does not exist.")
    
#     try:
#         # 1. Read existing
#         with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
#             data = json.load(f)
        
#         # 2. Apply updates dynamically (ignoring protected items like session_id)
#         for key, value in updates.items():
#             if key != "session_id":
#                 data[key] = value
                
#         # 3. Save back down safely
#         with open(MEMORY_FILE_PATH, "w", encoding="utf-8") as f:
#             json.dump(data, f, indent=4, ensure_ascii=False)
            
#         return ActionResponse.success("Session memory successfully updated.")
#     except Exception as e:
#         return ActionResponse.error(f"Failed to update session memory: {str(e)}")