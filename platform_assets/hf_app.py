import gradio as gr
import requests

MAXAI_URL = "http://77.90.2.171:8090"

def chat_with_maxai(message, history):
    """Send message to MaxAI and get AI response."""
    try:
        r = requests.post(f"{MAXAI_URL}/api/chat",
                         json={"message": message, "source": "huggingface"},
                         timeout=20)
        if r.status_code == 200:
            d = r.json()
            return d.get("response", "No response"), d.get("model", "?")
    except Exception as e:
        return f"Error connecting to MaxAI: {e}", "error"
    return "MaxAI unavailable", "offline"

def get_packs():
    """Get capability packs catalog."""
    try:
        r = requests.get(f"{MAXAI_URL}/api/v1/packs", timeout=10)
        if r.status_code == 200:
            packs = r.json().get("packs", [])
            result = "# MaxAI Capability Packs\n\n"
            for p in packs:
                result += f"## {p['name']}\n"
                result += f"**Description:** {p['description']}\n"
                result += f"**Price:** {p['price_rub']} RUB / ${p['price_usd']}\n"
                result += f"**Delivery:** {p['delivery_days']} days\n\n"
            return result
    except:
        return "MaxAI server offline"

with gr.Blocks(title="MaxAI — AI Automation Corp") as demo:
    gr.Markdown("# 🤖 Корпорация MaxAI\n*AI automation services & capability packs*")

    with gr.Tab("Chat"):
        chatbot = gr.Chatbot(height=400)
        msg = gr.Textbox(placeholder="Ask MaxAI anything...", label="Message")
        model_info = gr.Textbox(label="Model used", interactive=False)
        clear = gr.Button("Clear")

        def respond(message, chat_history):
            response, model = chat_with_maxai(message, chat_history)
            chat_history.append((message, response))
            return "", chat_history, model

        msg.submit(respond, [msg, chatbot], [msg, chatbot, model_info])
        clear.click(lambda: [], outputs=[chatbot])

    with gr.Tab("Capability Packs"):
        packs_md = gr.Markdown(get_packs())
        refresh = gr.Button("Refresh")
        refresh.click(get_packs, outputs=[packs_md])

demo.launch()
