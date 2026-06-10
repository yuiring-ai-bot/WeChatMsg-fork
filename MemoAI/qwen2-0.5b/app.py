import json
import os
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

import gradio as gr


LM_STUDIO_BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "local-model")
DEFAULT_SYSTEM = os.environ.get("LM_STUDIO_SYSTEM_PROMPT", "You are a helpful assistant.")
REQUEST_TIMEOUT = int(os.environ.get("LM_STUDIO_TIMEOUT", "120"))

History = List[Tuple[str, str]]
Messages = List[Dict[str, str]]


def clear_session() -> Tuple[str, History]:
    return "", []


def modify_system_session(system: Optional[str]) -> Tuple[str, str, History]:
    system = system or DEFAULT_SYSTEM
    return system, system, []


def history_to_messages(history: Optional[History], system: str, query: str) -> Messages:
    messages = [{"role": "system", "content": system or DEFAULT_SYSTEM}]
    for user_text, assistant_text in history or []:
        messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": assistant_text})
    messages.append({"role": "user", "content": query})
    return messages


def call_lm_studio(messages: Messages) -> str:
    payload = {
        "model": LM_STUDIO_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{LM_STUDIO_BASE_URL}/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Cannot reach LM Studio at {LM_STUDIO_BASE_URL}. "
            "Start the LM Studio local server and load a model first."
        ) from exc

    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError(f"LM Studio returned no choices: {result}")
    message = choices[0].get("message") or {}
    return message.get("content", "")


def model_chat(query: Optional[str], history: Optional[History], system: str):
    query = query or ""
    history = history or []
    if not query.strip():
        yield "", history, system or DEFAULT_SYSTEM
        return

    try:
        reply = call_lm_studio(history_to_messages(history, system or DEFAULT_SYSTEM, query))
    except Exception as exc:
        reply = f"LM Studio request failed: {exc}"

    yield "", history + [(query, reply)], system or DEFAULT_SYSTEM


with gr.Blocks() as demo:
    gr.Markdown("# LM Studio Chat")
    with gr.Row():
        with gr.Column(scale=3):
            system_input = gr.Textbox(value=DEFAULT_SYSTEM, lines=2, label="System")
        with gr.Column(scale=1):
            modify_system = gr.Button("Set system and clear")
        system_state = gr.Textbox(value=DEFAULT_SYSTEM, visible=False)
    chatbot = gr.Chatbot(label=f"LM Studio: {LM_STUDIO_MODEL}")
    textbox = gr.Textbox(lines=2, label="Input")

    with gr.Row():
        clear_history = gr.Button("Clear")
        submit = gr.Button("Send")

    submit.click(
        model_chat,
        inputs=[textbox, chatbot, system_state],
        outputs=[textbox, chatbot, system_input],
    )
    clear_history.click(fn=clear_session, inputs=[], outputs=[textbox, chatbot])
    modify_system.click(
        fn=modify_system_session,
        inputs=[system_input],
        outputs=[system_state, system_input, chatbot],
    )


if __name__ == "__main__":
    demo.queue(api_open=False).launch(
        height=800,
        share=False,
        server_name="127.0.0.1",
        server_port=int(os.environ.get("GRADIO_PORT", "7860")),
    )
