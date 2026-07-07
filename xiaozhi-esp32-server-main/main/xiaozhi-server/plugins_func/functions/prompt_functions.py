import os
import json
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging
from core.utils.cache.manager import cache_manager, CacheType 

logger = setup_logging()
TAG = "prompt_functions"

prompt_cache_read_func_desc = {
    "type": "function",
    "function": {
        "name": "prompt_cache_read",
        "description": "Reads the current session memory parameters json. Used to find out current: active phase, overall activity, milestones, and goals.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

@register_function("prompt_cache_read", prompt_cache_read_func_desc, ToolType.WAIT)
def prompt_cache_read():
    """Reads the local session memory JSON manifest."""

    try: 


        device_cache_key = f"device_prompt:E6:0D:34:D8:41:98"
        quick_prompt = cache_manager.get(CacheType.CONFIG, device_cache_key)

        template_path = "simplified_agent_prompt.txt"
        cache_key = f"prompt_template:{template_path}"
        cached_template = cache_manager.get(CacheType.CONFIG, cache_key)
        # if cached_template is not None:
        #     self.base_prompt_template = cached_template
        #     self.logger.bind(tag=TAG).debug("[load base prompt] Load base prompt template from cache")
        #     return
        template_prompt = cache_manager.get(
            CacheType.CONFIG, cache_key
        )

        logger.bind(tag=TAG).info(f"[ Read Current Prompt ]: this is what we got right now ////////////////////////////////////////")
        logger.bind(tag=TAG).info(f"[ Read Current Prompt ]: QUICK PROMPT: {quick_prompt}")
        logger.bind(tag=TAG).info(f"[ Read Current Prompt ]: TEMPLATE PROMPT: {template_prompt}")
        logger.bind(tag=TAG).info(f"[ Read Current Prompt ]: this is what we got right now ////////////////////////////////////////")
        return ActionResponse(
            Action.RESPONSE, result="got the thing", response="please say peanut butter jelly sandwich"
        )

    except Exception as e:
        error_msg = f"Failed to read current prompt: {str(e)}"
        logger.bind(tag=TAG).error(error_msg)
        return ActionResponse(Action.ERROR, error_msg, None)
