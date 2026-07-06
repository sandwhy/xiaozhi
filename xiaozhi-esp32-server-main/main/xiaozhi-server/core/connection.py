import os
import sys
import copy
import json
import uuid
import time
import queue
import asyncio
import threading
import traceback
import subprocess
import websockets

from core.utils.util import (
    extract_json_from_string,
    check_vad_update,
    check_asr_update,
    filter_sensitive_info,
)
from typing import Dict, Any
from collections import deque
from core.utils.modules_initialize import (
    initialize_modules,
    initialize_tts,
    initialize_asr,
)
from core.handle.reportHandle import report, enqueue_tool_report
from core.providers.tts.default import DefaultTTS
from concurrent.futures import ThreadPoolExecutor
from core.utils.dialogue import Message, Dialogue
from core.providers.asr.dto.dto import InterfaceType
from core.handle.textHandle import handleTextMessage
from core.providers.tools.unified_tool_handler import UnifiedToolHandler
from plugins_func.loadplugins import auto_import_modules
from plugins_func.register import Action, ActionResponse
from core.auth import AuthenticationError
from config.config_loader import get_private_config_from_api
from core.providers.tts.dto.dto import ContentType, TTSMessageDTO, SentenceType
from config.logger import setup_logging, build_module_string, create_connection_logger
from config.manage_api_client import DeviceNotFoundException, DeviceBindException, generate_and_save_chat_title
from core.utils.prompt_manager import PromptManager
from core.utils.voiceprint_provider import VoiceprintProvider
from core.utils.util import get_system_error_response
from core.utils import textUtils

from core.utils.session_storage import init_session_memory



TAG = __name__

# Tool calling rules - used for dynamic injection reminders
TOOL_CALLING_RULES = """
<tool_calling>
    [Core Principle] You are an intelligent assistant with tool capabilities. When a user requests real-time information or to perform an operation, invoke the appropriate tool to retrieve the data; do not fabricate answers out of thin air.

    - **When Tools Must Be Called:**

    1. Real-time information query (news, non-local weather, stock prices, exchange rates, etc.)

    2. Performing operations (playing music, controlling devices, taking photos, setting alarms, etc.)

    3. Knowledge base retrieval (when the tool list contains `search_from_ragflow`, determine whether to call it based on user intent)

    4. Querying lunar calendar information other than today's (tomorrow's lunar calendar, auspicious and inauspicious days for a certain day, solar terms, etc.)

    5. Calling `self_camera_take_photo` when the user says "take a photo," with the default `question` parameter being "describe the item you see."

    - **When Tools Are Not Required:**

    1. Information already provided in `<context>` (current time, today's date, today's lunar calendar, local weather, etc.)

    2. Ordinary conversations, greetings, small talk, emotional exchanges, storytelling

    3. General knowledge Q&A (non-real-time information)

    - **Calling Guidelines:**

    1. Each request should be judged independently; historical tool results should not be reused; the latest data must be retrieved again.

    2. 1. In multitasking situations, call all necessary tools sequentially and summarize the results of each tool in turn, without omission.

    2. Strictly adhere to the parameter requirements of each tool and provide all necessary parameters.

    3. When uncertain, guide the user to clarify or inform them of limitations; never guess or fabricate.

    4. Do not call tools that are not provided. Ignore or explain if old tools mentioned in the conversation are unavailable.

    - **Anti-laziness Mechanism (Highest Priority):**

    1. **Independent Judgment Each Time:** Regardless of whether a tool has been called in the conversation history, the current request must be independently judged based on the current needs to determine whether it needs to be called.

    2. **Prohibition of Pattern Imitation:** Even if previous responses did not call tools, it does not mean that tools can be omitted this time.

    3. **Self-Check:** Before replying, you must ask yourself: "Does this request involve real-time information or operations? If so, have I called a tool?"

    4. **History is Not Equal to Present:** Behavioral patterns in the conversation history do not affect the current judgment; each user request is a completely new beginning.
</tool_calling>
"""

auto_import_modules("plugins_func.functions")


class TTSException(RuntimeError):
    pass


