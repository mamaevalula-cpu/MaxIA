#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skill Trainer - AI self-learning system
Identifies weak skills and creates learning tasks
Runs on schedule, downloads/installs learning resources
"""
import json, time, subprocess, os, urllib.request, sys

SKILLS_API = "http://localhost:8090/api/skills/matrix"
KNOWLEDGE_API = "http://localhost:8090/api/knowledge/add"
CHAT_API = "http://localhost:8090/api/chat"
LOG_FILE = "/root/my_personal_ai/logs/skill_trainer.log"

LEARNING_RESOURCES = {
    "erp_1c": {
        "topics": ["1C Enterprise REST API", "1C XML data exchange format", "1C accounting automation Python"],
        "install": [],
        "study_urls": ["https://its.1c.ru/db/metod8dev"]
    },
    "multimodal": {
        "topics": ["Flux image generation API", "Replicate API for image generation", "ComfyUI REST API"],
        "install": ["replicate"],
        "study_urls": ["https://replicate.com/docs", "https://fal.ai/docs"]
    },
    "arbitrage": {
        "topics": ["WebSocket orderbook arbitrage", "triangular arbitrage algorithm", "funding rate arbitrage Bybit"],
        "install": [],
        "study_urls": []
    },
    "sfe": {
        "topics": ["affiliate marketing automation Python", "passive income streams API", "DeFi yield farming Python"],
        "install": [],
        "study_urls": []
    },
    "sales": {
        "topics": ["B2B sales automation", "CRM Python integration", "automated invoice generation"],
        "install": [],
        "study_urls": []
    },
    "sast_audit": {
        "topics": ["SAST static analysis Python", "GitHub API private repo scanning", "security vulnerability patterns AST"],
        "install": [],
        "study_urls": []
    },
    "uiux_audit": {
        "topics": ["UI/UX automated audit Selenium", "accessibility testing Python", "Resend email API integration"],
        "install": [],
        "study_urls": []
    }
}

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def get_weak_skills():
    try:
        with urllib.request.urlopen(SKILLS_API, timeout=10) as r:
            data = json.loads(r.read())
            return [(s["id"], s["name"], s["mastery"], s.get("next_training", ""))
                    for s in data.get("skills", []) if s["mastery"] < 65]
    except Exception as e:
        log(f"ERROR getting skills: {e}")
        return []

def ask_ai_to_learn(topic):
    try:
        msg = f"LEARNING TASK: Study the topic '{topic}' and save key knowledge to knowledge base. Describe 3-5 key concepts and a practical code example."
        req = urllib.request.Request(
            CHAT_API,
            data=json.dumps({"message": msg}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
            return resp.get("response", "")[:500]
    except Exception as e:
        return f"Error: {e}"

def install_packages(packages):
    for pkg in packages:
        try:
            result = subprocess.run(
                ["/root/venv/bin/pip", "install", pkg, "--quiet"],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                log(f"Installed: {pkg}")
            else:
                log(f"Failed to install {pkg}: {result.stderr[:100]}")
        except Exception as e:
            log(f"Install error {pkg}: {e}")

def add_to_knowledge(title, content, tags):
    try:
        data = json.dumps({"title": title, "content": content, "tags": tags}).encode("utf-8")
        req = urllib.request.Request(
            KNOWLEDGE_API, data=data,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}

def main():
    log("=== Skill Trainer started ===")
    weak_skills = get_weak_skills()
    if not weak_skills:
        log("No weak skills found or API unavailable")
        return
    log(f"Found {len(weak_skills)} weak skills: {[s[0] for s in weak_skills]}")
    for skill_id, skill_name, mastery, next_training in weak_skills[:2]:
        log(f"Training skill: {skill_name} (mastery={mastery}%)")
        resources = LEARNING_RESOURCES.get(skill_id, {})
        if resources.get("install"):
            log(f"Installing packages for {skill_id}: {resources['install']}")
            install_packages(resources["install"])
        topics = resources.get("topics", [next_training] if next_training else [skill_name])
        for topic in topics[:2]:
            log(f"Learning topic: {topic}")
            ai_response = ask_ai_to_learn(topic)
            log(f"AI response preview: {ai_response[:100]}")
            time.sleep(3)
        result = add_to_knowledge(
            title=f"Skill Training: {skill_name}",
            content=f"Skill ID: {skill_id}, Mastery: {mastery}%, Next training focus: {next_training}",
            tags=["skill_training", skill_id, "auto_learning"]
        )
        log(f"Knowledge added: {result}")
    log("=== Skill Trainer completed ===")

if __name__ == "__main__":
    main()

