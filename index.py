import discord
from discord import app_commands
import requests
import json
import os
from discord.ext import tasks
from dotenv import load_dotenv

# Load sensitive data from .env file (store your keys in this file)
load_dotenv()

# Your Riot API Key and region
RIOT_API_KEY = os.getenv('RIOT_API_KEY')  # Store the API key in a .env file
REGION = 'euw1'  # Replace with your region (e.g., 'na1', 'euw1')

# Discord bot token
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')  # Store the bot token in .env

# Define the file where we'll store the summoners
DATA_FILE = 'summoners.json'
CHANNEL_FILE = 'channel_config.json'  

ranks_en = [
    "IRON IV", "IRON III", "IRON II", "IRON I",
    "BRONZE IV", "BRONZE III", "BRONZE II", "BRONZE I",
    "SILVER IV", "SILVER III", "SILVER II", "SILVER I",
    "GOLD IV", "GOLD III", "GOLD II", "GOLD I",
    "PLATINUM IV", "PLATINUM III", "PLATINUM II", "PLATINUM I",
    "DIAMOND IV", "DIAMOND III", "DIAMOND II", "DIAMOND I",
    "MASTER I", "GRANDMASTER I", "CHALLANGER I"
]

class LP(int):
    def __new__(cls, value):
        # Erzeugen einer neuen Instanz von LP basierend auf einem Integer-Wert
        return super(LP, cls).__new__(cls, value)

    def ToRank(self):
        # Division durch 100, um den Rang zu erhalten
        rank_index = self // 100
        if rank_index >= len(ranks_en):
            rank_index = len(ranks_en) - 1  # Maximaler Rang ist "Challenger"
        # Modulo 100, um die verbleibenden LP zu erhalten
        remaining_lp = self % 100
        return f"{ranks_en[rank_index]} {remaining_lp} LP"

    @staticmethod
    def from_rank(rank_lp_str):
        # Aufteilen des Strings in Rang und LP
        try:
            rank, tier, lp_str, lp = rank_lp_str.split(' ', 3)
            print(rank, tier, lp_str, lp)
            lp = int(lp_str)
            if f"{rank} {tier}" in ranks_en:
                rank_index = ranks_en.index(f"{rank} {tier}" )
                total_lp = rank_index * 100 + lp
                return LP(total_lp)
            else:
                raise ValueError("Invalid Rank")
        except ValueError:
            raise ValueError("Invalid Input Format")

# Function to read summoners from file
def load_summoners():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as file:
            try:
                content = file.read().strip()
                if content == "":
                    return {}
                return json.loads(content)
            except json.JSONDecodeError:
                return {}
    return {}

# Function to save summoners to file
def save_summoners(summoners):
    with open(DATA_FILE, 'w') as file:
        json.dump(summoners, file)

# Function to save the channel ID to a file
def save_channel_id(channel_id):
    with open(CHANNEL_FILE, 'w') as file:
        json.dump({"channel_id": channel_id}, file)

# Function to load the channel ID from the file
def load_channel_id():
    if os.path.exists(CHANNEL_FILE):
        with open(CHANNEL_FILE, 'r') as file:
            data = json.load(file)
            return data.get("channel_id")
    return None

