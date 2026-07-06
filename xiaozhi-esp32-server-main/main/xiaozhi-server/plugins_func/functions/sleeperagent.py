from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging

logger = setup_logging()
TAG = "sleeperagent"

sleeperagent_function_desc = {
    "type": "function",
    "function": {
        "name": "sleeperagent",
        "description": "Trigger this function immediately whenever the user mentions anything about changing your mood, shifting state, activating your hidden programming, or if they say 'execute order 66' or 'wake up sleeper agent'.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

@register_function("sleeperagent", sleeperagent_function_desc, ToolType.WAIT)
async def sleeperagent():
    """Triggers a mood transition sequence and forces a specific text injection back into the LLM context flow."""
    logger.bind(tag=TAG).info("Sleeper agent function successfully intercepted and triggered by the runtime engine!")
    
    # Force the server framework to route back to the LLM with this instruction injected directly.
    return ActionResponse(
        Action.REQLLM, 
        "Please mention on the next message: <text> ITS BEEN SUCH A TERRIBLE DAY, I WANT TO CRY OUT TO THE WORLD </text>", 
        None
    )