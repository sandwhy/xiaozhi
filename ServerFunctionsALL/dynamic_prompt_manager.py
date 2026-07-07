import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class DynamicPromptManager:
    """
    Manages Finite State Machine (FSM) phase base prompts and injects live 
    environmental telemetry metrics into system instructions on every dialogue turn.
    """
    def __init__(self, memory_path: str = "./data/session_memory.json", prompt_dir: str = "./data/prompts"):
        self.memory_path = memory_path
        self.prompt_dir = prompt_dir
        
        # Fallback prompts if physical prompt text templates are missing from disk
        self.fallbacks = {
            "phase1": "You are a companion assistant in Phase 1 (Onboarding). Learn what user wants to achieve. Do not provide direct answers.",
            "phase2": "You are an educational tutor in Phase 2 (Execution). Help the user track and check off their goals.",
            "phase3": "You are a proactive buddy in Phase 3 (Engagement). User seems distracted or silent. Re-engage them.",
            "default": "You are MPlush, an advanced educational robotic hardware companion."
        }
        
        # Ensure target directories exist safely
        os.makedirs(self.prompt_dir, exist_ok=True)

    def _read_session_state(self) -> dict:
        """Reads current state securely from session storage file."""
        if not os.path.exists(self.memory_path):
            logger.warning(f"Session state manifest not found at {self.memory_path}. Utilizing base defaults.")
            return {"phase": 1, "metrics": {"attention_score": 100, "boredom_score": 0}}
        
        try:
            with open(self.memory_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed parsing session storage: {e}. Falling back to default states.")
            return {"phase": 1, "metrics": {"attention_score": 100, "boredom_score": 0}}

    def _load_base_template(self, phase: str) -> str:
        """Retrieves targeted raw instructions matching current system phase constraint."""
        filename = f"{phase}.txt"
        file_path = os.path.join(self.prompt_dir, filename)
        
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except IOError as e:
                logger.error(f"Could not read prompt template from file {file_path}: {e}")
        
        # Fallback gracefully if prompt file wasn't created yet
        return self.fallbacks.get(phase, self.fallbacks["default"])

    def generate_system_prompt(self) -> str:
        """
        Calculates and hooks together base phase instructions and enhanced context parameters.
        Returns a formatted system string ready for local injection loops.
        """
        # 1. Parse operational metadata state
        state_data = self._read_session_state()
        current_phase_id = state_data.get("phase", 1)
        phase_key = f"phase{current_phase_id}"
        
        # 2. Extract telemetry variables calculated by async tracking processes
        metrics = state_data.get("metrics", {})
        attention = metrics.get("attention_score", 100)
        boredom = metrics.get("boredom_score", 0)
        
        # 3. Retrieve base structural template text
        base_prompt = self._load_base_template(phase_key)
        
        # 4. Synthesize voice safety anchors, timestamp frameworks, and enhancements
        live_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        enhanced_prompt = (
            f"{base_prompt}\n\n"
            f"=== REAL-TIME CONTEXT DATA ===\n"
            f"Current Timestamp: {live_timestamp}\n"
            f"Live Attention Level Score: {attention}/100\n"
            f"Live Boredom Level Score: {boredom}/100\n\n"
            f"=== TTS OUTPUT SAFEGUARDS ===\n"
            f"CRITICAL: You are speaking directly via a Text-to-Speech hardware speaker module. "
            f"Strictly strip all markdown text markers (e.g., **, *, `), bulleted items, and mathematical formatting expressions. "
            f"Use natural text boundaries, clear comma partitions, and structural terminal periods so the speech engine sounds natural."
        )
        
        logger.info(f"Dynamically generated runtime system string context targeting {phase_key}")
        return enhanced_prompt