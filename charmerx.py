"""
CharmerX demo (2026 rebuild)

Upload a dating app screenshot (a profile or a chat) and get:
  - what kind of screenshot it is
  - which conversation phase you are in
  - a read on the situation and your next move
  - 3 reply options: Charming, Sweet, Nice

The 2025 production version ran ~5 model calls per message (parser, router,
phase classifier, persona classifier, reply generator). The post-mortem's
biggest cost fix was to merge them into one call. This demo does exactly that:
one vision call, one structured JSON answer.

Runs on Google Colab or locally. Needs a free Gemini API key from
https://aistudio.google.com/apikey (no card needed).

Local run:
    pip install google-genai gradio pillow
    export GEMINI_API_KEY=your_key      # or you will be prompted
    python charmerx.py
"""

import io
import json
import os
from getpass import getpass

import gradio as gr
from google import genai
from google.genai import types
from PIL import Image


# ---------------------------------------------------------------------------
# 1. The prompt. This is where the product logic lives.
# ---------------------------------------------------------------------------

PROMPT = """
You are CharmerX, a dating texting coach for young Indian professionals.
The user has uploaded a screenshot from a dating app (Hinge, Bumble, Tinder)
or from WhatsApp.

STEP 1. Decide the screenshot type:
  - "profile": someone's dating profile (photos, bio, prompts). No chat yet.
  - "chat": a conversation. In chat screenshots, messages on the RIGHT are
    from the user, messages on the LEFT are from the match. Read them in order.

STEP 2. If it is a chat, pick the conversation phase:
  - "opener": no messages yet, or only the user's first message
  - "general": the conversation is flowing, getting to know each other
  - "reignition": the chat has gone cold or the match has stopped replying
  - "ask_out": there is enough rapport to suggest meeting in person
For a profile, the phase is "opener".

STEP 3. Write:
  - situation: 1 to 2 sentences on what is going on
  - your_move: 1 sentence on what the user should aim for next
  - 3 replies the user can send as-is:
      charming: playful, confident, light teasing
      sweet: warm and genuine
      nice: simple, safe, low-risk
    For a profile, each reply must reference something specific in it.
    Keep each reply short, like a real text (under 25 words).
    Hinglish is fine if the chat already uses it.

RULES:
  - Be respectful. No pickup-line cringe, no pressure, no manipulation.
  - If the match has clearly said no or shown disinterest, say so in
    "situation" and make the replies a graceful, friendly exit.
  - If the image is not a dating profile or chat, set screenshot_type to
    "unknown" and explain in "situation".

Return ONLY JSON in this exact shape:
{
  "screenshot_type": "profile" | "chat" | "unknown",
  "phase": "opener" | "general" | "reignition" | "ask_out",
  "situation": "...",
  "your_move": "...",
  "replies": {"charming": "...", "sweet": "...", "nice": "..."}
}
"""


# ---------------------------------------------------------------------------
# 2. Setup: API key and model choice
# ---------------------------------------------------------------------------

def get_api_key() -> str:
    """Colab secret first, then environment variable, then ask the user."""
    try:
        from google.colab import userdata  # only exists on Colab
        key = userdata.get("GEMINI_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY") or getpass("Paste your free Gemini API key: ")


def pick_model(client: genai.Client) -> str:
    """
    Google renames its free models often, so instead of hardcoding one,
    pick the best available text+vision model on this key.
    Flash-Lite first: it has the most generous free daily quota.
    """
    skip = ("tts", "live", "image", "embedding", "audio", "transcribe", "translate")
    names = []
    for m in client.models.list():
        name = m.name.replace("models/", "")
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" in actions and "gemini" in name and not any(s in name for s in skip):
            names.append(name)

    for preference in ("flash-lite", "flash"):
        stable = sorted([n for n in names if preference in n and "preview" not in n], reverse=True)
        if stable:
            return stable[0]
    if names:
        return sorted(names, reverse=True)[0]
    raise RuntimeError("No usable Gemini model found for this API key.")


# ---------------------------------------------------------------------------
# 3. The core: one call from screenshot to replies
# ---------------------------------------------------------------------------

def analyze(client: genai.Client, model: str, image: Image.Image) -> dict:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/png"),
            PROMPT,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.9,
        ),
    )
    return json.loads(response.text)


def to_markdown(result: dict) -> str:
    replies = result.get("replies", {})
    phase = result.get("phase", "").replace("_", " ").title()
    return f"""
**Screenshot:** {result.get("screenshot_type", "").title()} &nbsp;|&nbsp; **Phase:** {phase}

**The situation:** {result.get("situation", "")}

**Your move:** {result.get("your_move", "")}

---

**Charming:** {replies.get("charming", "")}

**Sweet:** {replies.get("sweet", "")}

**Nice:** {replies.get("nice", "")}
"""


# ---------------------------------------------------------------------------
# 4. The app: an upload box and a results panel
# ---------------------------------------------------------------------------

def build_app(client: genai.Client, model: str) -> gr.Interface:
    def run(image):
        if image is None:
            return "Upload a screenshot first."
        try:
            return to_markdown(analyze(client, model, image))
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                return "Free daily quota reached for this API key. Try again tomorrow or use another key."
            return f"Something went wrong: {e}"

    return gr.Interface(
        fn=run,
        inputs=gr.Image(type="pil", label="Dating profile or chat screenshot"),
        outputs=gr.Markdown(label="CharmerX"),
        title="CharmerX",
        description=f"Upload a screenshot, get 3 replies. Demo rebuild of a 2025 product. Model: {model}",
        flagging_mode="never",
    )


def main():
    client = genai.Client(api_key=get_api_key())
    model = pick_model(client)
    print(f"Using model: {model}")
    in_colab = "COLAB_RELEASE_TAG" in os.environ
    build_app(client, model).launch(share=in_colab)


if __name__ == "__main__":
    main()
