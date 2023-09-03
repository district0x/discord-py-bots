def replace_with_emojis(prompt):
    emoji_dict = {
        'TTRPG': '🎲',
        'Discord': '💬',
        'cryptocurrency': '💰',
        'satirical': '🤪',
        'fiat currency': '💸',
        'oil and gas': '🛢️',
        'macro': '📈',
        'micro': '📉',
        'AI bots': '🤖',
        'virtual existence': '🌐',
        'cultural satire': '🎭'
        # Add more replacements as needed
    }
    
    for word, emoji in emoji_dict.items():
        prompt = prompt.replace(word, emoji)
    
    return prompt

# Your original prompt
original_prompt = "I'm the creator of Aqua Prime, a TTRPG inspired Discord game..."

# Replace words with emojis
emoji_prompt = replace_with_emojis(original_prompt)

# Print the updated prompt
print(emoji_prompt)
