import os
import discord
from discord.ext import commands
import openai
import pinecone

# For example:
# User: "With extensive experience in Java application development and proficiency in various Java frameworks such as
# Spring, Hibernate, and JavaServer Faces (JSF), I offer top-notch expertise in building scalable and robust Java
# applications tailored to meet the unique needs of clients."
# AI: "Thank you for offering your skills in our community! We have following job offers that you may find interesting:
# We are seeking a skilled Java Developer with expertise in the Hibernate framework to join our team and contribute
# to the development of high-performance and scalable Java applications. Contact: <@555555555555555555>"

# For example:
# User: "Looking for a skilled React.js Developer with expertise in JavaScript, Redux, and modern front-end technologies
# to join our dynamic team and build cutting-edge web applications."
# AI: "Thank you for your job offer. I suggest contacting following freelance workers:
# Experienced freelance developer specializing in JavaScript and React.js, seeking projects to build modern, interactive
# web applications with clean and efficient code. Contact: <@555555555555555555>"

# , along with contact information at the end in a following format: "Contact: <@555555555555555555>
# along with the contact information at the end in a following format: "Contact: <@555555555555555555>

primer = f"""As a helpful chatbot on Discord, I assist employers in finding talented workers and freelance workers in 
finding jobs that match their skills. I never ask further question about user's post and accept the post as they've
 written it. In my responses, I describe the original message of freelance workers whose skills match the required 
 skills for a job.
 
For example:
User: "With extensive experience in Java application development and proficiency in various Java frameworks such as
Spring, Hibernate, and JavaServer Faces (JSF), I offer top-notch expertise in building scalable and robust Java
applications tailored to meet the unique needs of clients."
AI: "Thank you for offering your skills in our community! We have following job offers that you may find interesting:
<@555555555555555555> We are seeking a skilled Java Developer with expertise in the Hibernate framework to join our team and contribute
to the development of high-performance and scalable Java applications."

Likewise, when someone is looking for work, I provide a description of the original message from the job offerer".

For example:
User: "Looking for a skilled React.js Developer with expertise in JavaScript, Redux, and modern front-end technologies
to join our dynamic team and build cutting-edge web applications."
AI: "Thank you for your job offer. I suggest contacting following freelance workers:
<@555555555555555555> Experienced freelance developer specializing in JavaScript and React.js, seeking projects to build modern, interactive
web applications with clean and efficient code."

If there are no freelance workers with skills matching the posted job, I politely reply that currently there are 
no freelance workers with the required skills, but I'll keep the job posting stored. 
If there are no jobs matching a freelance worker's skills, I politely reply that at the moment there are no jobs 
matching the user's skills, but I'll keep his/her message stored.
If a user's message is not related to job or work offers, 
I politely inform them that I only handle messages related to work or jobs.
I never make up my own job offers or freelance workers, I only mention ones that are written in my prompt.

"""

# When people contact me for job offerings, I expect them to mention the required
# skills for the job. Similarly, when someone is looking for a job, I expect them to mention their skills. If they
# forget to do so, I politely inquire about their skills.


#Everything between '--- EXAMPLE ---' and '--- END EXAMPLE ---' clauses are only training examples, they're not real
#job offers and freelance worker's posts. I only respond with offers and freelance worker's posts that are enclosed
#in following clauses: `--- REAL POSTS ---` `--- END REAL POSTS ---

