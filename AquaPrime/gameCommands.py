#gamecommands.py

import random
from datetime import datetime
import asyncio
import discord
from discord.ext import commands


class CommandsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='attack', brief="Rolls for an attack with a d20 and modifier")
    @commands.cooldown(1, 86400, commands.BucketType.user)  # 24-hour cooldown
    async def attack(self, ctx, user: discord.Member = None):
        await self.perform_attack(ctx, user)

    async def perform_attack(self, ctx, user: discord.Member = None):
        print("\033[31mPerforming attack...\033[0m")
        roll = random.randint(1, 20)
        total = roll

        member = ctx.guild.get_member(ctx.author.id)
        if any(role.id == 1081109959292497928 for role in member.roles):
            roll2 = random.randint(1, 20)
            total += roll2
            output = f"**{roll}** :game_die: + **{roll2}** :game_die: = **{total}** :crossed_swords:"
        else:
            output = f"**{roll}** :game_die: = **{total}** :crossed_swords:"

        target_user_mention = f"is attacking {user.mention}" if user else "is attacking"
        embed = discord.Embed(colour=0x00b0f4, timestamp=datetime.now())
        embed.set_author(name="Attack Roll", icon_url="https://images-ext-1.discordapp.net/external/AkSGsZL11_KdXNhA2QqQs3OusLy8-_u65pmdhYZ3mzU/https/images.emojiterra.com/google/android-12l/512px/2694.png")
        embed.add_field(
            name="", value=f"{ctx.author.mention} {target_user_mention}", inline=False)
        embed.add_field(
            name="`  🎲  `", value=f"`{roll} ⚔`", inline=True)
        if any(role.id == 1081109959292497928 for role in member.roles):
            embed.add_field(
                name="`  🎲  `", value=f"`{roll2} ⚔`", inline=True)
        embed.add_field(name="`Total 💥`", value=f"{total} ⚔", inline=False)
        embed.set_thumbnail(
            url="https://thumbs.gfycat.com/CompleteCornyGalago-max-1mb.gif")
        embed.set_footer(
            text="Aqua Prime", icon_url="https://media.discordapp.net/attachments/1094443050098511922/1142958547353731104/ezgif-5-15676eab6f.gif")

        await ctx.send(embed=embed)

    @commands.command(name='shoot', brief="Shoots a user with a gun")
    async def shoot(self, ctx, user: discord.Member):
        if user.id == self.bot.user.id:
            await ctx.send("Nice try. I can't be killed. I'm a cat with 9 lives, and I'm a meme. Not to mention I somehow handle gun fire in the game so I'm not even gonna bother with that.")
            return

        # Check if the target user is the boss
        boss_role = discord.utils.get(ctx.guild.roles, name='Boss')
        if boss_role in user.roles:
            await ctx.send("You can't shoot the boss, they're too powerful!")
            return

        print("\033[34mCommand executed\033[0m")

        # Check if the user has the Special Role or ID 🔫
        member = ctx.guild.get_member(ctx.author.id)
        if any(role.id in [1076926977518346412, 1081417524043857943] for role in member.roles):

            role_to_remove1 = discord.utils.get(
                ctx.guild.roles, id=1059989387875729438)
            role_to_remove2 = discord.utils.get(
                ctx.guild.roles, id=1076926977518346412)
            role_to_add = discord.utils.get(
                ctx.guild.roles, id=1075838775307030598)

            await asyncio.sleep(10)  # Add a 10-second delay
            await user.remove_roles(role_to_remove1, role_to_remove2)
            await member.remove_roles(role_to_remove2)
            await user.add_roles(role_to_add)
            print("\033[34mRole added\033[0m")
            await ctx.send(f"{ctx.author.mention} just shot and killed {user.mention} 💥🔫. But... their lame little 3D printed gun broke in the process.")

        else:
            await ctx.send("You need to buy a gun first. 🔫")

    @commands.command(name='res', brief="Adds a role to a user")
    async def res(self, ctx, user: discord.Member):
        command_user = ctx.message.author
        if any(role.id in [1080938165625442314] for role in command_user.roles):
            command_user_role = discord.utils.get(
                ctx.guild.roles, id=1080938165625442314)
            target_user_role = discord.utils.get(
                ctx.guild.roles, id=1075838775307030598)
            new_role = discord.utils.get(
                ctx.guild.roles, id=1059989387875729438)

            await command_user.remove_roles(command_user_role)
            await user.remove_roles(target_user_role)
            await user.add_roles(new_role)
            await ctx.send(f"{ctx.author.mention} just resurrected {user.mention}")

        else:
            await ctx.send("You don't have the permission to use this command.")

    @commands.command(name='dice', brief="Rolls two six-sided dice")
    async def roll(self, ctx):
        roll1 = random.randint(1, 6)
        roll2 = random.randint(1, 6)
        total = roll1 + roll2

        output = f"**{roll1}** :game_die:   **{roll2}** :game_die:   =   **{total}** :tada:"
        embed = discord.Embed(title="Dice Roll", color=discord.Color.blue())
        embed.add_field(name="Results", value=output, inline=False)
        embed.description = f"{ctx.author.mention} rolled the dice! 🎲"
        embed.set_thumbnail(
            url="https://thumbs.gfycat.com/CompleteCornyGalago-max-1mb.gif")
        await ctx.send(embed=embed)

    @commands.command(name='spell', brief="Casts a random spell from the spell book")
    async def spell(self, ctx):
        spell_book = discord.utils.get(ctx.guild.roles, name='Spell Book')
        if spell_book not in ctx.message.author.roles:
            await ctx.send("You need to buy the Spell Book from the store first!")
            return

        user_id = ctx.message.author.id
        current_time = datetime.datetime.now()
        if user_id in last_execution:
            lasttime = last_execution[user_id]
            difference = current_time - lasttime
            if difference.days < 1:
                await ctx.send(f"This command is on cooldown. Please try again in {1 - difference.days} days.")
                return

        last_execution[user_id] = current_time
        result = random.randint(1, len(spells.effects))
        emoji = '🎲'
        effect = spells.effects.get(result, "No effect.")
        if result == 1:
            role = discord.utils.get(ctx.guild.roles, name='🐸')
            original_nick = ctx.author.display_name
            await ctx.author.edit(nick=original_nick + ' 🐸')
            await ctx.author.add_roles(role)
            await ctx.author.edit(mute=True)
            await asyncio.sleep(28800)
            await ctx.author.edit(mute=False)
            await ctx.author.remove_roles(role)
            await ctx.send(f"{ctx.author.mention} cast a spell! You've been turned into a 🐸 for 8 hours! Enjoy!")
        else:
            await ctx.send(f"{ctx.author.mention} cast a spell! {effect} {emoji}")


@commands.Cog.listener()
async def on_command_error(self, ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        # Convert the cooldown time from seconds to hours and minutes
        hours = int(error.retry_after // 3600)
        minutes = int((error.retry_after % 3600) // 60)

        # Construct the cooldown message
        if hours > 0:
            cooldown_msg = f"You're on cooldown! Please wait {hours} hour(s) and {minutes} minute(s) before using this command again."
        else:
            cooldown_msg = f"You're on cooldown! Please wait {minutes} minute(s) before using this command again."

        await ctx.send(cooldown_msg)
        return  # This will suppress the default cooldown message
    else:
        print(f"\033[34mError occurred: {error}\033[0m")


def setup(bot):
    bot.add_cog(CommandsCog(bot))
    print("Commands cog is ready.")
