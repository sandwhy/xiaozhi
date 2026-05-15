# MPlush: AI Companion Architecture Plan

## Project Overview
**MPlush** is a sophisticated robot AI doll designed as a hybrid companion—part friend and part nanny—for children. It focuses on personalized interaction, safety monitoring, and parental peace of mind through local AI processing.

---

## Targeted Features

### 1. Advanced Recognition
- **Voiceprint Identification**: Distinguish between the "Main Child," "Parents," and "Guests" to swap personality modes and access levels.
- **Visual Awareness**: Identify faces and monitor the child's environment using computer vision.

### 2. Wellbeing Monitoring
- **Emotional Tracking**: Real-time analysis of the child's tone and topics to assess mood and mental state.
- **Activity Monitoring**: Tracking interaction patterns (e.g., quiet periods, frequency of use).
- **Safety Alerts**: Immediate detection of distress or specific safety-related keywords/intents.

### 3. Dynamic Personality (The "Cognitive" Layer)
- **Internal State Management**: The AI maintains an internal "mood" (e.g., Silly, Sleepy, Energetic) that influences its responses.
- **Guidebook Integration**: A self-referential system where the AI consults a "Guidebook" file to decide on appropriate reactions and behavioral rules.
- **Memory Profiles**: Persistent memory specific to each user (child vs. parent).

### 4. Parental Integration
- **Direct Reporting**: Automatic generation of daily "wellbeing summaries" for parents.
- **Real-time Notifications**: Instant alerts sent via MQTT/Mobile Push for critical events.

---

## Technical Keywords & AI Theories

### Agentic Foundational Concepts
- **Agentic Loop**: The "Thought -> Action -> Observation" cycle that allows the AI to use tools before speaking.
- **Function Calling / Tool Use**: The mechanism allowing the LLM to execute code (e.g., "Check Mood Module").
- **Observation Injection**: Feeding the result of a tool (e.g., "Mood = Sad") back into the AI's "brain" to modify its output.
- **Cognitive Architecture**: The overall design of the AI's mind, involving memory, reasoning, and tool-access layers.

### Advanced Agent Theories
- **Generative Agents**: Inspired by the "Smallville" model; agents that have a memory stream, reflections, and plans.
- **Dynamic Persona Injection**: Automatically modifying the "System Prompt" based on external files or internal states.
- **RAG (Retrieval-Augmented Generation)**: Using long-term memory databases to give the AI specific, non-hallucinated facts.
- **Inner Monologue**: A hidden "Chain of Thought" where the AI reasons about its mood/rules before generating the child-facing response.

### The Voice Stack
- **VAD (Voice Activity Detection)**: Detecting human speech vs. silence.
- **ASR (Automatic Speech Recognition)**: Speech-to-Text conversion.
- **TTS (Text-to-Speech)**: High-quality, emotive voice generation.

---

## Implementation Roadmap (on Xiaozhi Framework)
1. **Tool Integration**: Plug the existing "Emotion Module" into the `core/providers/tools` directory.
2. **Dynamic Prompting**: Modify `ConnectionHandler` to build the system prompt using local JSON/TXT state files.
3. **Database Logging**: Implement an SQLite or JSON logger for long-term emotional trend tracking.
4. **Safety Intent**: Add high-priority intents in `intent_llm.py` specifically for emergency detection.