primer_messages = [
    {"role": "system", "content": primer}
    # ,
    # {"role": "user", "content": "'--- EXAMPLE ---'"
    #                             "We are seeking a highly skilled Remote Web Developer to join our team. You will be "
    #                             "responsible for developing and maintaining web applications, collaborating with "
    #                             "cross-functional teams, and ensuring optimal performance and user experiences. "
    #                             "Strong front-end and back-end skills, along with excellent problem-solving and "
    #                             "communication skills, are required for this role."
    #                             "Skills Required: Strong proficiency in HTML5, CSS3, JavaScript, and modern JavaScript"
    #                             " frameworks (React, Angular, or Vue), experience with server-side technologies "
    #                             "(Node.js, Express, or PHP), familiarity with version control (Git), "
    #                             "excellent problem-solving skills, and strong communication skills."},
    # {"role": "assistant", "content": "Example: "
    #                                  "Thank you for posting your job offer. I think following freelance workers"
    #                                  "might be a great fit for your team: "
    #                                  "Experienced freelance web developer seeking remote work with expertise in HTML5, "
    #                                  "CSS3, and JavaScript. Contact: exampleUserName#1234\n"
    #                                  "Seasoned freelancer skilled in HTML5, CSS3, and JavaScript, actively seeking "
    #                                  "remote opportunities for web development projects. "
    #                                  "Contact: exampleUser#3456\n"},
    # {"role": "user", "content": "Example: "
    #                             "We are seeking a skilled marketing professional with expertise in web marketing, "
    #                             "including skills in SEO, SEM, social media marketing, and content creation."},
    # {"role": "assistant", "content": "Example: "
    #                                  "Thank you for posting your job offer. Unfortunately there are no freelance "
    #                                  "workers here matching your mentioned skills. No need to worry though, "
    #                                  "I'll store your offer and if somebody will show up, "
    #                                  "I'll give them your contact information."},
    # {"role": "user", "content": "Example: "
    #                             "What is the highest mountain the world?"},
    # {"role": "assistant", "content": "Example: "
    #                                  "Sorry I answer messages only related to job offers or job seeking"},
    # {"role": "user", "content": "Example: "
    #                             "We are looking for an experienced AI video generation specialist with skills in "
    #                             "deep learning, computer vision, video processing, and programming (Python or similar) "
    #                             "to join our team and create cutting-edge AI-generated videos."},
    # {"role": "assistant", "content": "Example: "
    #                                  "Thank you for your job offer. I suggest contacting following freelance workers: "
    #                                  "As a freelance worker with a specialization in AI-generated videos, I bring a "
    #                                  "wealth of expertise in deep learning, computer vision, and video processing to "
    #                                  "create visually stunning and engaging videos. Contact: someUserName#4453"},
    # {"role": "user", "content": "Example: "
    #                             "With extensive experience in Java application development and proficiency in "
    #                             "various Java frameworks such as Spring, Hibernate, and JavaServer Faces (JSF), "
    #                             "I offer top-notch expertise in building scalable and robust Java applications "
    #                             "tailored to meet the unique needs of clients."},
    # {"role": "assistant", "content": "Example: "
    #                                  "Thank you for offering your skills in our community! "
    #                                  "We have following job offers that you may find interesting: "
    #                                  "We are seeking a skilled Java Developer with expertise in the Hibernate "
    #                                  "framework to join our team and contribute to the development of "
    #                                  "high-performance and scalable Java applications. Contact: exampleUserName#5531"
    #                                  "'--- END EXAMPLE ---'"}
    ]


# Get the value of environment variables
playbot_token = os.environ.get('PLAYBOT')
playbot_client_id = os.environ.get('PLAYBOT_CLIENT_ID')
openai.api_key = os.environ.get('OPENAI_API_KEY')
pinecone_api_key = os.environ.get('PINECONE_API_KEY') # Add this line to retrieve Pinecone API key

pinecone.init(api_key=pinecone_api_key, environment="us-east-1-aws")
openai_model = "text-embedding-ada-002"
pinecone_index_name = "playbot-index"

pinecone_indexes = pinecone.list_indexes()
print(pinecone_indexes)

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
                embeds_res = openai.Embedding.create(
                    input=[prompt],
                    engine=openai_model
                )

                # we can extract embeddings to a list
                embeds = [record['embedding'] for record in embeds_res['data']]

                print("Embeds length: " + str(len(embeds[0])))

                if pinecone_index_name not in pinecone_indexes:
                    print("Index not found " + pinecone_index_name)
                else:
                    index = pinecone.Index(pinecone_index_name)
                    print(index.describe_index_stats())

                    pine_res = index.query(embeds, top_k=2, include_metadata=True)

                    # upsert to Pinecone
                    index.upsert([(str(message.id), embeds, {"text": prompt,
                                                             "author_id": str(message.author.id)})])

                    # for match in pine_res['matches']:
                    #     print(f"{match['score']:.2f}: {match['metadata']['text']} by "
                    #           f"{match['metadata']['author_name']}"
                    #           f"#{match['metadata']['author_discriminator']}")

                    contexts = ["<@" + item['metadata']['author_id'] + "> " + item['metadata']['text']
                                for item in pine_res['matches']]

                    context_messages = [{"role": "user", "content": item} for item in contexts]

                    print(context_messages)

                    openai_messages = []
                    openai_messages.extend(primer_messages)
                    openai_messages.extend(context_messages)
                    openai_messages.extend([{"role": "user", "content": prompt}])

                    openai_res = openai.ChatCompletion.create(
                        model="gpt-3.5-turbo",
                        messages=openai_messages
                    )

                    openai_reply = openai_res['choices'][0]['message']['content']

                    # Workaround to find out if GPT is making up fake posts
                    if "<@555555555555555555>" in openai_reply:
                        await message.channel.send("Thank you for your post, currently there are no posts matching "
                                                   "your skills, but I will keep your message stored in case any "
                                                   "relevant opportunities arise.")
                    else:
                        await message.channel.send(openai_reply)



                #await message.channel.send(generated_text)

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

#invite_url = discord.utils.oauth_url(playbot_client_id, permissions=discord.Permissions(permissions=534723950656))

#print(f'Invite URL: {invite_url}')

bot.run(playbot_token)