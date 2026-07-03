import asyncio
import json
import websockets
import sys

# Replace with your server's host and port
SERVER_URL = "ws://localhost:8000/xiaozhi/v1/"

async def receive_messages(websocket):
    """Listens continuously for audio frames, text tokens, or state signals from the server."""
    try:
        async for message in websocket:
            if isinstance(message, str):
                # Handle text frames (metadata, text streaming, or structural JSON logs)
                try:
                    data = json.loads(message)
                    print(f"\n[Server JSON]: {data}")
                except json.JSONDecodeError:
                    print(f"{message}", end="", flush=True)
            elif isinstance(message, bytes):
                # Handle incoming raw audio frames (PCM bytes from TTS)
                # In a minimal CLI, we just acknowledge receipt or count frames instead of blocking
                print(".", end="", flush=True)
    except websockets.exceptions.ConnectionClosed:
        print("\n[Disconnected] Server closed the connection.")

async def send_interactive_prompts(websocket):
    """Reads input from your terminal prompt and transmits it to the server."""
    print("\n=== Xiaozhi CLI Sandbox ===")
    print("Type your message and press Enter. Type 'exit' to quit.\n")
    
    # Optional: Send a boot/handshake configuration payload if your server requires it
    # hello_payload = {"type": "hello", "version": 3, "transport": "websocket"}
    # await websocket.send(json.dumps(hello_payload))

    while True:
        # Run input in a thread executor so it doesn't block the async event loop
        loop = asyncio.get_event_loop()
        user_input = await loop.run_in_executor(None, input, "You > ")
        
        if user_input.strip().lower() == "exit":
            print("Closing connection...")
            break
            
        if not user_input.strip():
            continue

        # Package text input as a structured text event or raw frame depending on your endpoint layout
        payload = {
            "type": "listen",
            "state": "text",
            "text": user_input
        }
        
        try:
            await websocket.send(json.dumps(payload))
        except websockets.exceptions.ConnectionClosed:
            print("[Error] Cannot send message. Connection closed.")
            break

async def main():
    try:
        async with websockets.connect(SERVER_URL) as websocket:
            print(f"[Connected] Successfully hooked into backend at {SERVER_URL}")
            
            # Run the sending loop and receiving loop concurrently
            await asyncio.gather(
                receive_messages(websocket),
                send_interactive_prompts(websocket)
            )
    except Exception as e:
        print(f"[Connection Failure] Could not connect to {SERVER_URL}: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting CLI Sandbox.")
        sys.exit(0)