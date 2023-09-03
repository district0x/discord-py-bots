import os
import openai
import weaviate
from weaviate import Client
from utils import WeaviateClient
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import traceback
import logging

logging.basicConfig(filename='error_log.log', level=logging.ERROR)

def process_os_context():
    try:
        os_context = '''"Role: OS
        ...
        fostering strategic choices, creativity, and collaborative experiences.
        "'''
        return os_context
    except Exception as e:
        logging.error("Error processing OS context: %s", str(e))  # Logging the error
        traceback.print_exc()

# Replace these placeholders with your actual context processing logic
def process_os_context():
    try:
        os_context = '''"Role: OS
        ...
        fostering strategic choices, creativity, and collaborative experiences.
        "'''
        return os_context
    except Exception as e:
        traceback.print_exc()
        print("Error processing OS context:", str(e))


def process_hdd_context():
    try:
        hdd_context = "This is the long term summary..."
        return hdd_context
    except Exception as e:
        traceback.print_exc()
        print("Error processing HDD context:", str(e))


def process_ram_context():
    try:
        ram_context = "Summarize everything the user has said..."
        return ram_context
    except Exception as e:
        traceback.print_exc()
        print("Error processing RAM context:", str(e))


def process_user_context():
    try:
        user_context = "This is the core message..."
        return user_context
    except Exception as e:
        traceback.print_exc()
        print("Error processing user context:", str(e))


class WeaviateClient:
    def __init__(self):
        try:
            self.client = weaviate.Client(
                url="https://soghv1qtoysbn6krtzakq.gcp-d.weaviate.cloud"
            )
        except Exception as e:
            logging.error("Error initializing Weaviate client: %s", str(e))  # Logging the error
            traceback.print_exc()

    def add_data(self, data):
        try:
            weaviate_data = {
                "class": "Message",
                "id": data["message_id"],
                "properties": {
                    "username": data["username"],
                    "message": data["message"],
                    "timestamp": data["timestamp"],
                    "channel_id": data["channel_id"],
                    "server_id": data["server_id"],
                    "reactions": data["reactions"],
                    "attachments": data["attachments"],
                    "embeds": data["embeds"],
                    "mentioned_users": data["mentioned_users"]
                }
            }
            self.client.data_object.create(data_object=weaviate_data, class_name="Message")
        except Exception as e:
            logging.error("Error adding data to Weaviate: %s", str(e))  # Logging the error
            traceback.print_exc()

    def search_data(self, query):
        try:
            pass
          #  return self.client.query.v1.query(query)
        except Exception as e:
            logging.error("Error searching data in Weaviate: %s", str(e))  # Logging the error
            traceback.print_exc()

class OpenAI:
    def __init__(self):
        self.api_key = os.environ['OPENAI_KEY']
        openai.api_key = self.api_key
        self.weaviate_client = WeaviateClient()  # Initialize WeaviateClient object

    def generate_response(self, user_message):
        # Rest of the code remains the same

        system_message = '''Setting: Aqua Prime, a world where players dance with sand dollars, burn moonstones, and in Grumpy Cat's guise, master the dungeon's enigmatic embrace.'''

        try:
            # Invoke the spirit of Weaviate client
            weaviate_client = self.weaviate_client  # No longer a stranger, but an intimate friend

            uri = os.environ['MONGO_URI']
            mongo_client = MongoClient(uri)
            db = mongo_client['discord']
            messages_collection = db['messages']

            # Create a new client and connect to the server
            client = MongoClient(uri, server_api=ServerApi('1'))

            # Send a ping to confirm a successful connection
            try:
                client.admin.command('ping')
                print("Pinged your deployment. You successfully connected to MongoDB!")
            except Exception as e:
                traceback.print_exc()
                print(e)
            # Initialize the vessel of Discord
            intents = discord.Intents.all()
            intents.messages = True
            bot = commands.Bot(command_prefix='!', intents=intents)

            # Initialize OpenAI's whispered wisdom
            openai = OpenAI()

            @bot.event
            async def on_ready():
                print(f'Logged in as {bot.user.name}, the harbinger of virtual fate.')

            @bot.event
            async def on_message(message):
                try:
                    if message.author == bot.user:
                        return
                    if bot.user.mentioned_in(message):
                        user_id = str(message.author.id)
                        # Retrieve memories from MongoDB
                        past_messages = messages_collection.find({'channel_id': str(message.channel.id)}).sort('_id', -1).limit(5)
                        ram_messages = " ".join([past_message['message'] for past_message in past_messages])

                        # Seek answers in Weaviate's arcane texts
                        hdd_context = weaviate_client.search_data(ram_messages)

                        # Forge the celestial prompt
                        prompt = f"Role: System\nRole: HDD - {hdd_context}\nRole: RAM - {ram_messages}\nRole: User - {user_id}\n"

                        # Converse with OpenAI's mystical oracle
                        response = openai.generate_response(prompt)
                        grumpycat_reply = response.strip()

                        await message.channel.send(grumpycat_reply)

                except Exception as e:
                    traceback.print_exc()
                    print(f"An error occurred, a tempest in the code: {e}")

                await bot.process_commands(message)

            # Embark on the voyage with the bot
            bot_token = os.getenv("DISCORD_TOKEN")
            bot.run(bot_token)

        except Exception as e:
            traceback.print_exc()
            print(f"A celestial error occurred, a rift in the fabric of code: {e}")

# Call upon the energies to run the bot
def run_bot():
    try:
        bot = OpenAI()
        bot.generate_response("User message")
    except Exception as e:
        traceback.print_exc()
        print(f"An error occurred, a whisper in the void: {e}")

run_bot()