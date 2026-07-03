Core components 
form providers, 

- asr
- intent
- llm
- memory
- tools
- tts
- vad
- vllm

Features to work out one by one / one at a time:
- asr
    fix the recognition
- memory
    apply memory
- prompt
    find out more about the propmt
- intent
    how to work out intent
- tools / mcp
    how to get that working.


Connenction.py
886 - 896, 

### AI Function calling / tools
how to get ai to use functions we created ourselves. 
ex: weather api function
prompt goes to ai,
ai thinks: ok i should see if i have a tool to check the weather
finds weather api function
executes weather api function
get result from weather api
passes result to ai
ai gives final answer to user

...
Initialisation: 
- function list is given to the llm
LLm receives prompt, looks into function list, decide to call function -> 
LLM checks with the function schema, decide the params for the function -> 
Call the function and get the result -> 
Pass the result to the LLM -> 
LLM generate the final response

Function list / schema is the same

The functions list is created automatically by loadplugins.py
# so the functions has a shape:
- sending tool list to the llm:
try:
    response = client.responses.create(
        model="gpt-4o",
        instructions="You are a helpful assistant with access to weather, todo, and traffic tools.",
        previousNormally I can help with things like this, but I don't seem to have access to that content. You can try again or ask me for something else.
        
- functionDescription:
get_lunar_function_desc = {
    "type": "function",
    "function": {
        "name": "get_lunar",
        "description": (
            "用于具体日期的阴历/农历和黄历信息。"
            "用户可以指定查询内容，如：阴历日期、天干地支、节气、生肖、星座、八字、宜忌等。"
            "如果没有指定查询内容，则默认查询干支年和农历日期。"
            "对于'今天农历是多少'、'今天农历日期'这样的基本查询，请直接使用context中的信息，不要调用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "要查询的日期，格式为YYYY-MM-DD，例如2024-01-01。如果不提供，则使用当前日期",
                },
                "query": {
                    "type": "string",
                    "description": "要查询的内容，例如阴历日期、天干地支、节日、节气、生肖、星座、八字、宜忌等",
                },
            },
            "required": [],
        },
    },
}
- execution

## End of Tools

## Prompting
- base prompt comes form .config.yaml
- prompt_manager.py can add context information into the base prompt
- agennt-basep-prompt.txt is the base prompt template

<do figgure out later> when the server prompts the llm model, it sends out instructions and prompts. takes the response and filters it, then uses that. but it could also force the ai to ommit things while thinking and such..

runnning deepseek-r1:1.5b caused issuse where the ai rambles on and on, long, kind of incoherent responses
possible reasons for this being the model is a thinking model, which our server strips, and its a small model being injected a large prompt file 'agennt-base-prompt.txt'

what actually happened today?
found out that main loop processes occurs at conenction.py, chat function
this loop processes the messages from the esp32
and generates the responses, using the cores

tested the llm performance in local test server, found issues, prolly because its a thinking type and small. 

llm.py calls up ollama.py, within ollama.py we are prompting the ai, then modifying it directly to be used in tts (standard procedures for tts apparently)

changed to a non thinking model, works quite well

<for expansion> modify the prompt to suite the orignial vision. change the tts sounds.

## End of Prompting

## Memory 

![alt text](image.png)