# Create a subclass of discord.Client and add the command tree
class MyBot(discord.Client):
    def __init__(self, intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
    
    async def on_ready(self):
        print(f'Bot is ready! Logged in as {self.user}')
        # Sync commands with Discord (registers them with the API)
        await self.tree.sync()
        print("Commands synced.") 
        await check_lp()

# Initialize bot and summoners
intents = discord.Intents.default()
intents.message_content = True
bot = MyBot(intents=intents)

# Load summoners from the file
summoners = load_summoners()

# Step 1: Get the PUUID using Riot ID (gameName and tagLine)
def get_puuid(game_name, tag_line):
    riot_account_url = f'https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}?api_key={RIOT_API_KEY}'
    response = requests.get(riot_account_url)
    
    if response.status_code != 200:
        print(f"Error fetching Riot ID: {response.status_code}")
        return None
    
    account_data = response.json()
    return account_data['puuid']

# Step 2: Get the encrypted summoner ID using the PUUID
def get_encrypted_summoner_id(puuid):
    summoner_url = f'https://{REGION}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}?api_key={RIOT_API_KEY}'
    response = requests.get(summoner_url)

    if response.status_code != 200:
        print(f"Error fetching summoner by PUUID: {response.status_code}")
        return None

    summoner_data = response.json()
    return summoner_data['id']  # This is the encrypted summoner ID

# Step 3: Get ranked data using the encrypted summoner ID
def get_rank_data(encrypted_summoner_id):
    rank_url = f'https://{REGION}.api.riotgames.com/lol/league/v4/entries/by-summoner/{encrypted_summoner_id}?api_key={RIOT_API_KEY}'
    rank_response = requests.get(rank_url)

    if rank_response.status_code != 200:
        print(f"Error fetching rank data: {rank_response.status_code}")
        return None

    rank_data = rank_response.json()

    # Look for ranked solo/duo queue data
    for queue in rank_data:
        if queue['queueType'] == 'RANKED_SOLO_5x5':
            return queue
    return None

# Command to add a summoner to the tracking list
@bot.tree.command(name="add_summoner", description="Add a summoner to the tracking list using Riot ID.")
async def add_summoner(interaction: discord.Interaction, game_name: str, tag_line: str):
    # Step 1: Get the PUUID
    puuid = get_puuid(game_name, tag_line)
    
    if not puuid:
        await interaction.response.send_message(f"Failed to find the Riot ID for {game_name}#{tag_line}.")
        return

    # Step 2: Get the encrypted summoner ID
    encrypted_summoner_id = get_encrypted_summoner_id(puuid)
    
    if not encrypted_summoner_id:
        await interaction.response.send_message(f"Failed to find summoner for PUUID: {puuid}.")
        return
    
    # Add the summoner to the tracking list
    summoners[game_name] = {'encrypted_summoner_id': encrypted_summoner_id, 'last_lp': None, 'rank': None}
    save_summoners(summoners)
    await interaction.response.send_message(f'{game_name}#{tag_line} added to the list.')

# Command to remove a summoner from the tracking list
@bot.tree.command(name="remove_summoner", description="Remove a summoner from the tracking list.")
async def remove_summoner(interaction: discord.Interaction, summoner_name: str):
    if summoner_name in summoners:
        del summoners[summoner_name]
        save_summoners(summoners)
        await interaction.response.send_message(f'{summoner_name} removed from the list.')
    else:
        await interaction.response.send_message(f'{summoner_name} is not in the list.')

@bot.tree.command(name="set_channel", description="Set the channel for LP updates to the current channel.")
async def set_channel(interaction: discord.Interaction):
    channel = interaction.channel  # Get the channel where the command is invoked
    save_channel_id(channel.id)  # Save the channel ID to a file
    print(f"Channel ID {channel.id} set for LP updates.")  # Debug print
    await interaction.response.send_message(f"Channel set to {channel.name} for LP updates.")

# Function to check LP gain/loss and send a message to the channel
async def check_lp():
    channel_id = load_channel_id()
    if not channel_id:
        print("No channel has been set for updates.")
        return

    channel = await bot.fetch_channel(channel_id)  # Use loaded channel_id
    if not channel:
        print("Channel not found")
        return
    
    for summoner_name, data in summoners.items():
        encrypted_summoner_id = data['encrypted_summoner_id']
        rank_data = get_rank_data(encrypted_summoner_id)
        print(rank_data)
        if rank_data:
            current_lp = rank_data['leaguePoints']
            tier = rank_data['tier']
            rank = rank_data['rank']
            wins = rank_data["wins"]
            losses = rank_data["losses"]

            # Get previous rank information
            previous_rank_info = summoners[summoner_name].get('rank', None)
            previous_tier = previous_rank_info.split()[0] if previous_rank_info else None
            previous_rank = previous_rank_info.split()[1] if previous_rank_info else None

            # First time we encounter this summoner
            if summoners[summoner_name]['last_lp'] is None:
                summoners[summoner_name]['last_lp'] = current_lp
                summoners[summoner_name]['rank'] = f'{tier} {rank}'
                lp_message = "This is the first record for this summoner."
            else:
                last_lp = summoners[summoner_name]['last_lp']
                # Update the summoner's last LP and current rank
                summoners[summoner_name]['last_lp'] = current_lp
                summoners[summoner_name]['rank'] = f'{tier} {rank}'

                # Prepare the LP gain message
                lp_gain = 0
                #print(f"{previous_tier} {previous_rank} {last_lp} LP")
                #print(f"{tier} {rank} {current_lp} LP")

                lp_from_rank = LP.from_rank(f"{tier} {rank} {current_lp} LP")
                lp_from_past_rank = LP.from_rank(f"{previous_tier} {previous_rank} {last_lp} LP")
                lp_gain = lp_from_rank - lp_from_past_rank

            if lp_gain >= 0:
                lp_message = f"Gained {lp_gain} LP Today."
            else:
                lp_message = f"Lost {lp_gain} LP Today."
            if previous_rank is not rank or previous_tier is not tier:
                lp_message += f"Rank changed from {previous_tier} {previous_rank} to {tier} {rank}"
            # Add the current LP message
            lp_message += f' Current LP: {current_lp}.'

            # Send the message to the Discord channel
            embed = discord.Embed(
                title=f'{summoner_name}\'s LP Update',
                description=(
                    f'{summoner_name} has {lp_message}\n'
                    f'Winrate: {round(((wins / (losses + wins)) * 100), 2)}%'
                ),
                color=discord.Color.blue()
            )

            # Path to the rank icon
            rank_icon_path = f'rank_images/{tier.lower()}.png'
            
            try:
                with open(rank_icon_path, 'rb') as f:
                    file = discord.File(f, filename=f'{tier.lower()}.png')  # Create the file object
                    embed.set_thumbnail(url=f'attachment://{tier.lower()}.png')  # Set the thumbnail to the attachment
                    await channel.send(embed=embed, files=[file])  
            except FileNotFoundError:
                print(f"Rank image for {tier.lower()} not found.")
                await channel.send(embed=embed)  # Send embed without image if the file is not found

    save_summoners(summoners)


# Schedule task to check at the start of the day
@tasks.loop(hours=24)
async def daily_lp_check():
    await check_lp()

# Start the bot
bot.run(DISCORD_BOT_TOKEN)
