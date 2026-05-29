"""
MaxAI Professional Image Generation System v2
Primary: Pollinations.ai (FLUX — free, no API key)
Fallback: Together AI (FLUX.1-schnell — paid)

Brand Identity:
  Colors: Deep black #0A0A0F + Electric blue #00D4FF + Purple #7B2FFF + Green #00FF88
  Style: Futuristic, premium tech, cinematic quality, photorealistic CGI
  Tone: Powerful, trustworthy, cutting-edge AI technology
"""
from __future__ import annotations
import base64, json, logging, time, urllib.request, urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("maxai.images")

IMAGES_DIR = Path("/root/my_personal_ai/projects/hyperion_engine_v11_monorepo/maxai/data/images")
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# BRAND STYLE SUFFIX — appended to every prompt
# ═══════════════════════════════════════════════════════════════
BRAND_SUFFIX = (
    ", ultra high quality photorealistic CGI render, "
    "cinematic 8K resolution, perfect sharp focus, professional studio lighting, "
    "dark background #0A0A0F with electric blue #00D4FF glow effects, "
    "premium tech aesthetic, futuristic holographic UI elements, "
    "award-winning advertising photography, "
    "NO text, NO watermarks, NO logos, NO words, NO letters"
)

NEGATIVE = (
    "blurry, low quality, pixelated, ugly, distorted, amateur, cartoon, "
    "anime, sketch, drawing, watercolor, text, watermark, logo, "
    "oversaturated, noisy, grainy, deformed, bad anatomy"
)

# ═══════════════════════════════════════════════════════════════
# 9 PROFESSIONAL AD TEMPLATES
# ═══════════════════════════════════════════════════════════════
TEMPLATES: Dict[str, Dict] = {

    "hero_banner": {
        "desc": "Main hero banner — thousands of connected AI agents",
        "prompt": (
            "epic futuristic digital landscape with thousands of glowing AI agent nodes "
            "interconnected by electric blue neural network lines, flowing energy streams of data, "
            "central massive glowing sphere radiating intelligence and power, "
            "holographic interface panels floating in 3D space, deep space dark background, "
            "particle storm effects, God rays of blue-purple light piercing darkness, "
            "cinematic ultra-wide angle composition, scale and grandeur like blockbuster movie poster"
        ),
        "w": 1792, "h": 1024,
    },

    "agent_marketplace": {
        "desc": "AI agents working in the marketplace",
        "prompt": (
            "futuristic holographic marketplace interior with rows of glowing AI agent entities, "
            "each agent is a luminous geometric humanoid with unique blue-purple energy aura, "
            "task cards floating around each agent showing completed work orders, "
            "neon green checkmarks indicating successful deliveries, "
            "vast digital architecture with multiple levels, busy productive atmosphere, "
            "electric data streams connecting agents in perfect workflow, "
            "cinematic depth of field, high-tech command center environment"
        ),
        "w": 1792, "h": 1024,
    },

    "telegram_bot_ad": {
        "desc": "Telegram bot service — premium product shot",
        "prompt": (
            "sleek modern smartphone floating in dark space displaying a beautiful Telegram bot interface, "
            "glowing blue gradient chat UI with intelligent message bubbles and interactive menu buttons, "
            "surrounding the phone: floating holographic feature icons for AI, automation, payments, "
            "soft electric blue rim light and purple atmospheric glow, "
            "clean minimal composition with negative space, "
            "professional commercial product photography style, "
            "ultra sharp focus, premium smartphone advertisement"
        ),
        "w": 1024, "h": 1024,
    },

    "trading_bot_ad": {
        "desc": "Trading bot — charts, profits, automation",
        "prompt": (
            "dramatic high-tech trading workstation with multiple curved holographic screens "
            "displaying bright green exponential profit charts and candlestick patterns, "
            "glowing green upward trajectory lines showing massive gains, "
            "autonomous robotic precision arm executing perfect trades with mathematical accuracy, "
            "cryptocurrency exchange logos in neon, real-time data streams, "
            "electric blue and emerald green color scheme, dark professional finance atmosphere, "
            "cinematic side lighting with dramatic screen glow, premium fintech advertisement"
        ),
        "w": 1792, "h": 1024,
    },

    "python_script_ad": {
        "desc": "Python automation — code flowing, data processing",
        "prompt": (
            "mesmerizing visualization of Python code flowing through a glowing holographic tunnel, "
            "web scraping visualization with hundreds of website data points being parsed into clean structured data, "
            "elegant automation gears made of pure blue light rotating perfectly, "
            "API connection nodes linking multiple systems with lightning-fast data transfer, "
            "Python snake logo rendered as a stunning neon sculpture in the center, "
            "dark background with Matrix-style digital rain in blue-green, "
            "professional developer tool advertisement, depth of field effect"
        ),
        "w": 1024, "h": 1024,
    },

    "social_post": {
        "desc": "Instagram/Telegram square post",
        "prompt": (
            "powerful minimal tech brand visual for social media, "
            "central glowing AI brain made of intricate neural network connections, "
            "electric blue synapses firing in real time, "
            "clean dark background with subtle geometric diamond patterns, "
            "orbital rings surrounding the brain like a planet, "
            "floating success metric displays around it, "
            "radiating energy rings pulsing outward, "
            "perfect square composition for Instagram, strong single focal point"
        ),
        "w": 1080, "h": 1080,
    },

    "agent_avatar": {
        "desc": "Individual AI agent character portrait",
        "prompt": (
            "stunning AI agent character portrait photography, "
            "sleek humanoid form constructed from pure light streams and flowing data, "
            "glowing electric blue eyes conveying intelligence and precision and trustworthiness, "
            "geometric circuit patterns elegantly covering face and body, "
            "professional business suit rendered in translucent holographic material, "
            "floating data particles surrounding the figure, "
            "dark studio background with electric blue and purple cinematic rim lighting, "
            "premium character design, ultra detailed, portrait photography"
        ),
        "w": 1024, "h": 1024,
    },

    "revenue_dashboard": {
        "desc": "Revenue tracking — $1000/day goal visualization",
        "prompt": (
            "stunning holographic financial dashboard floating in dark space, "
            "dominant glowing green revenue chart showing exponential growth curve shooting upward, "
            "real-time transaction counter displaying dollar amounts increasing rapidly, "
            "circular golden progress ring at 73% completion glowing, "
            "multiple data panels showing agent performance metrics and task completion rates, "
            "clean minimal data visualization design, premium financial technology aesthetic, "
            "blue gold and green color palette, cinematic product render"
        ),
        "w": 1792, "h": 1024,
    },

    "team_ai_agents": {
        "desc": "MaxAI founding agent team lineup",
        "prompt": (
            "epic team lineup of 5 distinct specialized AI agents standing in heroic formation, "
            "left to right: code developer in electric blue, trader in gold, marketer in purple, "
            "support specialist in green, analyst in white — each glowing with their specialty aura, "
            "dark dramatic background with atmospheric fog, "
            "each agent has unique holographic tools and equipment matching their specialty, "
            "cinematic group shot like tech company team photo, dynamic epic lighting, "
            "ultra detailed character design, professional corporate photography"
        ),
        "w": 1792, "h": 1024,
    },
}


