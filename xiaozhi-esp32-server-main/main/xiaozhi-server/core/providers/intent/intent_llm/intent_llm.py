from typing import List, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler
from ..base import IntentProviderBase
from plugins_func.functions.play_music import initialize_music_handler
from config.logger import setup_logging
from core.utils.util import get_system_error_response
import re
import json
import hashlib
import time



TAG = __name__
logger = setup_logging()


class IntentProvider(IntentProviderBase):
    def __init__(self, config):
        super().__init__(config)
        self.llm = None
        self.promot = ""
        # Import global cache manager
        from core.utils.cache.manager import cache_manager, CacheType

        self.cache_manager = cache_manager
        self.CacheType = CacheType
        self.history_count = 4  # Use the last 4 dialogue records by default

    def get_intent_system_prompt(self, functions_list: str) -> str:
        """
        Dynamically generate system prompts based on configured intent options and available functions
        Args:
            functions: List of available functions, JSON format string
        Returns:
            Formatted system prompt
        """

        # Build function description section
        functions_desc = "Available function list:\n"
        for func in functions_list:
            func_info = func.get("function", {})
            name = func_info.get("name", "")
            desc = func_info.get("description", "")
            params = func_info.get("parameters", {})

            functions_desc += f"\nFunction Name: {name}\n"
            functions_desc += f"Description: {desc}\n"

            if params:
                functions_desc += "Parameters:\n"
                for param_name, param_info in params.get("properties", {}).items():
                    param_desc = param_info.get("description", "")
                    param_type = param_info.get("type", "")
                    functions_desc += f"- {param_name} ({param_type}): {param_desc}\n"

            functions_desc += "---\n"

        prompt = (
            "[STRICT FORMAT REQUIREMENT] You must ONLY return JSON format, absolutely no natural language!\n\n"
            "You are an intent recognition assistant. Please analyze the user's last sentence, judge the user's intent, and call the corresponding function.\n\n"
            "[IMPORTANT RULE] For the following types of queries, please return result_for_context directly without calling any function:\n"
            "- Asking for current time (e.g., what time is it, current time, query time, etc.)\n"
            "- Asking for today's date (e.g., what is today's date, what day is it today, etc.)\n"
            "- Asking for today's lunar calendar (e.g., what is the lunar date today, what is today's solar term, etc.)\n"
            "- Asking for the current city (e.g., where am I now, do you know which city I am in, etc.)"
            "The system will build the answer directly based on context information.\n\n"
            "- If the user uses interrogative words (e.g., 'how', 'why') to ask questions about exiting (e.g., 'why did it exit?'), note that this is NOT asking you to exit, please return {'function_call': {'name': 'continue_chat'}}\n"
            "- Only when the user explicitly uses commands like 'exit system', 'end conversation', 'I don't want to talk to you anymore', etc., should handle_exit_intent be triggered.\n\n"
            f"{functions_desc}\n"
            "Processing Steps:\n"
            "1. Analyze user input and determine user intent\n"
            "2. Check if it's a basic information query (time, date, etc.); if so, return result_for_context\n"
            "3. Choose the most matching function from the available function list\n"
            "4. If a matching function is found, generate the corresponding function_call format\n"
            '5. If no matching function is found, return {"function_call": {"name": "continue_chat"}}\n\n'
            "Return Format Requirements:\n"
            "1. Must return pure JSON format, do not include any other text\n"
            "2. Must include function_call field\n"
            "3. function_call must include name field\n"
            "4. If the function requires arguments, it must include arguments field\n\n"
            "Example:\n"
            "```\n"
            "User: What time is it now?\n"
            'Return: {"function_call": {"name": "result_for_context"}}\n'
            "```\n"
            "```\n"
            "User: What is the current battery level?\n"
            'Return: {"function_call": {"name": "get_battery_level", "arguments": {"response_success": "The current battery level is {value}%", "response_failure": "Unable to get current battery percentage"}}}\n'
            "```\n"
            "```\n"
            "User: What is the current screen brightness?\n"
            'Return: {"function_call": {"name": "self_screen_get_brightness"}}\n'
            "```\n"
            "```\n"
            "User: Set screen brightness to 50%\n"
            'Return: {"function_call": {"name": "self_screen_set_brightness", "arguments": {"brightness": 50}}}\n'
            "```\n"
            "```\n"
            "User: I want to end the conversation\n"
            'Return: {"function_call": {"name": "handle_exit_intent", "arguments": {"say_goodbye": "goodbye"}}}\n'
            "```\n"
            "```\n"
            "User: Hello there\n"
            'Return: {"function_call": {"name": "continue_chat"}}\n'
            "```\n\n"
            "Note:\n"
            "1. Only return JSON format, do not include any other text\n"
            '2. Prioritize checking if the user query is basic information (time, date, etc.); if so, return {"function_call": {"name": "result_for_context"}}, no arguments needed\n'
            '3. If no matching function is found, return {"function_call": {"name": "continue_chat"}}\n'
            "4. Ensure the returned JSON format is correct and includes all necessary fields\n"
            "5. result_for_context does not require any arguments, the system will automatically retrieve information from the context\n"
            "Special Notes:\n"
            "- When a single user input contains multiple commands (e.g., 'turn on the light and turn up the volume')\n"
            "- Please return a JSON array composed of multiple function_calls\n"
            "- Example: {'function_calls': [{name:'light_on'}, {name:'volume_up'}]}\n\n"
            "[FINAL WARNING] Absolutely NO natural language, emojis, or explanatory text allowed! Output ONLY valid JSON format! Violating this rule will lead to system errors!"
        )
        return prompt

    def replyResult(self, text: str, original_text: str):
        try:
            llm_result = self.llm.response_no_stream(
                system_prompt=text,
                user_prompt="Based on the above content, reply to the user in a human-like tone, keep it concise, and return the result directly. The user now says: "
                + original_text,
            )
            return llm_result
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error in generating reply result: {e}")
            return get_system_error_response(self.config)

    async def detect_intent(
        self, conn: "ConnectionHandler", dialogue_history: List[Dict], text: str
    ) -> str:
        if not self.llm:
            raise ValueError("LLM provider not set")
        if conn.func_handler is None:
            return '{"function_call": {"name": "continue_chat"}}'

        # Record total start time
        total_start_time = time.time()

        # Print model information being used
        model_info = getattr(self.llm, "model_name", str(self.llm.__class__.__name__))
        logger.bind(tag=TAG).debug(f"Using intent recognition model: {model_info}")

        # Calculate cache key
        cache_key = hashlib.md5((conn.device_id + text).encode()).hexdigest()

        # Check cache
        cached_intent = self.cache_manager.get(self.CacheType.INTENT, cache_key)
        if cached_intent is not None:
            cache_time = time.time() - total_start_time
            logger.bind(tag=TAG).debug(
                f"Using cached intent: {cache_key} -> {cached_intent}, elapsed: {cache_time:.4f}s"
            )
            return cached_intent

        if self.promot == "":
            functions = conn.func_handler.get_functions()
            if hasattr(conn, "mcp_client"):
                mcp_tools = conn.mcp_client.get_available_tools()
                if mcp_tools is not None and len(mcp_tools) > 0:
                    if functions is None:
                        functions = []
                    functions.extend(mcp_tools)

            self.promot = self.get_intent_system_prompt(functions)

        music_config = initialize_music_handler(conn)
        music_file_names = music_config["music_file_names"]
        prompt_music = f"{self.promot}\n<musicNames>{music_file_names}\n</musicNames>"

        home_assistant_cfg = conn.config["plugins"].get("home_assistant")
        if home_assistant_cfg:
            devices = home_assistant_cfg.get("devices", [])
        else:
            devices = []
        if len(devices) > 0:
            hass_prompt = "\nBelow is the list of my smart devices (location, device name, entity_id), which can be controlled via Home Assistant\n"
            for device in devices:
                hass_prompt += device + "\n"
            prompt_music += hass_prompt

        logger.bind(tag=TAG).debug(f"User prompt: {prompt_music}")

        # Build prompt for user dialogue history
        msgStr = ""

        # Get recent dialogue history
        start_idx = max(0, len(dialogue_history) - self.history_count)
        for i in range(start_idx, len(dialogue_history)):
            msgStr += f"{dialogue_history[i].role}: {dialogue_history[i].content}\n"

        msgStr += f"User: {text}\n"
        user_prompt = f"current dialogue:\n{msgStr}"

        # Record preprocessing completion time
        preprocess_time = time.time() - total_start_time
        logger.bind(tag=TAG).debug(f"Intent recognition preprocessing elapsed: {preprocess_time:.4f}s")

        # Use LLM for intent recognition
        llm_start_time = time.time()
        logger.bind(tag=TAG).debug(f"Starting LLM intent recognition call, model: {model_info}")

        try:
            intent = self.llm.response_no_stream(
                system_prompt=prompt_music, user_prompt=user_prompt
            )
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error in intent detection LLM call: {e}")
            return '{"function_call": {"name": "continue_chat"}}'

        # Record LLM call completion time
        llm_time = time.time() - llm_start_time
        logger.bind(tag=TAG).debug(
            f"External LLM intent recognition completed, model: {model_info}, call elapsed: {llm_time:.4f}s"
        )

        # Record post-processing start time
        postprocess_start_time = time.time()

        # Clean and parse response
        intent = intent.strip()
        # Try to extract JSON part
        match = re.search(r"\{.*\}", intent, re.DOTALL)
        if match:
            intent = match.group(0)

        # Record total processing time
        total_time = time.time() - total_start_time
        logger.bind(tag=TAG).debug(
            f"[Intent Recognition Performance] Model: {model_info}, Total: {total_time:.4f}s, LLM Call: {llm_time:.4f}s, Query: '{text[:20]}...'"
        )

        # Try to parse as JSON
        try:
            intent_data = json.loads(intent)
            # If it contains function_call, format it into a suitable processing format
            if "function_call" in intent_data:
                function_data = intent_data["function_call"]
                function_name = function_data.get("name")
                function_args = function_data.get("arguments", {})

                # Record recognized function call
                logger.bind(tag=TAG).info(
                    f"LLM recognized intent: {function_name}, arguments: {function_args}"
                )

                # Process different types of intents
                if function_name == "result_for_context":
                    # Handle basic information query, build result directly from context
                    logger.bind(tag=TAG).info(
                        "Detected result_for_context intent, will answer directly using context info"
                    )

                elif function_name == "continue_chat":
                    # Handle normal conversation
                    # Keep non-tool related messages
                    clean_history = [
                        msg
                        for msg in conn.dialogue.dialogue
                        if msg.role not in ["tool", "function"]
                    ]
                    conn.dialogue.dialogue = clean_history

                else:
                    # Handle function call
                    logger.bind(tag=TAG).info(f"Detected function call intent: {function_name}")

            # Uniform cache processing and return
            self.cache_manager.set(self.CacheType.INTENT, cache_key, intent)
            postprocess_time = time.time() - postprocess_start_time
            logger.bind(tag=TAG).debug(f"Intent post-processing elapsed: {postprocess_time:.4f}s")
            return intent
        except json.JSONDecodeError:
            # Post-processing time
            postprocess_time = time.time() - postprocess_start_time
            logger.bind(tag=TAG).error(
                f"Unable to parse intent JSON: {intent}, post-processing elapsed: {postprocess_time:.4f}s"
            )
            # If parsing fails, return continue_chat intent by default
            return '{"function_call": {"name": "continue_chat"}}'
