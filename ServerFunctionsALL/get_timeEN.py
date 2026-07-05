from datetime import datetime
from plugins_func.register import register_function, ToolType, ActionResponse, Action

get_timeEN_function_desc = {
    "type": "function",
    "function": {
        "name": "get_timeEN",
        "description": "When user is writing in english, used to get current time in regular format",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "The date to query in YYYY-MM-DD format (e.g., 2024-01-01). If omitted, defaults to the current active date."
                }
            },
            "required": [],
        },
    },
}

@register_function("get_timeEN", get_timeEN_function_desc, ToolType.WAIT)
def get_timeEN(conn: "ConnectionHandler", date: str = None):
    try:
        if date is None:
            now = datetime.now()
            # %I: 12-hour clock hour, %M: minute, %p: AM/PM indicator
            formatted_time = now.strftime("%Y-%m-%d %I:%M %p")
        else:
            # Parse the provided date string to ensure it follows the format
            parsed_date = datetime.strptime(date, "%Y-%m-%d")
            # Convert the parsed date object into a string featuring hours, minutes, and AM/PM (will default to 12:00 AM)
            formatted_time = parsed_date.strftime("%Y-%m-%d %I:%M %p")
        
        logger.bind(tag=TAG).info(f"Acquired time:{formatted_time}")
        
        return ActionResponse(
            Action.REQLLM,
            formatted_time,
            None
        )

    except Exception as e:
        logger.error(f"Acquiring time failed: {e}")
        return ActionResponse(action=Action.RESPONSE, result="Acquiring time failed", response="Acquiring time failed")
