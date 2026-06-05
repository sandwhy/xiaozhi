// WebSocket Message Processing Module
import { getConfig, saveConnectionUrls } from '../../config/manager.js?v=0205';
import { uiController } from '../../ui/controller.js?v=0205';
import { log } from '../../utils/logger.js?v=0205';
import { getAudioPlayer } from '../audio/player.js?v=0205';
import { getAudioRecorder } from '../audio/recorder.js?v=0205';
import { executeMcpTool, getMcpTools, setWebSocket as setMcpWebSocket } from '../mcp/tools.js?v=0205';
import { webSocketConnect } from './ota-connector.js?v=0205';

// WebSocket Handler Class
export class WebSocketHandler {
    constructor() {
        this.websocket = null;
        this.onConnectionStateChange = null;
        this.onRecordButtonStateChange = null;
        this.onSessionStateChange = null;
        this.onSessionEmotionChange = null;
        this.onChatMessage = null;
        this.currentSessionId = null;
        this.isRemoteSpeaking = false;
    }

    // Send hello handshake message
    async sendHelloMessage() {
        if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) return false;

        try {
            const config = getConfig();

            const helloMessage = {
                type: 'hello',
                device_id: config.deviceId,
                device_name: config.deviceName,
                device_mac: config.deviceMac,
                token: config.token,
                features: {
                    mcp: true,
                    emoji: config.emojiEnabled
                }
            };

            log('Sending hello handshake message', 'info');
            this.websocket.send(JSON.stringify(helloMessage));

            return new Promise(resolve => {
                const timeout = setTimeout(() => {
                    log('Timed out waiting for hello response', 'error');
                    log('Tip: Please try clicking the "Test Authentication" button to troubleshoot the connection', 'info');
                    resolve(false);
                }, 5000);

                const onMessageHandler = (event) => {
                    try {
                        const response = JSON.parse(event.data);
                        if (response.type === 'hello' && response.session_id) {
                            log(`Server handshake successful, Session ID: ${response.session_id}`, 'success');
                            clearTimeout(timeout);
                            this.websocket.removeEventListener('message', onMessageHandler);
                            resolve(true);
                        }
                    } catch (e) {
                        // Ignore non-JSON messages
                    }
                };

                this.websocket.addEventListener('message', onMessageHandler);
            });
        } catch (error) {
            log(`Error sending hello message: ${error.message}`, 'error');
            return false;
        }
    }

    _sendWakeupMessages(sessionId) {
        if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) return;

        // listen detect
        this.websocket.send(JSON.stringify({
            session_id: sessionId,
            type: 'listen',
            state: 'detect',
            text: 'Hey, hello there'
        }));
        log('Sent listen detect message, wake word: Hey, hello there', 'info');

        // listen start: Start monitoring
        this.websocket.send(JSON.stringify({
            session_id: sessionId,
            type: 'listen',
            state: 'start',
            mode: 'auto'
        }));
        log('Sent listen start message', 'info');
    }

    // Handle text messages
    handleTextMessage(message) {
        if (message.type === 'hello') {
            log(`Server response: ${JSON.stringify(message, null, 2)}`, 'success');
            window.cameraAvailable = true;
            log('Connection successful, camera is now available', 'success');
            uiController.updateDialButton(true);

            this._sendWakeupMessages(message.session_id);

            uiController.startAIChatSession();
        } else if (message.type === 'tts') {
            this.handleTTSMessage(message);
        } else if (message.type === 'audio') {
            log(`Received audio control message: ${JSON.stringify(message)}`, 'info');
        } else if (message.type === 'stt') {
            log(`Recognition result: ${message.text}`, 'info');
            // Check if device binding is required
            if (message.text && (message.text.includes('bind') || message.text.includes('绑定'))) {
                log('Received device binding notification, updating camera status', 'warning');
                window.cameraAvailable = false;
                // Turn off the camera
                if (typeof window.stopCamera === 'function') {
                    window.stopCamera();
                }
                // Update camera button state
                const cameraBtn = document.getElementById('cameraBtn');
                if (cameraBtn) {
                    cameraBtn.classList.remove('camera-active');
                    cameraBtn.querySelector('.btn-text').textContent = 'Camera';
                    cameraBtn.disabled = true;
                    cameraBtn.title = 'Please bind the verification code first';
                }
            }
            // Display STT message using the new chat message callback
            if (this.onChatMessage && message.text) {
                this.onChatMessage(message.text, true);
            }
        } else if (message.type === 'llm') {
            log(`LLM response: ${message.text}`, 'info');
            // Display LLM reply using the new chat message callback
            if (this.onChatMessage && message.text) {
                this.onChatMessage(message.text, false);
            }

            // If it contains an emoji, update sessionStatus emotion and trigger Live2D action
            if (message.text && /[\u{1F300}-\u{1F9FF}]|[\u{2600}-\u{26FF}]|[\u{2700}-\u{27BF}]/u.test(message.text)) {
                // Extract emoji symbols
                const emojiMatch = message.text.match(/[\u{1F300}-\u{1F9FF}]|[\u{2600}-\u{26FF}]|[\u{2700}-\u{27BF}]/u);
                if (emojiMatch && this.onSessionEmotionChange) {
                    this.onSessionEmotionChange(emojiMatch[0]);
                }

                // Trigger Live2D emotional action
                if (message.emotion) {
                    console.log(`Received emotion message: emotion=${message.emotion}, text=${message.text}`);
                    this.triggerLive2DEmotionAction(message.emotion);
                }
            }

            // Only add to dialogue if text is not just an emoji
            // Remove emojis from text then check if there is content left
            const textWithoutEmoji = message.text ? message.text.replace(/[\u{1F300}-\u{1F9FF}]|[\u{2600}-\u{26FF}]|[\u{2700}-\u{27BF}]/gu, '').trim() : '';
            if (textWithoutEmoji && this.onChatMessage) {
                this.onChatMessage(message.text, false);
            }
        } else if (message.type === 'mcp') {
            this.handleMCPMessage(message);
        } else {
            log(`Unknown message type: ${message.type}`, 'info');
            if (this.onChatMessage) {
                this.onChatMessage(`Unknown message type: ${message.type}\n${JSON.stringify(message, null, 2)}`, false);
            }
        }
    }

    // Handle TTS messages
    handleTTSMessage(message) {
        if (message.state === 'start') {
            log('Server started streaming audio', 'info');
            this.currentSessionId = message.session_id;
            this.isRemoteSpeaking = true;
            if (this.onSessionStateChange) {
                this.onSessionStateChange(true);
            }

            // Start Live2D talking animation
            this.startLive2DTalking();
        } else if (message.state === 'sentence_start') {
            log(`Server sent audio segment: ${message.text}`, 'info');
            this.ttsSentenceCount = (this.ttsSentenceCount || 0) + 1;

            if (message.text && this.onChatMessage) {
                this.onChatMessage(message.text, false);
            }

            // Ensure animation is running when the sentence starts
            const live2dManager = window.chatApp?.live2dManager;
            if (live2dManager && !live2dManager.isTalking) {
                this.startLive2DTalking();
            }
        } else if (message.state === 'sentence_end') {
            log(`Audio segment finished: ${message.text}`, 'info');

            // Do not clear animation on sentence end, wait for the next sentence or final stop
        } else if (message.state === 'stop') {
            log('Server audio streaming finished, flushing all audio buffers', 'info');

            // Clear all audio buffers and stop playback
            const audioPlayer = getAudioPlayer();
            audioPlayer.clearAllAudio();

            this.isRemoteSpeaking = false;
            if (this.onRecordButtonStateChange) {
                this.onRecordButtonStateChange(false);
            }
            if (this.onSessionStateChange) {
                this.onSessionStateChange(false);
            }

            // Delay stopping Live2D talking animation to ensure all sentences have finished playing
            setTimeout(() => {
                this.stopLive2DTalking();
                this.ttsSentenceCount = 0; // Reset counter
            }, 1000); // 1-second delay to guarantee completeness across all sentences
        }
    }

    // Start Live2D talking animation
    startLive2DTalking() {
        try {
            // Get Live2D manager instance
            const live2dManager = window.chatApp?.live2dManager;
            if (live2dManager && live2dManager.live2dModel) {
                // Use the audio player's analyzer node
                live2dManager.startTalking();
                log('Live2D talking animation started', 'info');
            }
        } catch (error) {
            log(`Failed to start Live2D talking animation: ${error.message}`, 'error');
        }
    }

    // Stop Live2D talking animation
    stopLive2DTalking() {
        try {
            const live2dManager = window.chatApp?.live2dManager;
            if (live2dManager) {
                live2dManager.stopTalking();
                log('Live2D talking animation stopped', 'info');
            }
        } catch (error) {
            log(`Failed to stop Live2D talking animation: ${error.message}`, 'error');
        }
    }

    // Initialize Live2D audio analyzer
    initializeLive2DAudioAnalyzer() {
        try {
            const live2dManager = window.chatApp?.live2dManager;
            if (live2dManager) {
                // Initialize audio analyzer (using the audio player's context)
                if (live2dManager.initializeAudioAnalyzer()) {
                    log('Live2D audio analyzer initialization complete, connected to audio player', 'success');
                } else {
                    log('Live2D audio analyzer initialization failed, falling back to simulated animation', 'warning');
                }
            }
        } catch (error) {
            log(`Failed to initialize Live2D audio analyzer: ${error.message}`, 'error');
        }
    }

    // Handle MCP messages
    handleMCPMessage(message) {
        const payload = message.payload || {};
        log(`Server distributed: ${JSON.stringify(message)}`, 'info');

        if (payload.method === 'tools/list') {
            const tools = getMcpTools();

            const replyMessage = JSON.stringify({
                "session_id": message.session_id || "",
                "type": "mcp",
                "payload": {
                    "jsonrpc": "2.0",
                    "id": payload.id,
                    "result": {
                        "tools": tools
                    }
                }
            });
            log(`Client reported: ${replyMessage}`, 'info');
            this.websocket.send(replyMessage);
            log(`Replied with MCP tool list: ${tools.length} tools`, 'info');

        } else if (payload.method === 'tools/call') {
            const toolName = payload.params?.name;
            const toolArgs = payload.params?.arguments;

            log(`Invoking tool: ${toolName} Parameters: ${JSON.stringify(toolArgs)}`, 'info');

            executeMcpTool(toolName, toolArgs).then(result => {
                const replyMessage = JSON.stringify({
                    "session_id": message.session_id || "",
                    "type": "mcp",
                    "payload": {
                        "jsonrpc": "2.0",
                        "id": payload.id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": JSON.stringify(result)
                                }
                            ],
                            "isError": false
                        }
                    }
                });

                log(`Client reported: ${replyMessage}`, 'info');
                this.websocket.send(replyMessage);
            }).catch(error => {
                log(`Tool execution failed: ${error.message}`, 'error');
                const errorReply = JSON.stringify({
                    "session_id": message.session_id || "",
                    "type": "mcp",
                    "payload": {
                        "jsonrpc": "2.0",
                        "id": payload.id,
                        "error": {
                            "code": -32603,
                            "message": error.message
                        }
                    }
                });
                this.websocket.send(errorReply);
            });
        } else if (payload.method === 'initialize') {
            log(`Received tool initialization request: ${JSON.stringify(payload.params)}`, 'info');
            // Save vision analysis endpoint address
            const visionUrl = document.getElementById('visionUrl');
            const visionConfig = payload?.params?.capabilities?.vision;
            if (visionConfig && typeof visionConfig === 'object' && visionConfig.url && visionConfig.token) {
                const visionConfigStr = JSON.stringify(visionConfig);
                localStorage.setItem('xz_tester_vision', visionConfigStr);
                if (visionUrl) visionUrl.value = visionConfig.url;
            } else {
                localStorage.removeItem('xz_tester_vision');
                if (visionUrl) visionUrl.value = '';
            }

            const replyMessage = JSON.stringify({
                "session_id": message.session_id || "",
                "type": "mcp",
                "payload": {
                    "jsonrpc": "2.0",
                    "id": payload.id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "xiaozhi-web-test",
                            "version": "2.1.0"
                        }
                    }
                }
            });
            log(`Replying to initialization request`, 'info');
            this.websocket.send(replyMessage);
        } else {
            log(`Unknown MCP method: ${payload.method}`, 'warning');
        }
    }

    // Handle binary messages
    async handleBinaryMessage(data) {
        try {
            let arrayBuffer;
            if (data instanceof ArrayBuffer) {
                arrayBuffer = data;
            } else if (data instanceof Blob) {
                arrayBuffer = await data.arrayBuffer();
                log(`Received Blob audio data, Size: ${arrayBuffer.byteLength} bytes`, 'debug');
            } else {
                log(`Received binary data of unknown type: ${typeof data}`, 'warning');
                return;
            }

            const opusData = new Uint8Array(arrayBuffer);
            const audioPlayer = getAudioPlayer();
            audioPlayer.enqueueAudioData(opusData);
        } catch (error) {
            log(`Error processing binary message: ${error.message}`, 'error');
        }
    }

    // Connect to WebSocket server
    async connect() {
        const config = getConfig();
        log('Checking OTA status...', 'info');
        saveConnectionUrls();

        try {
            const otaUrl = document.getElementById('otaUrl').value.trim();
            const ws = await webSocketConnect(otaUrl, config);
            if (ws === undefined) {
                return false;
            }
            this.websocket = ws;

            // Set incoming binary message structure type to ArrayBuffer
            this.websocket.binaryType = 'arraybuffer';

            // Assign the active WebSocket instance to the MCP module
            setMcpWebSocket(this.websocket);

            // Assign the target WebSocket to the Audio Recorder
            const audioRecorder = getAudioRecorder();
            audioRecorder.setWebSocket(this.websocket);

            this.setupEventHandlers();

            return true;
        } catch (error) {
            log(`Connection error: ${error.message}`, 'error');
            if (this.onConnectionStateChange) {
                this.onConnectionStateChange(false);
            }
            return false;
        }
    }

    // Setup event handlers
    setupEventHandlers() {
        this.websocket.onopen = async () => {
            const url = document.getElementById('serverUrl').value;
            log(`Connected to server: ${url}`, 'success');

            if (this.onConnectionStateChange) {
                this.onConnectionStateChange(true);
            }

            // Default connection state starts as listening
            this.isRemoteSpeaking = false;
            if (this.onSessionStateChange) {
                this.onSessionStateChange(false);
            }

            // Initialize Live2D audio analyzer upon successful WebSocket connection
            this.initializeLive2DAudioAnalyzer();

            await this.sendHelloMessage();
        };

        this.websocket.onclose = () => {
            log('Disconnected from server', 'info');

            if (this.onConnectionStateChange) {
                this.onConnectionStateChange(false);
            }

            const audioRecorder = getAudioRecorder();
            audioRecorder.stop();

            // Shut down the camera stream
            if (typeof window.stopCamera === 'function') {
                window.stopCamera();
            }

            // Hide camera viewpoint container block
            const cameraContainer = document.getElementById('cameraContainer');
            if (cameraContainer) {
                cameraContainer.classList.remove('active');
            }
        };

        this.websocket.onerror = (error) => {
            log(`WebSocket error: ${error.message || 'Unknown error'}`, 'error');
            uiController.addChatMessage(`⚠️ WebSocket error: ${error.message || 'Unknown error'}`, false);
            if (this.onConnectionStateChange) {
                this.onConnectionStateChange(false);
            }
        };

        this.websocket.onmessage = (event) => {
            try {
                if (typeof event.data === 'string') {
                    const message = JSON.parse(event.data);
                    this.handleTextMessage(message);
                } else {
                    this.handleBinaryMessage(event.data);
                }
            } catch (error) {
                log(`WebSocket message sorting error: ${error.message}`, 'error');
                // Legacy addMessage function has been deprecated as conversationDiv does not exist
                // Errors are routed upstream to diagnostic tracking instead
            }
        };
    }

    // Terminate connection
    disconnect() {
        if (!this.websocket) return;

        this.websocket.close();
        const audioRecorder = getAudioRecorder();
        audioRecorder.stop();

        // Shut down camera capture stream
        if (typeof window.stopCamera === 'function') {
            window.stopCamera();
        }

        // Collapse camera view interface component
        const cameraContainer = document.getElementById('cameraContainer');
        if (cameraContainer) {
            cameraContainer.classList.remove('active');
        }
    }

    // Outbound text messaging handler
    sendTextMessage(text) {
        if (text === '' || !this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
            return false;
        }

        try {
            // If the digital human is actively speaking, push an interruption payload first
            if (this.isRemoteSpeaking && this.currentSessionId) {
                const abortMessage = {
                    session_id: this.currentSessionId,
                    type: 'abort',
                    reason: 'wake_word_detected'
                };
                this.websocket.send(JSON.stringify(abortMessage));
                log('Sent interruption signal (abort)', 'info');
            }

            const listenMessage = {
                type: 'listen',
                state: 'detect',
                text: text
            };

            this.websocket.send(JSON.stringify(listenMessage));
            log(`Sent text message content: ${text}`, 'info');

            return true;
        } catch (error) {
            log(`Error dispatching text message packet: ${error.message}`, 'error');
            return false;
        }
    }

    /**
     * Trigger Live2D Emotional Action Animation Sequence
     * @param {string} emotion - Emotion classification tag string
     */
    triggerLive2DEmotionAction(emotion) {
        try {
            const live2dManager = window.chatApp?.live2dManager;
            if (live2dManager && typeof live2dManager.triggerEmotionAction === 'function') {
                live2dManager.triggerEmotionAction(emotion);
                log(`Triggered Live2D emotional animation macro: ${emotion}`, 'info');
            } else {
                log(`Unable to fire Live2D track sequence: Manager instance missing or reference unbound`, 'warning');
            }
        } catch (error) {
            log(`Failed running target Live2D structural mutation: ${error.message}`, 'error');
        }
    }

    // Fetch active wrapper object
    getWebSocket() {
        return this.websocket;
    }

    // Evaluation flag check
    isConnected() {
        return this.websocket && this.websocket.readyState === WebSocket.OPEN;
    }
}

// Generate single instance handle allocation
let wsHandlerInstance = null;

export function getWebSocketHandler() {
    if (!wsHandlerInstance) {
        wsHandlerInstance = new WebSocketHandler();
    }
    return wsHandlerInstance;
}