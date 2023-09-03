from context import process_os_context, process_hdd_context, process_ram_context, process_user_context

def process_os_context():
    # Replace with your logic to process OS context from your game world data
    os_context = '''"Role: OS
Setting: Aqua Prime, a virtual world where players engage in a multifaceted TTRPG experience.

Factions:
- Economic Factions: Focus on trading, crafting, mining, and resource management.
- Exploration Factions: Emphasize discovery, adventure, and mapping uncharted territories.
- Cultural Factions: Engage with narrative, memes, pop culture, and satire.
- Technological Factions: Concentrate on AI development and technological advancement.

Roles:
- Players join or create factions with unique goals and culture.
- Leadership structures vary across factions.

Bots:
- AI-driven bots guide players, enforce rules, and enhance role-playing.
- Custom bots reflect faction identity and goals.

Economics:
- Factions manage shared resources like Moonstones, crafting materials, and currency.
- Economy Bot oversees in-game currency, shop, and rewards.

Resources:
- Collect Moonstones from factions and players; burn for ship power during streams.

Rewards:
- Successful players receive prizes decided by factions, including NFTs and crypto.

Diverse Gameplay:
- Factions like Doge Cult, Thieves Guild, Bankers, Law, Bufficorn Cavalry, Meme Factory, Telephone Company, and Dark Cloud Militia offer diverse playstyles and interactions.

These factions and mechanics enrich Aqua Prime's gameplay, fostering strategic choices, creativity, and collaborative experiences.
"'''
    return os_context


def process_hdd_context():
    # Replace with your logic to process HDD context from MongoDB and Weaviate
    hdd_context = "This is the long term summary of the final prompt and must not be sent to chat and is simply logged in mongo after the user recives a response creating a TLDR of the game state and scenario for the assiciated user IDS, roles, and bots involved in the summary"
    return hdd_context


def process_ram_context():
    # Replace with your logic to process RAM context from recent messages
    ram_context = "Summarize everything the user and others have said in the last 5 messages along with any mentioned user and bots or roles, etc. This ensures short term memory is accounted for in the response"
    return ram_context


def process_user_context():
    # Replace with your logic to process User context from MongoDB
    user_context = "This is the core message the bot must respond to after collecting full context of the game world, roles, user, past messages, etc. This ensures the message send from the user is core to the response and exibits personality and game master responses appropriate for the message the user is sending"
    return user_context
