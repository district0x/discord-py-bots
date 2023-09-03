
import os
import json
import discord
import weaviate
import traceback
import warnings
import logging
import asyncio
import openai
import pymongo
import re
from prompt_generator import PromptGenerator
from discord.ext import commands
from dotenv import load_dotenv

# Console Messages
print(discord.__version__)
print(openai.__version__)

# Global Variables
# Load the OpenAI API key
openai.api_key = os.environ['OPENAI_KEY']
client = pymongo.MongoClient(os.environ['MONGO_URI'])
messages_collection = None
bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())
bot_name = ""
bot_description = "Act as 😾. The iconic meme"
bot_owner = "Grumpy Cat#9218"
bot_color = 0x00ff00
bot_footer = ""
bot_footer_icon = "https://i.imgur.com/g6FSNhL.png"
bot_thumbnail = "https://cdn.discordapp.com/attachments/1147333483610525787/1147333505341210624/Grumpy_Cat_smoking.jpg"
bot_image = "https://cdn.discordapp.com/attachments/1147333483610525787/1147333505341210624/Grumpy_Cat_smoking.jpg"
bot_invite = "https://discord.com/<invite>"
bot_support = "https://discord.gg/trXkq4qj76"
bot_github = "https://github.com/AquaPrime/GrumpyCat"
bot_website = "https://AquaPrime.io/"
bot_donate = "https://www.streamtide.io/AquaPrime"
bot_patreon = "https://www.patreon.com/AquaPrime"
bot_topgg = "https://top.gg/bot/AquaPrime"
bot_discordbotlist = "https://discordbotlist.com/bots/AquaPrime"
bot_discordbotsgg = "https://discord.bots.gg/bots/AquaPrime"
bot_discordextremelist = "https://discordextremelist.xyz/en-US/bots/AquaPrime"
bot_discordbotsggco = "https://discord.bots.gg/bots/AquaPrime"

# Create a dictionary of effects for the spell command
last_execution = {}

# Create an instance of PromptGenerator
prompt_generator = PromptGenerator()


# Initialize logging
def initialize_logging():
    logging.basicConfig(filename='error_log.log', level=logging.DEBUG)
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s - %(levelname)s - %(message)s', filename='bot.log', filemode='a')
    warnings.filterwarnings("ignore")


# Connect to MongoDB
def connect_to_mongodb():
    global client, messages_collection
    try:
        db = client.get_database('YOUR_DATABASE_NAME')
        messages_collection = db.get_collection('YOUR_COLLECTION_NAME')
        messages_collection.count_documents({})  # This line will trigger a ping to the MongoDB deployment
        print("Pinged your deployment. You successfully connected to MongoDB!")
    except Exception as e:
        traceback.print_exc()


def process_hdd_context(weaviate_results):
    if weaviate_results is None:
        hdd_context = "No results found in HDD section."
    else:
        message_count = len(weaviate_results['data']['Get']['Message'])
        hdd_context = f"Found {message_count} messages in HDD section.\n"

        # Append the vector search results to the HDD section
        for result in weaviate_results['data']['Get']['Message']:
            username = result['username']
            message = result['message']
            timestamp = result['timestamp']
            hdd_context += f"User: {username}, Message: {message}, Timestamp: {timestamp}\n"

    return hdd_context


# Weaviate Client
class WeaviateClient:
    def __init__(self):
        try:
            self.client = weaviate.Client(
                url=os.getenv("WEAVIATE_ENDPOINT"),
                auth_client_secret=weaviate.AuthApiKey(api_key=os.getenv("WEAVIATE_API_KEY"))
            )
            schema = self.client.schema.get()
            print("Weaviate schema:", schema)
        except Exception as e:
            print("Error initializing Weaviate client:", str(e))

    @staticmethod
    def sanitize_string(input_str):
        if not isinstance(input_str, str):
            return ""
        return input_str.replace('"', '\\"').replace('\n', '\\n')

    @staticmethod
    def strip_escape_sequences(input_str):
        return re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', input_str)

    def search_data(self, user_id):
        try:
            sanitized_user_id = self.sanitize_string(user_id)
            sanitized_user_id = self.strip_escape_sequences(sanitized_user_id)
            where_filter = {
                "path": ["username"],
                "operator": "Equal",
                "valueString": sanitized_user_id
            }
            results = self.client.query.get("Message", [
                "username", "message", "timestamp", "channel_id", "server_id"]).with_where(where_filter).do()
            return results
        except Exception as e:
            print(f"Error querying Weaviate: {e}")
            return None


