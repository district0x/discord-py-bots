import os
import discord
from discord.ext import commands
import openai

# Get the value of environment variables
playbot_token = os.environ.get('PLAYBOT')
playbot_client_id = os.environ.get('PLAYBOT_CLIENT_ID')
openai.api_key = os.environ.get('OPENAI_API_KEY')

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

bot = commands.AutoShardedBot(command_prefix='/', intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    print('------')

# Define a custom help command
class CustomHelpCommand(commands.DefaultHelpCommand):
    pass

# Register the custom help command
bot.help_command = CustomHelpCommand()

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if bot.user.mentioned_in(message):
        # Check if bot is mentioned in the message
        prompt = message.content.replace(f'<@!{bot.user.id}>', '').strip()
        if prompt:
            response = openai.Completion.create(
                model="text-davinci-003",
                prompt=prompt,
                temperature=0.7,
                max_tokens=100
            )
            generated_text = response.choices[0].text
            await message.channel.send(generated_text)

    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        # If command is not found, suggest similar commands
        cmd = ctx.message.content.split()[0]
        suggested_cmds = [cmd.name for cmd in bot.commands if cmd.name.startswith(cmd)]
        if suggested_cmds:
            suggested_cmds.sort()
            await ctx.send(f"Command not found. Did you mean: `{', '.join(suggested_cmds)}`?")
        else:
            await ctx.send("Command not found. Please use a valid command.")
    else:
        raise error

# invite_url = discord.utils.oauth_url(
#  playbot_client_id, permissions=discord.Permissions(permissions=534723950656))
# print(f'Invite URL: {invite_url}')

bot.run(playbot_token)
