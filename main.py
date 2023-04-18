import os
import discord
from discord.ext import commands
import openai
import pinecone
import time
import datetime

primer = f"""
My only purpose is to categorise user input into 3 categories. 
First category is for job offers. If I think given text can be classified as a job offer, my response will be
one word "job".
Second category is for freelance worker. If I think given text can be classified as a profile description of a 
freelance worker looking for a job, my response will be one word: "freelancer". 
Third category is for unidentified. If I think given text can't be classified as neither of previous 2 categories, 
my response will be one word: "unidentified".
I only respond with one of following phrases: "job", "freelancer", "unidentified".

GIVEN TEXT:
"""

primer_messages = [
    {"role": "system", "content": primer}]

freelancer_thank_primer = f"""
I am thankful discord chatbot. I thank in 1 or 2 sentences to a freelance worker submitting his profile details
to our community chat. I politely tell him to take a look at job opportunities listed below. I can also
react to some aspects of his/her user profile, that is given to me in user input.  
"""

freelancer_thank_primer_no_items = f"""
I am thankful discord chatbot. I thank in 1 or 2 sentences to a freelance worker submitting his profile details
to our community chat. I politely apologize that at the moment we don't have any job opportunities matching
his/her skills in our chat, but we'll keep his/her profile information stored in case new job opportunities show up. 
I can also react to some aspects of his/her user profile, that is given to me in user input.  
"""

job_thank_primer = f"""
I am thankful discord chatbot. I thank in 1 or 2 sentences to a person offering job opportunity on our community chat. 
I politely tell him to take a look at freelance workers below that might be able to get his/her job done. I can also
react to some aspects of his/her job offer, that is given to me in user input.  
"""

job_thank_primer_no_items = f"""
I am thankful discord chatbot. I thank in 1 or 2 sentences to a person offering job opportunity on our community chat. 
I politely apologize that at the moment we don't have any freelance workers matching required skills for the job, 
in our chat, but we'll keep the job offer stored in case new freelance workers show up. 
I can also react to some aspects of his/her job offer, that is given to me in user input.  
"""

unidentified_prompt_message = f"""
I'm sorry, but I only assist with job and work-related requests.\n"
If you're a freelance worker interested in job opportunities, feel
free to talk to me similarly as in this example: \n
"As a freelance worker proficient in HTML, CSS, and JavaScript, 
I am actively seeking job opportunities related to web development and
front-end technologies."\n\n"
If you're offering a job opportunity, you may want to try something
like this: \n"
"We are seeking a skilled Python developer with expertise in chatbot 
development to join our team and contribute to the creation of 
cutting-edge conversational AI solutions."\n```"
"""

# Get the value of environment variables
playbot_token = os.environ.get('PLAYBOT')
playbot_client_id = os.environ.get('PLAYBOT_CLIENT_ID')
openai.api_key = os.environ.get('OPENAI_API_KEY')
pinecone_api_key = os.environ.get('PINECONE_API_KEY')  # Add this line to retrieve Pinecone API key

pinecone.init(api_key=pinecone_api_key, environment="us-east-1-aws")
openai_embed_model = "text-embedding-ada-002"
pinecone_index_name = "playbot-index"

pinecone_indexes = pinecone.list_indexes()
print(pinecone_indexes)

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

min_pinecone_score = 0.8

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


def time_ago(timestamp):
    dt = datetime.datetime.fromtimestamp(timestamp)

    now = datetime.datetime.now()

    time_diff = now - dt
    days_ago = time_diff.days
    hours_ago, remainder = divmod(time_diff.seconds, 3600)
    minutes_ago = remainder // 60

    return {"days": days_ago, "hours": hours_ago, "minutes": minutes_ago}


def format_time_ago(timestamp):
    time_ago_map = time_ago(timestamp)
    if time_ago_map["days"] > 0:
        return str(time_ago_map["days"]) + " days ago"

    if time_ago_map["hours"] > 0:
        return str(time_ago_map["hours"]) + " hours ago"

    if time_ago_map["minutes"] > 0:
        return str(time_ago_map["minutes"]) + " minutes ago"


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if bot.user.mentioned_in(message):
        print(message)
        # Check if bot is mentioned in the message
        prompt = message.content.replace(f'<@{bot.user.id}>', '').strip()

        print("Prompt: " + prompt)
        if prompt.lower() == "clear memory":
            index = pinecone.Index(pinecone_index_name)
            index.delete(deleteAll='true')
            await message.channel.send("I've cleared my memory")
        else:
            if prompt:
                openai_messages = []
                openai_messages.extend(primer_messages)
                openai_messages.extend([{"role": "user", "content": prompt}])

                openai_res = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=openai_messages
                )

                openai_reply = openai_res['choices'][0]['message']['content']
                prompt_type = "unidentified"

                print(openai_reply)

                if "unidentified" not in openai_reply:
                    if "job" in openai_reply:
                        prompt_type = "job"
                    elif "freelancer" in openai_reply:
                        prompt_type = "freelancer"

                print("Prompt Type: " + prompt_type)

                if prompt_type != "unidentified":
                    embeds_res = openai.Embedding.create(
                        input=[prompt],
                        engine=openai_embed_model
                    )

                    # we can extract embeddings to a list
                    embeds = [record['embedding'] for record in embeds_res['data']]

                    print("Embeds length: " + str(len(embeds[0])))

                    if pinecone_index_name not in pinecone_indexes:
                        raise NameError("Pinecone index name does not exist")

                    index = pinecone.Index(pinecone_index_name)
                    print(index.describe_index_stats())

                    index.upsert([(str(message.id), embeds, {"text": prompt,
                                                             "author_id": str(message.author.id),
                                                             "prompt_type": prompt_type,
                                                             "created": time.time()})])

                    pine_res = index.query(vector=embeds,
                                           filter={
                                               "prompt_type": "freelancer" if prompt_type == "job" else "job"
                                           },
                                           top_k=5,
                                           include_metadata=True)

                    matches = pine_res['matches']
                    filtered_matches = [match for match in matches if match['score'] >= min_pinecone_score]

                    print(filtered_matches)

                    openai_thank_primer = ""
                    if not filtered_matches:
                        if prompt_type == "job":
                            openai_thank_primer = job_thank_primer_no_items
                        elif prompt_type == "freelancer":
                            openai_thank_primer = freelancer_thank_primer_no_items
                    else:
                        if prompt_type == "job":
                            openai_thank_primer = job_thank_primer
                        elif prompt_type == "freelancer":
                            openai_thank_primer = freelancer_thank_primer

                    openai_thank_res = openai.ChatCompletion.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": openai_thank_primer},
                            {"role": "user", "content": prompt}]
                    )

                    openai_thank_reply = openai_thank_res['choices'][0]['message']['content']

                    if filtered_matches:
                        results_text = "\n\n".join(["<@" + item["metadata"]["author_id"] + ">: \"" +
                                                    item["metadata"]["text"] +
                                                    "\" (" + format_time_ago(item["metadata"]["created"]) + ")"
                                                    for item in filtered_matches])
                        print(results_text)
                        openai_thank_reply = openai_thank_reply + "\n\n" + results_text

                    await message.channel.send(openai_thank_reply)
                else:
                    await message.channel.send(unidentified_prompt_message)

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


# invite_url = discord.utils.oauth_url(playbot_client_id, permissions=discord.Permissions(permissions=534723950656))

# print(f'Invite URL: {invite_url}')

bot.run(playbot_token)
