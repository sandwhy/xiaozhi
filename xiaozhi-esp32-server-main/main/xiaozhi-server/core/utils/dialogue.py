import uuid
import re
from typing import List, Dict
from datetime import datetime


class Message:
    def __init__(
            self,
            role: str,
            content: str = None,
            uniq_id: str = None,
            tool_calls=None,
            tool_call_id=None,
            is_temporary=False,
    ):
        self.uniq_id = uniq_id if uniq_id is not None else str(uuid.uuid4())
        self.role = role
        self.content = content
        self.tool_calls = tool_calls
        self.tool_call_id = tool_call_id
        self.is_temporary = is_temporary  # Mark temporary messages (such as tool call notifications).


class Dialogue:
    def __init__(self):
        self.dialogue: List[Message] = []
        # Get current time
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def put(self, message: Message):
        self.dialogue.append(message)

    def getMessages(self, m, dialogue):
        if m.tool_calls is not None:
            dialogue.append({"role": m.role, "tool_calls": m.tool_calls})
        elif m.role == "tool":
            dialogue.append(
                {
                    "role": m.role,
                    "tool_call_id": (
                        str(uuid.uuid4()) if m.tool_call_id is None else m.tool_call_id
                    ),
                    "content": m.content,
                }
            )
        else:
            dialogue.append({"role": m.role, "content": m.content})

    def get_llm_dialogue(self) -> List[Dict[str, str]]:
        #Directly call `get_llm_dialogue_with_memory`, passing `None` as `memory_str`
        # This ensures the speaker functionality works in all call paths.
        return self.get_llm_dialogue_with_memory(None, None)

    def update_system_message(self, new_content: str):
        """Update or add system message"""
        # Find the first system message
        system_msg = next((msg for msg in self.dialogue if msg.role == "system"), None)
        if system_msg:
            system_msg.content = new_content
        else:
            self.put(Message(role="system", content=new_content))

    def trim_history(self, max_turns: int = 10) -> int:
        """
        Intelligently truncates dialogue history, preserving the integrity of tool calls.

        Args:
            max_turns: The maximum number of dialogue turns to retain (each turn = user + assistant/tool related messages)

        Returns:
            int: The number of messages removed
        """
        if len(self.dialogue) <= max_turns * 2 + 1:  # +1 是系统消息
            return 0

        # Separate system messages and conversation messages
        system_messages = [msg for msg in self.dialogue if msg.role == "system"]
        conversation_messages = [msg for msg in self.dialogue if msg.role != "system"]

        if len(conversation_messages) <= max_turns * 2:
            return 0

        # Intelligent truncation: preserve the integrity of tool calls
        keep_messages = []
        i = len(conversation_messages) - 1
        turn_count = 0

        while i >= 0 and turn_count < max_turns:
            msg = conversation_messages[i]

            # Collect messages from back to front
            if msg.role == "user":
                # Encountering a user message indicates the start of a dialogue round
                keep_messages.insert(0, msg)
                turn_count += 1
                i -= 1
            elif msg.role == "assistant":
                # Collect assistant messages
                keep_messages.insert(0, msg)

                # If this assistant has tool_calls, collect the corresponding tool responses
                if msg.tool_calls is not None:
                    i -= 1
                    # Continue to collect all relevant tool messages
                    while i >= 0 and conversation_messages[i].role == "tool":
                        keep_messages.insert(0, conversation_messages[i])
                        i -= 1
                else:
                    i -= 1
            elif msg.role == "tool":
                # Tool messages should already be collected by the logic above
                # If encountered alone, keep it (to prevent boundary cases)
                keep_messages.insert(0, msg)
                i -= 1
            else:
                i -= 1

        removed_count = len(conversation_messages) - len(keep_messages)

        # Reconstruct the dialogue list
        self.dialogue = system_messages + keep_messages

        return removed_count

    def get_llm_dialogue_with_memory(
            self, memory_str: str = None, voiceprint_config: dict = None
    ) -> List[Dict[str, str]]:
        # Build dialogue
        dialogue = []

        # Add system prompts and memories
        system_message = next(
            (msg for msg in self.dialogue if msg.role == "system"), None
        )

        if system_message:
            # Base system prompt
            enhanced_system_prompt = system_message.content
            # Replace time placeholder
            enhanced_system_prompt = enhanced_system_prompt.replace(
                "{{current_time}}", datetime.now().strftime("%H:%M")
            )

            # Add speaker personalization description
            try:
                speakers = voiceprint_config.get("speakers", [])
                if speakers:
                    enhanced_system_prompt += "\n\n<speakers_info>"
                    for speaker_str in speakers:
                        try:
                            parts = speaker_str.split(",", 2)
                            if len(parts) >= 2:
                                name = parts[1].strip()
                                # 如果描述为空，则为""
                                description = (
                                    parts[2].strip() if len(parts) >= 3 else ""
                                )
                                enhanced_system_prompt += f"\n- {name}：{description}"
                        except:
                            pass
                    enhanced_system_prompt += "\n\n</speakers_info>"
            except:
                # Configuration reading failed, ignore the error and do not affect other functions
                pass

            # Use regular expressions to match the <memory> tag, regardless of the content in between
            if memory_str is not None:
                enhanced_system_prompt = re.sub(
                    r"<memory>.*?</memory>",
                    f"<memory>\n{memory_str}\n</memory>",
                    enhanced_system_prompt,
                    flags=re.DOTALL,
                )
            dialogue.append({"role": "system", "content": enhanced_system_prompt})

        # Add user and assistant dialogue
        for m in self.dialogue:
            if m.role != "system":  # Skip the original system message
                self.getMessages(m, dialogue)

        return dialogue