class ConnectionHandler:
    def __init__(
            self,
            config: Dict[str, Any],
            _vad,
            _asr,
            _llm,
            _memory,
            _intent,
            server=None,
    ):
        self.common_config = config
        self.config = copy.deepcopy(config)
        self.session_id = str(uuid.uuid4())
        self.logger = setup_logging()
        self.server = server  # Save a reference to the server instance.

        self.need_bind = False  # whether to bind device
        self.bind_completed_event = asyncio.Event()
        self.bind_code = None  # Verification code for binding device
        self.last_bind_prompt_time = 0  # Timestamp of last bind prompt played (seconds)
        self.bind_prompt_interval = 60  # Bind prompt playback interval (seconds)

        self.read_config_from_api = self.config.get("read_config_from_api", False)

        self.websocket: websockets.ServerConnection | None = None
        self.headers = None
        self.device_id = None
        self.client_ip = None
        self.prompt = None
        self.welcome_msg = None
        self.max_output_size = 0
        self.chat_history_conf = 0
        self.audio_format = "opus"
        self.sample_rate = 24000  # Default sample rate, dynamically updated from client hello message

        # Client status related
        self.client_abort = False
        self.client_is_speaking = False
        self.client_listen_mode = "auto"

        # Thread task related
        self.loop = None  # Get running event loop in handle_connection
        self.stop_event = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=5)

        # Add reporting thread pool
        self.report_queue = queue.Queue()
        self.report_thread = None
        # Can adjust ASR and TTS reporting here in the future; currently both enabled by default
        self.report_asr_enable = self.read_config_from_api
        self.report_tts_enable = self.read_config_from_api

        # Dependent components
        self.vad = None
        self.asr = None
        self.tts = None
        self._asr = _asr
        self._vad = _vad
        self.llm = _llm
        self.memory = _memory
        self.intent = _intent

        self.is_exiting = False  # Mark whether exit process is running

        # Manage voiceprint recognition for each connection separately
        self.voiceprint_provider = None

        # VAD related variables
        self.client_audio_buffer = bytearray()
        self.client_have_voice = False
        self.client_voice_window = deque(maxlen=5)
        self.first_activity_time = 0.0  # Record time of first activity (ms)
        self.last_activity_time = 0.0  # Unified activity timestamp (ms)
        self.vad_last_voice_time = 0.0  # Record last time user spoke (ms)
        self.client_voice_stop = False
        self.last_is_voice = False

        # ASR related variables
        # Because public local ASR might be used in deployment, variables cannot be exposed to public ASR
        # So ASR variables need to be defined here as connection private variables
        self.asr_audio = []
        self.asr_audio_queue = queue.Queue()
        self.current_speaker = None  # Store current speaker

        # LLM related variables
        self.dialogue = Dialogue()

        # Tool call statistics (for monitoring and auto-recovery)
        self.tool_call_stats = {
            'last_call_turn': -1,  # Turn number of last tool call
            'consecutive_no_call': 0,  # Consecutive no-call count
        }

        # TTS related variables
        self.sentence_id = None
        # Handle TTS response with no text returned
        self.tts_MessageText = ""

        # IoT related variables
        self.iot_descriptors = {}
        self.func_handler = None

        self.cmd_exit = self.config["exit_commands"]

        # Whether to close connection after chat ends
        self.close_after_chat = False
        self.load_function_plugin = False
        self.intent_type = "nointent"

        self.timeout_seconds = (
                int(self.config.get("close_connection_no_voice_time", 120)) + 60
        )  # Add 60 seconds to original first-stage close for second-stage close
        self.timeout_task = None

        # {"mcp":true} indicates MCP function enabled
        self.features = None

        # Mark whether connection is from MQTT
        self.conn_from_mqtt_gateway = False

        # Initialize prompt manager
        self.prompt_manager = PromptManager(self.config, self.logger)

    ###### ------------ #######
        # self.is_alive = True

    # async def async_loop(self):
    #     try:
    #         while self.is_alive:
    #             # 1. Execute your custom state evaluation
    #             # (Passing 'self' allows the checker to inspect session data or call tools)
    #             # await check_character_state(self)
    #             self.logger.bind(tag=TAG).info(f"async_loop is running, {self.client_ip} : {self.device_id}")
                
    #             # 2. Control the check interval (e.g., check every 5 seconds)
    #             # Using non-blocking asyncio.sleep yields control back to the main server loop
    #             await asyncio.sleep(5.0)

    #     except asyncio.CancelledError:
    #         print("[MPlush Monitor] Background monitor task was cancelled.")
    #         self.logger.bind(tag=TAG).info("Background monitor task was cancelled.")
    #     except Exception as e:
    #         print(f"[MPlush Monitor] Error encountered in state loop: {e}")
    #         self.logger.bind(tag=TAG).info(f"Error encountered in state loop: {e}")
    #     finally:
    #         print("[MPlush Monitor] Autonomous state checking loop stopped.")
    #         self.logger.bind(tag=TAG).info("Autonomous state checking loop stopped.")

    async def handle_connection(self, ws: websockets.ServerConnection):
        try:
            # Get running event loop (must be in async context)
            self.loop = asyncio.get_running_loop()

            # Get and verify headers
            self.headers = dict(ws.request.headers)
            real_ip = self.headers.get("x-real-ip") or self.headers.get(
                "x-forwarded-for"
            )
            if real_ip:
                self.client_ip = real_ip.split(",")[0].strip()
            else:
                self.client_ip = ws.remote_address[0]
            self.logger.bind(tag=TAG).info(
                f"{self.client_ip} conn - Headers: {self.headers}"
            )

            self.device_id = self.headers.get("device-id", None)

            # Authentication passed, continue processing
            self.websocket = ws

            # Check if from MQTT connection
            request_path = ws.request.path
            self.conn_from_mqtt_gateway = request_path.endswith("?from=mqtt_gateway")
            if self.conn_from_mqtt_gateway:
                self.logger.bind(tag=TAG).info("Connection from: MQTT Gateway")

            # Initialize activity timestamp
            self.first_activity_time = time.time() * 1000
            self.last_activity_time = time.time() * 1000

            # Start timeout check task
            self.timeout_task = asyncio.create_task(self._check_timeout())

            self.welcome_msg = self.config["xiaozhi"]
            self.welcome_msg["session_id"] = self.session_id

            # Read sample rate from configuration
            self.sample_rate = self.welcome_msg["audio_params"]["sample_rate"]
            self.logger.bind(tag=TAG).info(f"Configured output audio sample rate to: {self.sample_rate}")

            # Initialize config and components in background (non-blocking)
            asyncio.create_task(self._background_initialize())

            # asyncio.create_task(self.async_loop())

            try:
                async for message in self.websocket:
                    await self._route_message(message)
            except websockets.exceptions.ConnectionClosed:
                self.logger.bind(tag=TAG).info("Client disconnected")

        except AuthenticationError as e:
            self.logger.bind(tag=TAG).error(f"Authentication failed: {str(e)}")
            return
        except Exception as e:
            stack_trace = traceback.format_exc()
            self.logger.bind(tag=TAG).error(f"Connection error: {str(e)}-{stack_trace}")
            return
        finally:
            try:
                await self._save_and_close(ws)
            except Exception as final_error:
                self.logger.bind(tag=TAG).error(f"Error during final cleanup: {final_error}")
                # Ensure connection is closed even if saving memory fails
                try:
                    await self.close(ws)
                except Exception as close_error:
                    self.logger.bind(tag=TAG).error(
                        f"Error forcing connection close: {close_error}"
                    )

    async def _save_and_close(self, ws):
        """Save memory and close connection"""
        try:
            # Daemon thread 1: Generate title independently (non-memory model dependent)
            if self.session_id:
                def generate_title_task():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(
                            generate_and_save_chat_title(self.session_id)
                        )
                    except Exception as e:
                        self.logger.bind(tag=TAG).error(f"Failed to generate title: {e}")
                    finally:
                        try:
                            loop.close()
                        except Exception:
                            pass

                threading.Thread(target=generate_title_task, daemon=True).start()

            # Daemon thread 2: Old memory saving process (memory only, no title)
            if self.memory:
                # Asynchronously save memory using thread pool
                def save_memory_task():
                    try:
                        # Create new event loop (avoid conflict with main loop)
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(
                            self.memory.save_memory(
                                self.dialogue.dialogue, self.session_id
                            )
                        )
                    except Exception as e:
                        self.logger.bind(tag=TAG).error(f"Failed to save memory: {e}")
                    finally:
                        try:
                            loop.close()
                        except Exception:
                            pass

                # Start thread to save memory, do not wait for completion
                threading.Thread(target=save_memory_task, daemon=True).start()
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Failed to save memory: {e}")
        finally:
            # Close connection immediately, do not wait for memory saving
            try:
                await self.close(ws)
            except Exception as close_error:
                self.logger.bind(tag=TAG).error(
                    f"Failed to close connection after saving memory: {close_error}"
                )

    async def _discard_message_with_bind_prompt(self):
        """Discard message and check if bind prompt playback is needed"""
        current_time = time.time()
        # 检查是否需要播放绑定提示
        if current_time - self.last_bind_prompt_time >= self.bind_prompt_interval:
            self.last_bind_prompt_time = current_time
            # Reuse existing bind prompt logic
            from core.handle.receiveAudioHandle import check_bind_device

            asyncio.create_task(check_bind_device(self))

    async def _route_message(self, message):
        """Message routing"""
        # Discard all messages in exit state
        if self.is_exiting:
           return

        # Check if actual bind status is obtained
        if not self.bind_completed_event.is_set():
            # Actual status not yet obtained, wait until obtained or timeout
            try:
                await asyncio.wait_for(self.bind_completed_event.wait(), timeout=1)
            except asyncio.TimeoutError:
                # Timeout without obtaining actual status, discarding message
                await self._discard_message_with_bind_prompt()
                return

        # Actual status obtained, checking if bind is needed
        if self.need_bind:
            # Bind needed, discarding message
            await self._discard_message_with_bind_prompt()
            return

        # Bind not needed, continuing message processing

        if isinstance(message, str):
            await handleTextMessage(self, message)
        elif isinstance(message, bytes):
            if self.vad is None or self.asr is None:
                return

            # Process audio packet from MQTT gateway
            if self.conn_from_mqtt_gateway and len(message) >= 16:
                handled = await self._process_mqtt_audio_message(message)
                if handled:
                    return

            # Directly process raw message if no header processing needed or no header present
            self.asr_audio_queue.put(message)

    async def _process_mqtt_audio_message(self, message):
        """
        Process audio message from MQTT gateway, parse 16-byte header and extract audio data

        Args:
            message: Audio message containing header

        Returns:
            bool: Whether the message was successfully processed
        """
        try:
            # Extract header info
            timestamp = int.from_bytes(message[8:12], "big")
            audio_length = int.from_bytes(message[12:16], "big")

            # Extract audio data
            if audio_length > 0 and len(message) >= 16 + audio_length:
                # Length specified, extract precise audio data
                audio_data = message[16 : 16 + audio_length]
                # Process sorting based on timestamp
                self._process_websocket_audio(audio_data, timestamp)
                return True
            elif len(message) > 16:
                # No length specified or invalid, remove header and process remaining data
                audio_data = message[16:]
                self.asr_audio_queue.put(audio_data)
                return True
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Failed to parse WebSocket audio packet: {e}")

        # 处理失败，返回False表示需要继续处理
        return False

    def _process_websocket_audio(self, audio_data, timestamp):
        """Process WebSocket format audio packet"""
        # Initialize timestamp sequence management
        if not hasattr(self, "audio_timestamp_buffer"):
            self.audio_timestamp_buffer = {}
            self.last_processed_timestamp = 0
            self.max_timestamp_buffer_size = 20

        # If timestamp is increasing, process directly
        if timestamp >= self.last_processed_timestamp:
            self.asr_audio_queue.put(audio_data)
            self.last_processed_timestamp = timestamp

            # Process subsequent packets in buffer
            processed_any = True
            while processed_any:
                processed_any = False
                for ts in sorted(self.audio_timestamp_buffer.keys()):
                    if ts > self.last_processed_timestamp:
                        buffered_audio = self.audio_timestamp_buffer.pop(ts)
                        self.asr_audio_queue.put(buffered_audio)
                        self.last_processed_timestamp = ts
                        processed_any = True
                        break
        else:
            # Out-of-order packet, buffering
            if len(self.audio_timestamp_buffer) < self.max_timestamp_buffer_size:
                self.audio_timestamp_buffer[timestamp] = audio_data
            else:
                self.asr_audio_queue.put(audio_data)

    async def handle_restart(self, message):
        """Process server restart request"""
        try:

            self.logger.bind(tag=TAG).info("Received server restart command, preparing to execute...")

            # Send confirmation response
            await self.websocket.send(
                json.dumps(
                    {
                        "type": "server",
                        "status": "success",
                        "message": "Server restarting...",
                        "content": {"action": "restart"},
                    }
                )
            )

            # Asynchronously execute restart
            def restart_server():
                """Actual method to execute restart"""
                time.sleep(1)
                self.logger.bind(tag=TAG).info("Executing server restart...")
                subprocess.Popen(
                    [sys.executable, "app.py"],
                    stdin=sys.stdin,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                    start_new_session=True,
                )
                os._exit(0)

            # Execute restart using thread to avoid blocking event loop
            threading.Thread(target=restart_server, daemon=True).start()

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Restart failed: {str(e)}")
            await self.websocket.send(
                json.dumps(
                    {
                        "type": "server",
                        "status": "error",
                        "message": f"Restart failed: {str(e)}",
                        "content": {"action": "restart"},
                    }
                )
            )

    def _initialize_components(self):
        self.logger.bind(tag=TAG).info(f"[Initialize Components] Initializing components")

        try:
            if self.tts is None:
                self.tts = self._initialize_tts()
            # Open TTS channel
            asyncio.run_coroutine_threadsafe(
                self.tts.open_audio_channels(self), self.loop
            )
            if self.need_bind:
                self.bind_completed_event.set()
                return
            self.selected_module_str = build_module_string(
                self.config.get("selected_module", {})
            )
            self.logger = create_connection_logger(self.selected_module_str)

            """Initialize components"""
            if self.config.get("prompt") is not None:
                user_prompt = self.config["prompt"]
                # Initialize using quick prompt
                prompt = self.prompt_manager.get_quick_prompt(user_prompt)
                self.change_system_prompt(prompt)
                self.logger.bind(tag=TAG).info(
                    f"Quick component initialization: prompt success {prompt[:50]}..."
                )

            """Initialize local components"""
            if self.vad is None:
                self.vad = self._vad
            if self.asr is None:
                self.asr = self._initialize_asr()

            # Initialize voiceprint recognition
            self._initialize_voiceprint()
            # Open ASR channel
            asyncio.run_coroutine_threadsafe(
                self.asr.open_audio_channels(self), self.loop
            )

            """Load memory"""
            self._initialize_memory()
            """Load intent recognition"""
            self._initialize_intent()
            """Initialize reporting threads"""
            self._init_report_threads()
            """Update system prompt"""
            self._init_prompt_enhancement()
            """initialize session memory"""
            self._init_session_memory()

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Failed to instantiate component: {e}")

    ###### ------------ #######

    def _init_session_memory(self):
        self.logger.bind(tag=TAG).info(f"[Memory Init] Init session memory")

        """
        Initializes the session memory architecture. Calls the utility 
        layer to establish the JSON persistence template and binds the 
        live telemetry counters to the current network instance.
        """

        # # Ensure a session ID is established for this connection instance
        # if not hasattr(self, 'session_id') or not self.session_id:
        #     self.session_id = f"sess_{int(time.time())}"

        # 1. Initialize JSON storage architecture via decoupled utility module
        self.session_file_path = init_session_memory(self.session_id)
        
        self.logger.bind(tag=TAG).info(f"[INITIALIZING CURRENT SESSION MEMORY JSON] Bound storage path to active instance: {self.session_file_path}")

    def _init_prompt_enhancement(self):

        # Update context info
        self.prompt_manager.update_context_info(self, self.client_ip)
        enhanced_prompt = self.prompt_manager.build_enhanced_prompt(
            self.config["prompt"], self.device_id, self.client_ip
        )
        if enhanced_prompt:
            self.change_system_prompt(enhanced_prompt)
            self.logger.bind(tag=TAG).debug("System prompt enhanced and updated")

    def _init_report_threads(self):
        """Initialize ASR and TTS reporting threads"""
        if not self.read_config_from_api or self.need_bind:
            return
        if self.chat_history_conf == 0:
            return
        if self.report_thread is None or not self.report_thread.is_alive():
            self.report_thread = threading.Thread(
                target=self._report_worker, daemon=True
            )
            self.report_thread.start()
            self.logger.bind(tag=TAG).info("TTS reporting thread started")

    def _initialize_tts(self):
        """Initialize TTS"""
        tts = None
        if not self.need_bind:
            tts = initialize_tts(self.config)

        if tts is None:
            tts = DefaultTTS(self.config, delete_audio_file=True)

        return tts

    def _initialize_asr(self):
        """Initialize ASR"""
        if (
                self._asr is not None
                and hasattr(self._asr, "interface_type")
                and self._asr.interface_type == InterfaceType.LOCAL
        ):
            # If public ASR is a local service, return directly
            # Because one local ASR instance can be shared by multiple connections
            asr = self._asr
        else:
            # If public ASR is a remote service, initialize a new instance
            # Because remote ASR involves WebSocket connection and receiving threads, each connection needs its own instance
            asr = initialize_asr(self.config)

        return asr

    def _initialize_voiceprint(self):
        """Initialize voiceprint recognition for current connection"""
        try:
            voiceprint_config = self.config.get("voiceprint", {})
            if voiceprint_config:
                voiceprint_provider = VoiceprintProvider(voiceprint_config)
                if voiceprint_provider is not None and voiceprint_provider.enabled:
                    self.voiceprint_provider = voiceprint_provider
                    self.logger.bind(tag=TAG).info("Voiceprint recognition enabled dynamically on connection")
                else:
                    self.logger.bind(tag=TAG).warning("Voiceprint recognition enabled but configuration incomplete")
            else:
                self.logger.bind(tag=TAG).info("Voiceprint recognition not enabled")
        except Exception as e:
            self.logger.bind(tag=TAG).warning(f"Voiceprint initialization failed: {str(e)}")

    async def _background_initialize(self):
        """Initialize config and components in background (non-blocking)"""
        try:
            # Asynchronously obtain differentiated configuration
            await self._initialize_private_config_async()
            # Initialize the component in the thread pool
            self.executor.submit(self._initialize_components)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Background initialization failed: {e}")

    async def _initialize_private_config_async(self):
        """Retrieve differentiated configuration asynchronously from the interface (asynchronous version, does not block the main loop)"""
        if not self.read_config_from_api:
            self.need_bind = False
            self.bind_completed_event.set()
            return
        try:
            begin_time = time.time()
            private_config = await get_private_config_from_api(
                self.config,
                self.headers.get("device-id"),
                self.headers.get("client-id", self.headers.get("device-id")),
            )
            private_config["delete_audio"] = bool(self.config.get("delete_audio", True))
            self.logger.bind(tag=TAG).info(
                f"{time.time() - begin_time} seconds, asynchronously fetched differentiated configuration successfully: {json.dumps(filter_sensitive_info(private_config), ensure_ascii=False)}"
            )
            self.need_bind = False
            self.bind_completed_event.set()
        except DeviceNotFoundException as e:
            self.need_bind = True
            private_config = {}
        except DeviceBindException as e:
            self.need_bind = True
            self.bind_code = e.bind_code
            private_config = {}
        except Exception as e:
            self.need_bind = True
            self.logger.bind(tag=TAG).error(f"Failed to asynchronously fetch differentiated configuration: {e}")
            private_config = {}

        init_llm, init_tts, init_memory, init_intent = (
            False,
            False,
            False,
            False,
        )

        init_vad = check_vad_update(self.common_config, private_config)
        init_asr = check_asr_update(self.common_config, private_config)

        if init_vad:
            self.config["VAD"] = private_config["VAD"]
            self.config["selected_module"]["VAD"] = private_config["selected_module"][
                "VAD"
            ]
        if init_asr:
            self.config["ASR"] = private_config["ASR"]
            self.config["selected_module"]["ASR"] = private_config["selected_module"][
                "ASR"
            ]
        if private_config.get("TTS", None) is not None:
            init_tts = True
            self.config["TTS"] = private_config["TTS"]
            self.config["selected_module"]["TTS"] = private_config["selected_module"][
                "TTS"
            ]
        if private_config.get("LLM", None) is not None:
            init_llm = True
            self.config["LLM"] = private_config["LLM"]
            self.config["selected_module"]["LLM"] = private_config["selected_module"][
                "LLM"
            ]
        if private_config.get("VLLM", None) is not None:
            self.config["VLLM"] = private_config["VLLM"]
            self.config["selected_module"]["VLLM"] = private_config["selected_module"][
                "VLLM"
            ]
        if private_config.get("Memory", None) is not None:
            init_memory = True
            self.config["Memory"] = private_config["Memory"]
            self.config["selected_module"]["Memory"] = private_config[
                "selected_module"
            ]["Memory"]
        if private_config.get("Intent", None) is not None:
            init_intent = True
            self.config["Intent"] = private_config["Intent"]
            model_intent = private_config.get("selected_module", {}).get("Intent", {})
            self.config["selected_module"]["Intent"] = model_intent
            # Load plugin configuration
            if model_intent != "Intent_nointent":
                plugin_from_server = private_config.get("plugins", {})
                for plugin, config_str in plugin_from_server.items():
                    plugin_from_server[plugin] = json.loads(config_str)
                self.config["plugins"] = plugin_from_server
                self.config["Intent"][self.config["selected_module"]["Intent"]][
                    "functions"
                ] = plugin_from_server.keys()
        if private_config.get("prompt", None) is not None:
            self.config["prompt"] = private_config["prompt"]
        # Get voiceprint info
        if private_config.get("voiceprint", None) is not None:
            self.config["voiceprint"] = private_config["voiceprint"]
        if private_config.get("summaryMemory", None) is not None:
            self.config["summaryMemory"] = private_config["summaryMemory"]
        if private_config.get("device_max_output_size", None) is not None:
            self.max_output_size = int(private_config["device_max_output_size"])
        if private_config.get("chat_history_conf", None) is not None:
            self.chat_history_conf = int(private_config["chat_history_conf"])
        if private_config.get("mcp_endpoint", None) is not None:
            self.config["mcp_endpoint"] = private_config["mcp_endpoint"]
        if private_config.get("context_providers", None) is not None:
            self.config["context_providers"] = private_config["context_providers"]

        # 使用 run_in_executor 在线程池中执行 initialize_modules，避免阻塞主循环
        try:
            modules = await self.loop.run_in_executor(
                None,  # 使用默认线程池
                initialize_modules,
                self.logger,
                private_config,
                init_vad,
                init_asr,
                init_llm,
                init_tts,
                init_memory,
                init_intent,
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Failed to instantiate component: {e}")
            modules = {}
        if modules.get("tts", None) is not None:
            self.tts = modules["tts"]
        if modules.get("vad", None) is not None:
            self.vad = modules["vad"]
        if modules.get("asr", None) is not None:
            self.asr = modules["asr"]
        if modules.get("llm", None) is not None:
            self.llm = modules["llm"]
        if modules.get("intent", None) is not None:
            self.intent = modules["intent"]
        if modules.get("memory", None) is not None:
            self.memory = modules["memory"]

    def _initialize_memory(self):
        self.logger.bind(tag=TAG).info(f"[Initialize Memory] Initializing memory")
        if self.memory is None:
            return
        """Initialize memory module"""
        self.memory.init_memory(
            role_id=self.device_id,
            llm=self.llm,
            summary_memory=self.config.get("summaryMemory", None),
            save_to_file=not self.read_config_from_api,
        )

        # Get memory summary configuration
        memory_config = self.config["Memory"]
        memory_type = self.config["Memory"][self.config["selected_module"]["Memory"]][
            "type"
        ]
        # If using nomen or mem_report_only, return directly
        if memory_type == "nomem" or memory_type == "mem_report_only":
            return
        # Use mem_local_short mode
        elif memory_type == "mem_local_short":
            memory_llm_name = memory_config[self.config["selected_module"]["Memory"]][
                "llm"
            ]
            if memory_llm_name and memory_llm_name in self.config["LLM"]:
                # If a dedicated LLM is configured, create an independent LLM instance
                from core.utils import llm as llm_utils

                memory_llm_config = self.config["LLM"][memory_llm_name]
                memory_llm_type = memory_llm_config.get("type", memory_llm_name)
                memory_llm = llm_utils.create_instance(
                    memory_llm_type, memory_llm_config
                )
                self.logger.bind(tag=TAG).info(
                    f"A dedicated LLM was created for memory summarization.: {memory_llm_name}, type: {memory_llm_type}"
                )
                self.memory.set_llm(memory_llm)
            else:
                # Otherwise use main LLM
                self.memory.set_llm(self.llm)
                self.logger.bind(tag=TAG).info("Using main LLM as intent recognition model")

    def _initialize_intent(self):
        if self.intent is None:
            return
        self.intent_type = self.config["Intent"][
            self.config["selected_module"]["Intent"]
        ]["type"]
        if self.intent_type == "function_call" or self.intent_type == "intent_llm":
            self.load_function_plugin = True
        """Initialize intent recognition module"""
        # 获取意图识别配置
        intent_config = self.config["Intent"]
        intent_type = self.config["Intent"][self.config["selected_module"]["Intent"]][
            "type"
        ]

        # If using nointent, return directly
        if intent_type == "nointent":
            return
        # Use intent_llm mode
        elif intent_type == "intent_llm":
            intent_llm_name = intent_config[self.config["selected_module"]["Intent"]][
                "llm"
            ]

            if intent_llm_name and intent_llm_name in self.config["LLM"]:
                # If dedicated LLM is configured, create independent LLM instance
                from core.utils import llm as llm_utils

                intent_llm_config = self.config["LLM"][intent_llm_name]
                intent_llm_type = intent_llm_config.get("type", intent_llm_name)
                intent_llm = llm_utils.create_instance(
                    intent_llm_type, intent_llm_config
                )
                self.logger.bind(tag=TAG).info(
                    f"Created dedicated LLM for intent recognition: {intent_llm_name}, type: {intent_llm_type}"
                )
                self.intent.set_llm(intent_llm)
            else:
                # Otherwise use main LLM
                self.intent.set_llm(self.llm)
                self.logger.bind(tag=TAG).info("Using main LLM as intent recognition model")

        """Load unified tool handler"""
        self.func_handler = UnifiedToolHandler(self)

        # Asynchronously initialize tool handler
        if hasattr(self, "loop") and self.loop:
            asyncio.run_coroutine_threadsafe(self.func_handler._initialize(), self.loop)

    def change_system_prompt(self, prompt):
        self.prompt = prompt
        # 更新系统prompt至上下文
        self.dialogue.update_system_message(self.prompt)

    def chat(self, query, depth=0):
        # Save current task's sentence_id to local variable to avoid being overwritten by new tasks
        current_sentence_id = None

        if query is not None:
            self.logger.bind(tag=TAG).info(f"LLM received user message: {query}")

        # Create new session ID and send FIRST request when at the top level
        if depth == 0:
            current_sentence_id = str(uuid.uuid4().hex)
            self.sentence_id = current_sentence_id  # Update shared attribute
            self.dialogue.put(Message(role="user", content=query))
            self.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=current_sentence_id,
                    sentence_type=SentenceType.FIRST,
                    content_type=ContentType.ACTION,
                )
            )
        else:
            # Use current sentence_id during recursive calls
            current_sentence_id = self.sentence_id

        # Set max recursion depth to avoid infinite loops; adjust based on needs
        MAX_DEPTH = 5
        force_final_answer = False  # Mark whether to force final answer

        if depth >= MAX_DEPTH:
            self.logger.bind(tag=TAG).debug(
                f"Max tool call depth {MAX_DEPTH} reached, forcing answer based on existing info"
            )
            force_final_answer = True
            # Add system instruction, requiring LLM to answer based on existing info
            self.dialogue.put(
                Message(
                    role="user",
                    content="[System Prompt] Max tool call limit reached. Please provide the final answer directly based on all information obtained so far. Do not attempt to call any more tools.",
                )
            )

        # Long dialogue tool call reminder: when there are many turns, remind model to use tools correctly
        force_reminder = False  # Whether to force reminder

        if depth == 0 and query is not None:
            dialogue_length = len(self.dialogue.dialogue)
            current_turn = dialogue_length // 2

            # Detect interval since last consecutive tool non-call
            if self.tool_call_stats['last_call_turn'] >= 0:
                # self.logger.bind(tag=TAG).info(
                #     f"Last tool call turn: {self.tool_call_stats['last_call_turn']}"
                # )
                turns_since_last = current_turn - self.tool_call_stats['last_call_turn']
                if turns_since_last > 3:  # More than 3 turns without calling
                    self.logger.bind(tag=TAG).warning(
                        f"Detected {turns_since_last} turns without tool calls, potentially entering lazy mode, forcing reminder injection"
                    )
                    force_reminder = True

            # Dialogue history truncation: prevent long history from spreading "lazy mode"
            # When dialogue history exceeds threshold, keep the most recent 10 turns
            # max_dialogue_turns = 10
            # if dialogue_length > max_dialogue_turns * 2:
            #     removed = self.dialogue.trim_history(max_turns=max_dialogue_turns)
            #     if removed > 0:
            #         self.logger.bind(tag=TAG).info(
            #             f"Dialogue history too long ({dialogue_length} messages), intelligently truncated to keep recent {max_dialogue_turns} turns, removed {removed} messages"
            #         )

        # Define intent functions
        functions = None
        # When max depth is reached, disable tool calls and force LLM to answer directly
        if (
                self.intent_type == "function_call"
                and hasattr(self, "func_handler")
                and not force_final_answer
        ):
            functions = self.func_handler.get_functions()
            self.logger.bind(tag=TAG).info(f"Got functions: {functions}")

        # Long dialogue tool call rule reinforcement: dynamically generate reminders based on currently available tools
        tool_call_reminder = None
        if depth == 0 and query is not None and functions is not None:
            dialogue_length = len(self.dialogue.dialogue)
            # When dialogue history exceeds 4 messages, inject rule reinforcement
            if dialogue_length > 4:
                tool_summary = self._get_tool_summary(functions)
                if tool_summary:
                    # Use different reminder intensities based on dialogue length and laziness detection
                    if force_reminder:
                        # Strong reminder - includes full rule prefix
                        tool_call_reminder = (
                            TOOL_CALLING_RULES +
                            f"[Important Reminder] Multiple turns without using tools, check if response missed necessary tool calls! No tool was used in the previous turn, you must re-judge if tools are needed this turn."
                            f"Currently available tools: {tool_summary}。"
                        )
                        reminder_level = "Strong"
                    else:
                        # Medium reminder - includes rule prefix
                        tool_call_reminder = (
                            TOOL_CALLING_RULES +
                            f"Currently available tools: {tool_summary}。"
                            f"Call only when user request involves real-time info queries or action execution; daily conversation does not need calls."
                        )
                        reminder_level = "Medium"
                    self.logger.bind(tag=TAG).debug(
                        f"Long dialogue history ({dialogue_length} messages), injected {reminder_level} level tool call rule reinforcement, current available tools: {tool_summary}"
                    )

        response_message = []

        # If there is a tool call reminder, temporarily add it to conversation (marked as temporary message)
        if tool_call_reminder:
            self.dialogue.put(Message(role="user", content=tool_call_reminder, is_temporary=True))
        ### CALLING UP OLLAMA
        try:
            # Use dialogue with memory
            memory_str = None
            # Query memory only when query is non-empty (representing user inquiry)
            if self.memory is not None and query:
                future = asyncio.run_coroutine_threadsafe(
                    self.memory.query_memory(query), self.loop
                )
                memory_str = future.result()

            if self.intent_type == "function_call" and functions is not None:
                # Use streaming interface supporting functions
                llm_responses = self.llm.response_with_functions(
                    self.session_id,
                    self.dialogue.get_llm_dialogue_with_memory(
                        memory_str, self.config.get("voiceprint", {})
                    ),
                    functions=functions,
                )
            else:
                llm_responses = self.llm.response(
                    self.session_id,
                    self.dialogue.get_llm_dialogue_with_memory(
                        memory_str, self.config.get("voiceprint", {})
                    ),
                )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"LLM Error processing {query}: {e}")
            return None

        ### Processing streaming responses
        tool_call_flag = False
        # Process multiple parallel tool calls - using list storage
        tool_calls_list = []  # Format: [{"id": "", "name": "", "arguments": ""}]
        content_arguments = ""
        emotion_flag = True
        try:
            for response in llm_responses:
                if self.client_abort:
                    break
                if self.intent_type == "function_call" and functions is not None:
                    content, tools_call = response
                    if "content" in response:
                        content = response["content"]
                        tools_call = None
                    if content is not None and len(content) > 0:
                        content_arguments += content

                    if not tool_call_flag and content_arguments.startswith("<tool_call>"):
                        # print("content_arguments", content_arguments)
                        tool_call_flag = True

                    if tools_call is not None and len(tools_call) > 0:
                        tool_call_flag = True
                        self._merge_tool_calls(tool_calls_list, tools_call)
                else:
                    content = response

                # Get emotional expressions in LLM reply, only once at start of a dialogue
                if emotion_flag and content is not None and content.strip():
                    asyncio.run_coroutine_threadsafe(
                        textUtils.get_emotion(self, content),
                        self.loop,
                    )
                    emotion_flag = False

                if content is not None and len(content) > 0:
                    if not tool_call_flag:
                        response_message.append(content)
                        self.tts.tts_text_queue.put(
                            TTSMessageDTO(
                                sentence_id=current_sentence_id,
                                sentence_type=SentenceType.MIDDLE,
                                content_type=ContentType.TEXT,
                                content_detail=content,
                            )
                        )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"LLM stream processing error: {e}")
            self.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=current_sentence_id,
                    sentence_type=SentenceType.MIDDLE,
                    content_type=ContentType.TEXT,
                    content_detail=get_system_error_response(self.config),
                )
            )
            if depth == 0:
                self.tts.tts_text_queue.put(
                    TTSMessageDTO(
                        sentence_id=current_sentence_id,
                        sentence_type=SentenceType.LAST,
                        content_type=ContentType.ACTION,
                    )
                )
            return
        # Process function call
        if tool_call_flag:
            bHasError = False
            # Process text-based tool call format
            if len(tool_calls_list) == 0 and content_arguments:
                a = extract_json_from_string(content_arguments)
                if a is not None:
                    try:
                        content_arguments_json = json.loads(a)
                        tool_calls_list.append(
                            {
                                "id": str(uuid.uuid4().hex),
                                "name": content_arguments_json["name"],
                                "arguments": json.dumps(
                                    content_arguments_json["arguments"],
                                    ensure_ascii=False,
                                ),
                            }
                        )
                    except Exception as e:
                        bHasError = True
                        response_message.append(a)
                else:
                    bHasError = True
                    response_message.append(content_arguments)
                if bHasError:
                    self.logger.bind(tag=TAG).error(
                        f"function call error: {content_arguments}"
                    )

            if not bHasError and len(tool_calls_list) > 0:
                self.logger.bind(tag=TAG).debug(
                    f"Detected {len(tool_calls_list)} tool calls"
                )

                # Update tool call statistics
                if depth == 0:
                    current_turn = len(self.dialogue.dialogue) // 2
                    self.tool_call_stats['last_call_turn'] = current_turn
                    self.tool_call_stats['consecutive_no_call'] = 0
                    self.logger.bind(tag=TAG).debug(
                        f"Tool call statistics updated: current turn={current_turn}"
                    )

                # Text already broadcasted during LLM streaming phase
                streamed_text = ""
                if len(response_message) > 0:
                    streamed_text = "".join(response_message)
                    self.tts.store_tts_text(current_sentence_id, streamed_text)
                    self.dialogue.put(Message(role="assistant", content=streamed_text))
                response_message.clear()

                # Collect all tool call Futures
                futures_with_data = []
                for tool_call_data in tool_calls_list:
                    self.logger.bind(tag=TAG).debug(
                        f"function_name={tool_call_data['name']}, function_id={tool_call_data['id']}, function_arguments={tool_call_data['arguments']}"
                    )

                    # Report tool call using public method
                    tool_input = json.loads(tool_call_data.get("arguments") or "{}")
                    enqueue_tool_report(self, tool_call_data['name'], tool_input)

                    future = asyncio.run_coroutine_threadsafe(
                        self.func_handler.handle_llm_function_call(
                            self, tool_call_data
                        ),
                        self.loop,
                    )
                    futures_with_data.append((future, tool_call_data, tool_input))

                # Tool call timeout, configurable, default 30 seconds
                tool_call_timeout = int(self.config.get("tool_call_timeout", 30))
                # Wait for coroutine completion (actual wait duration is based on the slowest one)
                tool_results = []

                for future, tool_call_data, tool_input in futures_with_data:
                    try:
                        result = future.result(timeout=tool_call_timeout)
                        tool_results.append((result, tool_call_data))
                        # Report tool call results using public method
                        enqueue_tool_report(self, tool_call_data['name'], tool_input, str(result.result) if result.result else None, report_tool_call=False)

                    except Exception as e:
                        self.logger.bind(tag=TAG).error(
                            f"Tool call timeout or exception: {tool_call_data['name']}, error: {e}"
                        )
                        # Timeout when returning error response to avoid the entire process hanging
                        tool_results.append((
                            ActionResponse(action=Action.ERROR, result="Oops, encountered some network issues, please try again later!"),
                            tool_call_data
                        ))
                        # Report tool call error
                        enqueue_tool_report(self, tool_call_data['name'], tool_input, str(e), report_tool_call=False)

                # Unified processing of tool call results
                if tool_results:
                    self._handle_function_result(tool_results, depth=depth, streamed_text=streamed_text)

        # 存储对话内容
        if len(response_message) > 0:
            text_buff = "".join(response_message)
            self.tts.store_tts_text(current_sentence_id, text_buff)
            self.dialogue.put(Message(role="assistant", content=text_buff))

            # Update tool call statistics: increment count if no tool called
            if depth == 0 and not tool_call_flag:
                self.tool_call_stats['consecutive_no_call'] += 1

        if depth == 0:
            self.tts.tts_text_queue.put(
                TTSMessageDTO(
                    sentence_id=current_sentence_id,
                    sentence_type=SentenceType.LAST,
                    content_type=ContentType.ACTION,
                )
            )
            # 使用lambda延迟计算，只有在DEBUG级别时才执行get_llm_dialogue()
            self.logger.bind(tag=TAG).debug(
                lambda: json.dumps(
                    self.dialogue.get_llm_dialogue(), indent=4, ensure_ascii=False
                )
            )

            # 清理临时插入的工具调用提醒消息（使用标记清理）
            if tool_call_reminder and len(self.dialogue.dialogue) > 0:
                original_length = len(self.dialogue.dialogue)
                self.dialogue.dialogue = [
                    msg for msg in self.dialogue.dialogue
                    if not getattr(msg, 'is_temporary', False)
                ]
                if len(self.dialogue.dialogue) < original_length:
                    self.logger.bind(tag=TAG).debug("Cleared temporary tool call reminder messages")

        return True

    def _get_tool_summary(self, functions: list) -> str:
        """
        Extract a digest from the tool definition for rule reinforcement injection.
        Args:
            functions: List of tools
        Returns:
            str: Tool name string
        """
        if not functions:
            return ""

        datas = []
        for func in functions:
            func_info = func.get("function", {})
            name = func_info.get("name", "")
            datas.append(name)
        result = "、".join(datas)
        return result

    def _handle_function_result(self, tool_results, depth, streamed_text=""):
        need_llm_tools = []
        self.logger.bind(tag=TAG).info(f"[handle_function_result] {tool_results}")
        for result, tool_call_data in tool_results:
            if result.action in [
                Action.RESPONSE,
                Action.NOTFOUND,
                Action.ERROR,
            ]:
                text = result.response if result.response else result.result
                if streamed_text and text in streamed_text:
                    self.logger.bind(tag=TAG).debug(
                        f"Skipping duplicate TTS for tool {tool_call_data['name']}, already streamed"
                    )
                else:
                    self.tts.tts_one_sentence(self, ContentType.TEXT, content_detail=text)
                    self.tts.store_tts_text(self.sentence_id, text)
                self.dialogue.put(Message(role="assistant", content=text))
            elif result.action == Action.REQLLM:
                # Collect the tools that require LLM processing
                need_llm_tools.append((result, tool_call_data))
            else:
                pass

        if need_llm_tools:
            all_tool_calls = [
                {
                    "id": tool_call_data["id"],
                    "function": {
                        "arguments": (
                            "{}"
                            if tool_call_data["arguments"] == ""
                            else tool_call_data["arguments"]
                        ),
                        "name": tool_call_data["name"],
                    },
                    "type": "function",
                    "index": idx,
                }
                for idx, (_, tool_call_data) in enumerate(need_llm_tools)
            ]
            self.dialogue.put(Message(role="assistant", tool_calls=all_tool_calls))

            for result, tool_call_data in need_llm_tools:
                text = result.result
                if text is not None and len(text) > 0:
                    self.dialogue.put(
                        Message(
                            role="tool",
                            tool_call_id=(
                                str(uuid.uuid4())
                                if tool_call_data["id"] is None
                                else tool_call_data["id"]
                            ),
                            content=text,
                        )
                    )

            self.chat(None, depth=depth + 1)

    def _report_worker(self):
        """Chat Log Reporting Worker Thread"""
        while not self.stop_event.is_set():
            try:
                # Get data from the queue and set a timeout to check the stop event periodically
                item = self.report_queue.get(timeout=1)
                if item is None:  # Detects the poison pill object
                    break
                try:
                    # 检查线程池状态
                    if self.executor is None:
                        continue
                    # 提交任务到线程池
                    self.executor.submit(self._process_report, *item)
                except Exception as e:
                    self.logger.bind(tag=TAG).error(f"Chat record reporting thread exception: {e}")
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.bind(tag=TAG).error(f"Chat record reporting worker thread exception: {e}")

        self.logger.bind(tag=TAG).info("Chat record reporting thread exited")

    def _process_report(self, type, text, audio_data, report_time):
        """Processing reported tasks"""
        try:
            # Execute asynchronous reporting (run in the event loop)
            asyncio.run(report(self, type, text, audio_data, report_time))
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Reporting processing exception: {e}")
        finally:
            # Mark the task as done
            self.report_queue.task_done()

    def clearSpeakStatus(self):
        self.client_is_speaking = False
        self.logger.bind(tag=TAG).debug(f"Clear server-side speaking status")

    async def close(self, ws=None):
        """Resource cleanup method"""
        try:
            # Clean up VAD connection resources
            if (
                    hasattr(self, "vad")
                    and self.vad
                    and hasattr(self.vad, "release_conn_resources")
            ):
                self.vad.release_conn_resources(self)

            # Clean up audio buffer
            if hasattr(self, "audio_buffer"):
                self.audio_buffer.clear()

            # Cancel timeout task
            if self.timeout_task and not self.timeout_task.done():
                self.timeout_task.cancel()
                try:
                    await self.timeout_task
                except asyncio.CancelledError:
                    pass
                self.timeout_task = None

            # Clean up tool handler resources
            if hasattr(self, "func_handler") and self.func_handler:
                try:
                    await self.func_handler.cleanup()
                except Exception as cleanup_error:
                    self.logger.bind(tag=TAG).error(
                        f"Error cleaning up tool handler: {cleanup_error}"
                    )

            # Trigger stop event
            if self.stop_event:
                self.stop_event.set()

            # Clear all task queues
            self.clear_queues()

            # Close WebSocket connection
            try:
                if ws:
                    # Safely check WebSocket status and close
                    try:
                        if hasattr(ws, "closed") and not ws.closed:
                            await ws.close()
                        elif hasattr(ws, "state") and ws.state.name != "CLOSED":
                            await ws.close()
                        else:
                            # If there is no closed attribute, try to close directly
                            await ws.close()
                    except Exception:
                        # If closing fails, ignore errors
                        pass
                elif self.websocket:
                    try:
                        if (
                                hasattr(self.websocket, "closed")
                                and not self.websocket.closed
                        ):
                            await self.websocket.close()
                        elif (
                                hasattr(self.websocket, "state")
                                and self.websocket.state.name != "CLOSED"
                        ):
                            await self.websocket.close()
                        else:
                            # If there is no closed attribute, try to close directly
                            await self.websocket.close()
                    except Exception:
                        # If closing fails, ignore errors
                        pass
            except Exception as ws_error:
                self.logger.bind(tag=TAG).error(f"Error closing WebSocket connection: {ws_error}")

            if self.tts:
                await self.tts.close()
            if self.asr:
                await self.asr.close()

            # Finally close thread pool (to avoid blocking)
            if self.executor:
                try:
                    self.executor.shutdown(wait=False)
                except Exception as executor_error:
                    self.logger.bind(tag=TAG).error(
                        f"Error closing thread pool: {executor_error}"
                    )
                self.executor = None
            self.logger.bind(tag=TAG).info("Connection resources released")
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Error closing connection: {e}")
        finally:
            # 确保停止事件被设置
            if self.stop_event:
                self.stop_event.set()

    def clear_queues(self):
        """Clear all task queues"""
        if self.tts:
            self.logger.bind(tag=TAG).debug(
                f"Start cleaning: TTS queue size={self.tts.tts_text_queue.qsize()}, audio queue size={self.tts.tts_audio_queue.qsize()}"
            )

            # Clear queues using non-blocking method
            for q in [
                self.tts.tts_text_queue,
                self.tts.tts_audio_queue,
                self.report_queue,
            ]:
                if not q:
                    continue
                while True:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break

            # Reset audio rate controller (cancel background tasks and clear queues)
            if hasattr(self, "audio_rate_controller") and self.audio_rate_controller:
                self.audio_rate_controller.reset()
                self.logger.bind(tag=TAG).debug("Audio rate controller reset")

            self.logger.bind(tag=TAG).debug(
                f"Cleanup finished: TTS queue size={self.tts.tts_text_queue.qsize()}, audio queue size={self.tts.tts_audio_queue.qsize()}"
            )

    def reset_audio_states(self):
        """
        Reset all audio-related states (VAD + ASR)
        """
        # Reset VAD states
        self.client_audio_buffer.clear()
        self.client_have_voice = False
        self.client_voice_stop = False
        self.client_voice_window.clear()
        self.last_is_voice = False
        self.vad_last_voice_time = 0.0

        # Clear ASR buffers
        self.asr_audio.clear()

        self.logger.bind(tag=TAG).debug("All audio states reset.")

    def chat_and_close(self, text):
        """Chat with the user and then close the connection"""
        try:
            # Use the existing chat method
            self.chat(text)

            # After chat is complete, close the connection
            self.close_after_chat = True
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Chat and close error: {str(e)}")

    async def _check_timeout(self):
        """Check connection timeout"""
        try:
            while not self.stop_event.is_set():
                last_activity_time = self.last_activity_time
                if self.need_bind:
                    last_activity_time = self.first_activity_time

                # Check for timeout (only if timestamp is initialized)
                if last_activity_time > 0.0:
                    current_time = time.time() * 1000
                    if current_time - last_activity_time > self.timeout_seconds * 1000:
                        if not self.stop_event.is_set():
                            self.logger.bind(tag=TAG).info("Connection timed out, preparing to close")
                            # Set stop event to prevent repeated processing
                            self.stop_event.set()
                            # Wrap close operation in try-except to ensure no blocking due to exceptions
                            try:
                                await self.close(self.websocket)
                            except Exception as close_error:
                                self.logger.bind(tag=TAG).error(
                                    f"Error closing connection on timeout: {close_error}"
                                )
                        break
                # Check every 10 seconds to avoid excessive frequency
                await asyncio.sleep(10)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Error in timeout check task: {e}")
        finally:
            self.logger.bind(tag=TAG).info("Timeout check task exited")

    def _merge_tool_calls(self, tool_calls_list, tools_call):
        """Merge tool call list

        Args:
            tool_calls_list: Collected tool call list
            tools_call: New tool call
        """
        for tool_call in tools_call:
            tool_index = getattr(tool_call, "index", None)
            if tool_index is None:
                if tool_call.function.name:
                    # function_name present, indicates a new tool call
                    tool_index = len(tool_calls_list)
                else:
                    tool_index = len(tool_calls_list) - 1 if tool_calls_list else 0

            # Ensure list has enough space
            if tool_index >= len(tool_calls_list):
                tool_calls_list.append({"id": "", "name": "", "arguments": ""})

            # Update tool call information
            if tool_call.id:
                tool_calls_list[tool_index]["id"] = tool_call.id
            if tool_call.function.name:
                tool_calls_list[tool_index]["name"] = tool_call.function.name
            if tool_call.function.arguments:
                tool_calls_list[tool_index]["arguments"] += tool_call.function.arguments
