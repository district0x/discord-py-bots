import os
import discord
from discord.ext import commands

# Get the value of an environment variable
playbotToken = os.environ.get('PLAYBOT')
playbotClientID = os.environ.get('PLAYBOT_CLIENT_ID')

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True

client = commands.Bot(command_prefix='!', intents=intents)


@client.event
async def on_ready():
  print('Bot is ready.')


@client.event
async def on_message(message):
  if message.author == client.user:
    return

  if message.content.startswith('hello'):
    await message.channel.send('Hello there!')

invite_url = discord.utils.oauth_url(
  playbotClientID, permissions=discord.Permissions(permissions=534723950656))
print(f'Invite URL: {invite_url}')

client.run(playbotToken)