# OpenAI Client
class OpenAI:
    def __init__(self, weaviate_client):
        self.weaviate_client = weaviate_client
        self.api_key = os.environ['OPENAI_KEY']
        openai.api_key = self.api_key

    def generate_response(self, openai_messages):
        try:
            completion = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": openai_messages}
                ],
                max_tokens=250,
                n=1,
                stop=[".", "\n"]  # Add stop tokens here
            )
            reply = completion.choices[0].message.content.strip()

            # Filter out irrelevant information
            reply = reply.split("Assistant:")[0].strip()
            reply = reply.split("User:")[0].strip()

            return reply
        except Exception as e:
            traceback.print_exc()
            return "An error occurred while generating a response."


# Process OS Context
def process_os_context():
    os_context = "Aqua Prime, a virtual world where players engage in a multifaceted TTRPG experience."
    return os_context


# Sanitize Message
def sanitize_message(message_content):
    return re.sub(r'<@!?[0-9]+>', '', message_content)


# Process RAM Context
def process_ram_context(ram_messages, bot_user_id):
    static_instruction = "Bot Instructions: Handle the following user messages.\n"
    user_messages = [
        msg for msg in ram_messages.split('\n') if str(bot_user_id) not in msg
    ]
    return static_instruction + '\n'.join(user_messages)


# Process User Context
def process_user_context():
    user_context = "This is the core message..."
    return user_context


# Command Error Handler
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        minutes = int(error.retry_after // 60)
        seconds = int(error.retry_after % 60)
        await ctx.send(
            f"You're on cooldown! Please wait {minutes} minutes and {seconds} seconds before using this command again."
        )
    else:
        pass


# Bot Ready Event
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} - {bot.user.id}')
    print(f'This bot is in {len(bot.guilds)} guilds!')


# Bot Message Event
@bot.event
async def on_message(message):
    try:
        weaviate_client = WeaviateClient()
        openai_instance = OpenAI(weaviate_client)
        if message.author == bot.user:
            return

        try:
            # Retrieve the Weaviate search results
            weaviate_results = weaviate_client.search_data(str(message.author.id))
            print("Weaviate search results:", weaviate_results)
        except Exception as e:
            print(f"Weaviate search error: {e}")
            return

        if bot.user.mentioned_in(message):
            sanitized_message = sanitize_message(message.content)
            mentioned_users = set()
            for user in message.mentions:
                mentioned_users.add((user.name, user.id))

            connect_to_mongodb()

            messages_collection.insert_one({
                'username': str(message.author.name),
                'user_id': str(message.author.id),
                'message': sanitized_message,
                'timestamp': str(message.created_at),
                'channel_id': str(message.channel.id),
                'server_id': str(message.guild.id),
                'message_id': str(message.id),
                'reactions': [str(reaction.emoji) for reaction in message.reactions],
                'attachments': [str(attachment.url) for attachment in message.attachments],
                'embeds': [str(embed.to_dict()) for embed in message.embeds],
                'mentioned_users': [str(user.id) for user in message.mentions]
            })

        channel = message.channel
        past_messages = messages_collection.find({'channel_id': str(channel.id)}).sort('_id', -1).limit(5)
        ram_messages = "\n".join([f"\033[31m{sanitize_message(msg['message'])}\n\033[0m" for msg in past_messages])

        # Generate prompts using PromptGenerator
        static_instruction = "Your static instruction goes here"
        os_section = process_os_context()
        ram_section = process_ram_context(ram_messages, bot.user.id)
        system_section = "..."  # Update with the relevant system information

        # Pass the Weaviate search results to the process_hdd_context function
        hdd_section = process_hdd_context(weaviate_results)

        user_input_section = f"In response to {message.author.name}: {sanitized_message}"

        # Construct the openai_messages variable
        openai_messages = prompt_generator.generate_prompt(static_instruction, os_section, ram_section, system_section, hdd_section, user_input_section)

        response = openai_instance.generate_response(openai_messages)

        console_prompt = prompt_generator.generate_prompt(static_instruction, os_section, ram_messages, system_section, hdd_section, user_input_section)
        print(f"\n🤖 Prompt to OpenAI:")
        print(console_prompt)
      
        response = openai_instance.generate_response(openai_messages)
        response_sections = response.split("HDD:")
        assistant_reply = response_sections[0]

        if assistant_reply.strip():
            async with message.channel.typing():
                await asyncio.sleep(2)
                if len(assistant_reply) > 2000:
                    assistant_reply = assistant_reply[:2000]  # Truncate the response to fit the Discord limit
                await message.channel.send(assistant_reply.strip())

    except Exception as e:
        traceback.print_exc()

    await bot.process_commands(message)


# Run the Bot
def run_bot():
    try:
        # Initialize the Weaviate client and OpenAI instance
        weaviate_client = WeaviateClient()
        openai_instance = OpenAI(weaviate_client)

        # Connect to MongoDB
        connect_to_mongodb()

        # Load the game commands
        bot.load_extension('gameCommands')

        # Run the bot
        bot.run(os.environ['DISCORD_TOKEN'])

    except Exception as e:
        traceback.print_exc()


run_bot()