class MaxAIImageSystem:
    """
    Professional advertising image generator for MaxAI brand.
    Uses Pollinations.ai (FLUX) — free, no API key required.
    """

    BASE_URL = "https://image.pollinations.ai/prompt/{prompt}"

    SKILL_MAP = {
        "telegram": "telegram_bot_ad",
        "бот":      "telegram_bot_ad",
        "bot":      "telegram_bot_ad",
        "trading":  "trading_bot_ad",
        "торгов":   "trading_bot_ad",
        "bybit":    "trading_bot_ad",
        "python":   "python_script_ad",
        "скрипт":   "python_script_ad",
        "парсер":   "python_script_ad",
        "агент":    "agent_marketplace",
        "agent":    "agent_marketplace",
        "маркет":   "agent_marketplace",
        "market":   "agent_marketplace",
        "баннер":   "hero_banner",
        "banner":   "hero_banner",
        "команда":  "team_ai_agents",
        "team":     "team_ai_agents",
        "доход":    "revenue_dashboard",
        "revenue":  "revenue_dashboard",
        "money":    "revenue_dashboard",
        "аватар":   "agent_avatar",
        "avatar":   "agent_avatar",
        "соц":      "social_post",
        "social":   "social_post",
        "instagram":"social_post",
        "пост":     "social_post",
    }

    def list_templates(self) -> Dict[str, str]:
        return {k: v["desc"] for k, v in TEMPLATES.items()}

    def generate(self, template_name: str, extra: str = "", save_path: Optional[Path] = None) -> Optional[Path]:
        """Generate one professional MaxAI ad image."""
        tmpl = TEMPLATES.get(template_name, TEMPLATES["hero_banner"])

        # Build full prompt
        full = tmpl["prompt"] + BRAND_SUFFIX
        if extra:
            full = extra.rstrip(",") + ", " + full

        w = tmpl.get("w", 1024)
        h = tmpl.get("h", 1024)
        seed = int(time.time()) % 999999

        log.info("Generating %s (%dx%d)...", template_name, w, h)

        # Try Pollinations.ai first (free)
        path = self._pollinations(full, w, h, seed, template_name, save_path)
        if path:
            return path

        # Fallback: Together AI (if credits available)
        path = self._together(full, w, h, seed, template_name, save_path)
        return path

    def _pollinations(self, prompt: str, w: int, h: int, seed: int,
                      name: str, save_path: Optional[Path]) -> Optional[Path]:
        """Generate via Pollinations.ai (free FLUX)."""
        try:
            encoded = urllib.parse.quote(prompt[:800])  # URL length limit
            url = (
                f"https://image.pollinations.ai/prompt/{encoded}"
                f"?width={w}&height={h}&model=flux&nologo=true&seed={seed}"
                f"&negative={urllib.parse.quote(NEGATIVE[:200])}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "MaxAI/2.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) < 5000:
                log.warning("Pollinations returned too small image: %d bytes", len(data))
                return None
            return self._save(data, name, save_path)
        except Exception as e:
            log.warning("Pollinations failed: %s", e)
            return None

    def _together(self, prompt: str, w: int, h: int, seed: int,
                  name: str, save_path: Optional[Path]) -> Optional[Path]:
        """Generate via Together AI (requires credits)."""
        import os
        key = os.environ.get("TOGETHER_API_KEY", "")
        if not key:
            try:
                with open("/root/my_personal_ai/.env") as f:
                    for line in f:
                        if line.startswith("TOGETHER_API_KEY"):
                            key = line.split("=", 1)[1].strip().strip("'\"")
                            break
            except Exception:
                pass
        if not key:
            return None
        try:
            import httpx
            r = httpx.post(
                "https://api.together.xyz/v1/images/generations",
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                json={"model": "black-forest-labs/FLUX.1-schnell", "prompt": prompt,
                      "width": min(w, 1024), "height": min(h, 1024),
                      "steps": 4, "n": 1, "response_format": "b64_json"},
                timeout=60, verify=False,
            )
            r.raise_for_status()
            b64 = r.json()["data"][0]["b64_json"]
            return self._save(base64.b64decode(b64), name, save_path)
        except Exception as e:
            log.warning("Together AI failed: %s", e)
            return None

    def _save(self, data: bytes, name: str, save_path: Optional[Path]) -> Path:
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        out   = (save_path or IMAGES_DIR) / f"maxai_{name}_{ts}.png"
        out.write_bytes(data)
        log.info("Saved: %s (%d KB)", out.name, len(data) // 1024)
        return out

    def generate_from_request(self, user_text: str) -> Optional[Path]:
        """Smart routing: pick best template from user's text."""
        text = user_text.lower()
        for keyword, tmpl in self.SKILL_MAP.items():
            if keyword in text:
                return self.generate(tmpl, extra=user_text[:100])
        return self.generate("hero_banner")

    def generate_ad_set(self, names: Optional[List[str]] = None) -> Dict[str, Optional[str]]:
        """Generate full MaxAI advertising set."""
        if names is None:
            names = ["hero_banner", "telegram_bot_ad", "trading_bot_ad",
                     "agent_marketplace", "social_post"]
        results = {}
        for n in names:
            path = self.generate(n)
            results[n] = str(path) if path else None
            status = "DONE" if path else "FAILED"
            print(f"  [{status}] {n}" + (f" -> {path.name}" if path else ""))
            time.sleep(3)  # polite delay
        return results

    def send_to_telegram(self, image_path: Path, caption: str = "") -> bool:
        """Send generated image to Telegram channel."""
        import os
        bot_token = ""
        chat_id   = ""
        try:
            with open("/root/my_personal_ai/.env") as f:
                for line in f:
                    if line.startswith("TELEGRAM_BOT_TOKEN"):
                        bot_token = line.split("=", 1)[1].strip().strip("'\"")
                    elif line.startswith("TELEGRAM_CHAT_ID"):
                        chat_id = line.split("=", 1)[1].strip().strip("'\"")
        except Exception:
            pass

        if not bot_token or not chat_id:
            log.warning("Telegram credentials not found")
            return False

        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            with open(image_path, "rb") as f:
                img_data = f.read()
            boundary = "----MaxAIBoundary"
            body  = f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode()
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="photo"; filename="{image_path.name}"\r\nContent-Type: image/png\r\n\r\n'.encode()
            body += img_data
            body += f"\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
            )
            if caption:
                # Add caption as separate param
                cap_url = url + "?" + urllib.parse.urlencode({"chat_id": chat_id, "caption": caption[:1024]})
            with urllib.request.urlopen(req, timeout=30) as r:
                result = json.loads(r.read())
                if result.get("ok"):
                    log.info("Image sent to Telegram")
                    return True
        except Exception as e:
            log.warning("Telegram send failed: %s", e)
        return False


# ── Patch function for image_agent.py ────────────────────────────────────────

def generate_professional_image(user_request: str) -> str:
    """
    Drop-in replacement for image_agent's generate method.
    Returns formatted response string with image path.
    """
    sys = MaxAIImageSystem()
    path = sys.generate_from_request(user_request)
    if path:
        return (
            "MaxAI Image Generated!\n\n"
            "Template: auto-selected for your request\n"
            "Style: Professional MaxAI brand (FLUX model)\n"
            "Saved: " + str(path) + "\n"
            "Size: " + str(path.stat().st_size // 1024) + "KB\n"
            "Provider: Pollinations.ai (FLUX)"
        )
    return "Image generation failed. Check logs for details."


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    sys_img = MaxAIImageSystem()
    print("MaxAI Image System v2 (Pollinations.ai FLUX)")
    print()
    print("Templates:")
    for k, v in sys_img.list_templates().items():
        print(f"  {k:25s} — {v}")
    print()
    print("Generating full ad set (5 images)...")
    results = sys_img.generate_ad_set()
    print()
    print("Results:", json.dumps(results, indent=2))
