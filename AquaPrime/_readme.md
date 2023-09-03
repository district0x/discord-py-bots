# Aqua Prime Grumpy Cat AI Documentation

## Overview

The Aqua Prime Grumpy Cat AI is a component of the Aqua Prime game—a Discord-based Tabletop Role-Playing Game (TTRPG) that combines economic strategy, education about cryptocurrency, and interactive storytelling. The Grumpy Cat AI serves as the game's Dungeon Master, providing witty and humorous responses in the character of Grumpy Cat to players' interactions and inquiries. The AI utilizes OpenAI's GPT-3.5 engine to generate contextually relevant and engaging responses.

# Purpose

The Grumpy Cat AI enhances players' immersion within the Aqua Prime universe by delivering responses that align with the in-game narrative and player interactions. The AI takes on the persona of Grumpy Cat, a popular internet meme, and maintains character throughout interactions, contributing to the satirical and entertaining nature of the game.

# Key Features

Contextual Responses: The AI leverages past player messages and interactions to build context. It includes both recent in-game conversations (RAM) and long-term history (HDD) of player interactions to provide more personalized and relevant responses.

Dynamic Prompts: The AI constructs prompts for the OpenAI GPT-3.5 engine that include:

## Operating System (OS) Section: A static game world setting description

### Hard Disk Drive (HDD) Section: Historical information about the player and related users

### Random Access Memory (RAM) Section: Recent in-game conversation messages

### System Section: Grumpy Cat's character and role description

### User Input Section: The current user's input message

### Mentioned Users Section: Any mentioned users in the input message

### Collaborative Storytelling: The AI facilitates collaborative storytelling within the Aqua Prime universe, driving engaging role-playing interactions between players and NPCs

## Usage

Players interact with the Grumpy Cat AI through Discord messages. When the AI is mentioned in a message, it processes the message's context, retrieves historical data from a MongoDB database, searches for additional context in Weaviate, and constructs a prompt for the OpenAI engine. The AI generates a response based on the prompt and delivers it back to the Discord channel.

## Components

### WeaviateClient: A class that interfaces with Weaviate, an external data source, to retrieve context relevant to player interactions

### OpenAI: A class that interacts with the OpenAI GPT-3.5 engine to generate responses based on prompts

### Bot Framework: The Discord bot framework handles interactions with the Grumpy Cat AI, retrieves historical messages, constructs prompts, and delivers AI-generated responses to the Discord channel

# Implementation

The Grumpy Cat AI is integrated with the Aqua Prime Discord bot using Python. The codebase consists of classes for interfacing with external data sources, creating prompts, and generating AI responses. The AI maintains Grumpy Cat's character by using the same tone, language, and humor expected from the meme.

# Conclusion

The Aqua Prime Grumpy Cat AI enhances the immersive experience of the Aqua Prime game by providing contextually relevant and entertaining responses. By taking on the role of the iconic Grumpy Cat, the AI adds a layer of humor and engagement to player interactions, contributing to the unique and engaging gameplay of Aqua Prime.

# Commands

### Dice Rolling feature (Roll Table)

 Discord Dice rolling bot that scales the dice to the size of the library items in 'effects', will also allow /shoot commands, /res commands to ressurect a player that was shot
 If you roll a one with !roll it will change the user name to 'Frog', Give them the role ''@🐸'', and time them out for 8 hours. (Other functions to come)

 Discord Commands Module Documentation
Overview
The Discord Commands Module provides various commands for players within the Aqua Prime game—a Discord-based Tabletop Role-Playing Game (TTRPG). These commands enable players to engage in various in-game actions, from attacking to casting spells, adding depth and interactivity to the gameplay experience.

Purpose
The purpose of this module is to enhance player engagement by offering a range of interactive commands that align with the Aqua Prime game's narrative and mechanics. Players can execute commands to perform in-game actions, such as attacking, shooting, rolling dice, and casting spells, contributing to collaborative storytelling and entertainment.

Key Features
Attack Command (!attack): Allows players to roll a twenty-sided die (d20) and calculate the attack total by adding a specified modifier. Players are then presented with the roll result, modifier, and total value.

Shoot Command (!shoot): Enables players to "shoot" a targeted user with a fictional gun. If specific conditions are met, the target user's role is modified, resulting in a humorous response.

Resurrection Command (!res): Grants players with a special role the ability to "resurrect" another user by modifying their roles. This command introduces a strategic aspect to the game.

Dice Roll Command (!dice): Allows players to roll two six-sided dice (2d6) and calculates the total of the rolls. The command then displays the individual rolls and the total value.

Spell Cast Command (!spell): Enables players to cast a random spell from a spell book, which has various effects on the player or the environment. Each spell is associated with a unique outcome.

Usage
Players within the Aqua Prime Discord server can utilize the provided commands by entering them in the chat. Each command is prefixed with ! to distinguish it as a command. Players can engage in diverse interactions and actions using these commands, contributing to the overall gameplay experience.

Components
Attack Command (!attack): Rolls a d20, calculates the total with a specified modifier, and provides the player with a roll result, modifier, and total value.

Shoot Command (!shoot): Simulates a user shooting another user, applying role modifications if specific conditions are met.

Resurrection Command (!res): Allows players with a special role to resurrect another user by modifying roles.

Dice Roll Command (!dice): Rolls 2d6 and calculates the total, displaying both individual roll results and the total.

Spell Cast Command (!spell): Enables players to cast a random spell with various effects, adding an element of unpredictability to the game.

Implementation
The Discord Commands Module is implemented using the Discord.py library in Python. Each command is defined as a function within the module and is prefixed with the command prefix !. The module handles interactions, calculations, role modifications, and responses, enhancing the interactive gameplay experience within the Aqua Prime game.

Conclusion
The Discord Commands Module enriches the Aqua Prime gameplay by providing players with an array of interactive commands that align with the game's narrative and mechanics. By offering a variety of actions, from attacking to casting spells, the module contributes to collaborative storytelling, engagement, and entertainment within the Aqua Prime TTRPG universe.
