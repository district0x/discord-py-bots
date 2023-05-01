from dotenv import load_dotenv
import os
import sys
from interactions import Client, Intents, slash_command, slash_option, SlashContext, OptionType, ActionRow, Button, ButtonStyle, Task, IntervalTrigger
from interactions.models.discord import Embed
import discord
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
import re
import time
import threading
import asyncio

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
bitly_api_key = os.getenv('BITLY_API_KEY')
commit_checking_interval = int(os.getenv('COMMIT_CHECKING_INTERVAL'))

contract_addresses = { # Make sure addresses are checksum format
    "mainnet": {
        "ETHRegistrarController": "0x253553366da8546fc250f225fe3d25d0c782303b"
    },
    "goerli": {
        "ETHRegistrarController": "0xCc5e7dB10E65EED1BBD105359e7268aa660f6734",
        "PublicResolver": "0x19c2d5D0f035563344dBB7bE5fD09c8dad62b001"
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


def hexlify(name):
    return binascii.hexlify(name).decode('utf-8')


def get_abi(contract_name):
    with open(f"abi/{contract_name}.abi", 'r') as f:
        return json.load(f)


def get_contract_address(contract_name):
    return contract_addresses[web3_network][contract_name]


def add_eth_suffix(ens_name):
    if not ens_name.endswith(".eth"):
        ens_name += ".eth"
    return ens_name


def remove_eth_suffix(s: str) -> str:
    if s.endswith(".eth"):
        return s[:-4]
    else:
        return s


def is_valid_ethereum_address(address):
    # Check that the address starts with '0x'
    if not re.match(r"^0x[a-fA-F0-9]{40}$", address):
        return False

    return True


def get_tx_page_url(tx_data):
    return f"{tx_page_host}?to={tx_data['to']}&data={tx_data['data']}&value={tx_data['value']}"


web3 = Web3(Web3.HTTPProvider(infura_url))
eth_registrar = web3.eth.contract(address=get_contract_address("ETHRegistrarController"),
                                  abi=get_abi("ETHRegistrarController"))


async def start_commit_checking_interval(
        interval_start,
        commitment,
        name_label,
        eth_address,
        register_duration,
        salt_bytes,
        ctx):
    while True:

        # Check if 24 hours have passed since interval_start
        now = datetime.datetime.now()
        time_passed = now - interval_start
        if time_passed >= datetime.timedelta(hours=24):
            logger.info("Stopping interval after 24 hours")
            break

        commitment_timestamp = eth_registrar.functions.commitments(commitment).call()
        logger.info(f"Commitment Timestamp...{commitment_timestamp}")

        if commitment_timestamp > 0:
            # Wait until commit period ends
            await asyncio.sleep(60)

            # Add 10% to account for price fluctuation; the difference is refunded.
            rent_price_wei = eth_registrar.functions.rentPrice(name_label, register_duration).call()[0]
            rent_price_eth = web3.from_wei(rent_price_wei, "ether")

            logger.info(f"rent price: {rent_price_eth}")
            logger.info(f"name_label: {name_label}")
            logger.info(f"eth_address: {eth_address}")
            logger.info(f"register_duration: {register_duration}")
            logger.info(f"salt_bytes: {hexlify(salt_bytes)}")
            logger.info(f"resolver: {get_contract_address('PublicResolver')}")

            tx_data = eth_registrar.functions.register(
                name_label,
                eth_address,
                register_duration,
                salt_bytes,
                get_contract_address("PublicResolver"),
                [],
                False,
                15
            ).build_transaction({"value": rent_price_wei})

            logger.info(tx_data)

            tx_url = get_tx_page_url(tx_data)

            embed = Embed(
                title="Finish Registration",
                description=f"Click this link to finish registration process for {add_eth_suffix(name_label)}",
                url=tx_url
            )

            await ctx.send(f"Great! Now you're ready to finish your registration of {add_eth_suffix(name_label)}. "
                           f"The cost is {rent_price_eth} ETH.", embeds=embed)
            break

        await asyncio.sleep(commit_checking_interval)



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
@slash_option(
    name="eth_address",
    description="Please provide the Ethereum address you wish to register an ENS name with.",
    required=True,
    opt_type=OptionType.STRING,
    max_length=42,
    min_length=42
)
async def register(ctx: SlashContext, ens_name, eth_address):
    register_duration = 31536000
    logger.info(f"register {ens_name}")
    try:
        ens_name = add_eth_suffix(ens_name)
        cured_name = ens_cure(ens_name)
        name_label = remove_eth_suffix(cured_name)

        if not is_valid_ethereum_address(eth_address):
            await ctx.send(f"It appears that the Ethereum address you provided is not valid.")
            return

        is_available = eth_registrar.functions.available(name_label).call()

        logger.info(f"available: {is_available}")

        if not is_available:
            await ctx.send(f"I apologize, but the name `{cured_name}` is not available for registration.")
            return

        hashed_name = namehash(cured_name)
        hashed_label = remove_eth_suffix(cured_name)

        salt = os.urandom(32).hex()
        salt_bytes = bytes.fromhex(salt)

        logger.info(f"label: {name_label}")
        logger.info(f"eth_address: {eth_address}")
        logger.info(f"register_duration: {register_duration}")
        logger.info(f"salt_bytes: {salt_bytes}")
        logger.info(f"address: {get_contract_address('PublicResolver')}")

        commitment = eth_registrar.functions.makeCommitment(
            name_label,
            eth_address,
            register_duration,
            salt_bytes,
            get_contract_address("PublicResolver"),
            [],
            False,
            15
        ).call()

        logger.info(f"commitment: {commitment}")

        tx_data = eth_registrar.functions.commit(commitment).build_transaction()

        tx_url = get_tx_page_url(tx_data)

        embed = Embed(
            title="Start Registration",
            description=f"Click this link to start registration process for {cured_name}",
            url=tx_url
        )

        await ctx.send(f"You're about to register `{cured_name}`!", embeds=embed)
        await start_commit_checking_interval(
            commitment=commitment,
            interval_start=datetime.datetime.now(),
            ctx=ctx,
            name_label=name_label,
            eth_address=eth_address,
            register_duration=register_duration,
            salt_bytes=salt_bytes
        )
    except DisallowedNameError as e:
        await ctx.send(f"I apologize, but the name {ens_name} cannot be accepted for registration.")

bot.start(namebazaarGPT_token)
