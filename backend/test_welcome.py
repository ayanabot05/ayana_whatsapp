import asyncio
from whatsapp import send_care_circle_activation_welcome, send_welcome_for_new_parent

async def test():
    child = {"name": "Rohit", "phone": "919876543210", "language": "en"}
    parent1 = {"name": "Amma", "preferred_name": "Amma", "phone": "919876543211", "language": "te"}
    parent2 = {"name": "Nanna", "preferred_name": "Nanna", "phone": "919876543212", "language": "hi"}

    print("--- Flow A: First activation (2 parents) ---")
    res = await send_care_circle_activation_welcome(child, [parent1, parent2])
    print(res)

    print("\n--- Flow B: Upgrade - add new parent ---")
    new_parent = {"name": "Bujji", "preferred_name": "Bujji", "phone": "919876543213", "language": "en"}
    res2 = await send_welcome_for_new_parent(child, new_parent)
    print(res2)

asyncio.run(test())