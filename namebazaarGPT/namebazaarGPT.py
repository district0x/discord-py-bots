from dotenv import load_dotenv
import os
import sys
from interactions import Client, Intents, slash_command, slash_option, SlashContext, OptionType, ActionRow, Button, ButtonStyle
import openai
import pinecone
import time
import datetime
import logging
import json
from web3 import Web3
from ens_normalize import ens_cure, DisallowedNameError
import binascii
from namehash import namehash

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("namebazaarGPT")

namebazaarGPT_token = os.getenv('NAMEBAZAAR_GPT_TOKEN')
namebazaarGPT_client_id = os.getenv('NAMEBAZAAR_GPT_CLIENT_ID')
openai.api_key = os.getenv('OPENAI_API_KEY')
pinecone_api_key = os.getenv('PINECONE_API_KEY')
max_uses_per_day = os.getenv('MAX_USES_PER_DAY')
admin_user_id = os.getenv('ADMIN_USER_ID')
infura_url = os.getenv('INFURA_URL')
web3_network = os.getenv('WEB3_NETWORK')
tx_page_host = os.getenv('TX_PAGE_HOST')

contract_addresses = {
    "mainnet": {
        "ETHRegistrarController": "0x253553366Da8546fC250F225fe3d25d0C782303b"
    },
    "goerli": {
        "ETHRegistrarController": "0xCc5e7dB10E65EED1BBD105359e7268aa660f6734"
    }
}

pinecone.init(api_key=pinecone_api_key, environment="northamerica-northeast1-gcp")
openai_embed_model = "text-embedding-ada-002"
pinecone_index_name = "namebazaar-gpt"

pinecone_indexes = pinecone.list_indexes()
logger.info(f"Pinecone indexes: {pinecone_indexes}")

intents = Intents.DEFAULT
intents.messages = True
intents.guilds = True
intents.message_content = True

guild_id = 356854079022039062

bot = Client(intents=intents)

with open('abi/ETHRegistrarController.abi', 'r') as f:
    eth_registrar_abi = json.load(f)

def get_contract_address(contract_name):
    return contract_addresses[web3_network][contract_name]

web3 = Web3(Web3.HTTPProvider(infura_url))
eth_registrar = web3.eth.contract(address=get_contract_address("ETHRegistrarController"),
                                  abi=eth_registrar_abi)


def add_eth_suffix(ens_name):
    if not ens_name.endswith(".eth"):
        ens_name += ".eth"
    return ens_name


def remove_eth_suffix(s: str) -> str:
    if s.endswith(".eth"):
        return s[:-4]
    else:
        return s


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user.name}")


@slash_command(name="buy", description="My first buy command :)")
async def buy(ctx: SlashContext):
    await ctx.send("You have just bought ENS name!")


@slash_command(name="register", description="Registers ENS name")
@slash_option(
    name="ens_name",
    description="Please provide the ENS name that you wish to register.",
    required=True,
    opt_type=OptionType.STRING,
    max_length=100,
    min_length=3
)
async def register(ctx: SlashContext, ens_name):
    logger.info(f"register {ens_name}")
    try:
        logger.info(f"Before suffix: {binascii.hexlify(namehash(ens_name)).decode('utf-8')}")
        ens_name = add_eth_suffix(ens_name)
        cured_name = ens_cure(ens_name)

        is_available = eth_registrar.functions.available(remove_eth_suffix(cured_name)).call()

        logger.info(f"available: {is_available}")

        if not is_available:
            await ctx.send(f"I apologize, but the name `{ens_name}` is not available for registration.")
            return

        hashed_name = namehash(cured_name)
        hashed_label = remove_eth_suffix(cured_name)

        tx_data = eth_registrar.functions.commit(namehash(hashed_label)).build_transaction()

        tx_url = f"{tx_page_host}?to={tx_data['to']}&data={tx_data['data']}"

        components = Button(
            style=ButtonStyle.URL,
            label="Start Registration",
            url=tx_url
        )

        hex_str = binascii.hexlify(hashed_name).decode('utf-8')

        logger.info(cured_name)
        logger.info(f"0x{hex_str}")

        await ctx.send(f"You're about to register `{cured_name}`!", components=components)
    except DisallowedNameError as e:
        await ctx.send(f"I apologize, but the name {ens_name} cannot be accepted for registration.")



bot.start(namebazaarGPT_token)
