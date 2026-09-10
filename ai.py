import os, sys
from openai import OpenAI

key = os.getenv("EXPLABS_API_KEY")
if not key:
    print("EXPLABS_API_KEY isn't set.")
    print("Run this first in THIS window:")
    print("set EXPLABS_API_KEY=xpl_YOUR_KEY_HERE")
    sys.exit(1)

client = OpenAI(
    api_key=key,
    base_url="https://api.experientiallabs.ai/v1"
)

print("\n=== GPT-6 Astra via Experiential ===")
print("Model: gpt-6-astra | Type 'exit' to quit\n")

messages = [{"role": "system", "content": "You are Astra, running in Windows CMD for ayana_whatsapp project."}]

while True:
    try:
        user_input = input("You: ")
    except KeyboardInterrupt:
        break

    if user_input.lower() in ["exit", "quit"]:
        break
    if not user_input.strip():
        continue

    messages.append({"role": "user", "content": user_input})

    resp = client.chat.completions.create(
        model="gpt-6-astra",
        messages=messages
    )

    reply = resp.choices[0].message.content
    print(f"\nAstra: {reply}\n")
    messages.append({"role": "assistant", "content": reply})