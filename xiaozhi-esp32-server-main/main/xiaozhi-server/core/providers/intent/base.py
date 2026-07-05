from abc import ABC, abstractmethod
from typing import List, Dict
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class IntentProviderBase(ABC):
    def __init__(self, config):
        self.config = config

    def set_llm(self, llm):
        self.llm = llm
        # Get model name and type information
        model_name = getattr(llm, "model_name", str(llm.__class__.__name__))
        # Log more detailed information
        logger.bind(tag=TAG).info(f"Intent recognition setting LLM: {model_name}")

    @abstractmethod
    async def detect_intent(self, conn, dialogue_history: List[Dict], text: str) -> str:
        """
        Detecting the intent of the user's last sentence
        Args:
            dialogue_history: A list of conversation history entries, each containing the role and content.
        Returns:
            Returns the identified intent in the following formats:
            - "Continue Chat"
            - "End Chat"
            - "Play Music Song Title" or "Random Music"
            - "Check Weather Location Name" or "Check Weather [Current Location]"
        """
        pass
