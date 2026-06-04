#!/usr/bin/env python3
"""Register MaxAI agent on Agentverse / Fetch.ai"""
import os, sys
os.environ["AGENTVERSE_KEY"] = "eyJhbGciOiJSUzI1NiJ9.eyJleHAiOjE3ODAzNjc4MjEsImlhdCI6MTc4MDM2NDIyMSwiaXNzIjoiZmV0Y2guYWkiLCJqdGkiOiIxYWViNDdjZWNhYmY0ZTk0M2I3ZjkxZGIiLCJzY29wZSI6IiIsInN1YiI6IjZlNjAzNjAxZmM4OTU2ODYyNzliMmE1ZGY0M2EzZTcwZGM1MWM5YTliYjYwZGQwYyJ9.E9kL3RaG5bTGawEcylfmqQCFci0Hz34jZUZWxQ6zq3VHhU0R4GHpOb9mingO6ijJQJtDJQuJhQ5aO6pgD4aZD9GWxKW8nXDuJzERDD8IVtkRq9n_BCjQORHjVLpiMac_Ty3wghADK6HSe4gbIhFurhMmnG4yGgKGpb-Pwrz72qrKAuzhtGSh2iBy0KlhPo6JRqDB5SNvbH8s3F65heiI14ssS-4hy8lQ1QKh0LWk826ws5pMhjhLno2AqS43EbT7D1VA_WruBkmiKFT4j-ZLZhp4H8iKRCNuCjL1OcIjGvAvS8LEGLrQjwFELsMuyM0NmMlK7uFEKBMRoIVUXlhRBA"
os.environ["AGENT_SEED_PHRASE"] = "6b16937d1142d93b1b2b002b056f6c465155695f3882eda2f4bbcfe9e170ce07"

from pathlib import Path
env_path = Path("/root/my_personal_ai/.env")
for l in env_path.read_text().splitlines():
    if "=" in l and not l.startswith("#"):
        k,_,v = l.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

try:
    from uagents_core.utils.registration import register_chat_agent, RegistrationRequestCredentials
    result = register_chat_agent(
        "MaxAI Research Trading Agent",
        "http://77.90.2.171/api/public/analyze",
        active=True,
        credentials=RegistrationRequestCredentials(
            agentverse_api_key=os.environ["AGENTVERSE_KEY"],
            agent_seed_phrase=os.environ["AGENT_SEED_PHRASE"],
        ),
    )
    print("Registration result:", result)
except Exception as e:
    print("Error:", e)
    print("The AGENTVERSE_KEY may need to be refreshed from agentverse.ai")
