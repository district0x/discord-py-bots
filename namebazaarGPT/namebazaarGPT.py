import asyncio
import binascii
import datetime
import json
import logging
import os
import re
import openai
import pinecone
from dotenv import load_dotenv
from ens_normalize import ens_cure, DisallowedNameError
from interactions import Client, Intents, slash_command, slash_option, SlashContext, OptionType
from interactions.models.discord import Embed, BrandColors
from web3 import Web3

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
tx_checking_interval = int(os.getenv('TX_CHECKING_INTERVAL'))

contract_addresses = { # Make sure addresses are checksum format
    "mainnet": {
        "ETHRegistrarController": "0x253553366Da8546fC250F225fe3d25d0C782303b",
        "PublicResolver": "0x4976fb03C32e5B8cfe2b6cCB31c09Ba78EBaBa41"
    },
    "goerli": {
        "ETHRegistrarController": "0xCc5e7dB10E65EED1BBD105359e7268aa660f6734",
        "PublicResolver": "0x19c2d5D0f035563344dBB7bE5fD09c8dad62b001"
    }
}

pinecone.init(api_key=pinecone_api_key, environment="northamerica-northeast1-gcp")
openai_embed_model = "text-embedding-ada-002"
pinecone_index_name = "namebazaar-gpt"

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


def get_tx_page_url(tx_data):
    return f"{tx_page_host}?to={tx_data['to']}&data={tx_data['data']}&value={tx_data['value']}"


web3 = Web3(Web3.WebsocketProvider(infura_url))
eth_registrar = web3.eth.contract(address=get_contract_address("ETHRegistrarController"),
                                  abi=get_abi("ETHRegistrarController"))


def less_hours_passed(start_time, hours):
    now = datetime.datetime.now()
    time_passed = now - start_time
    return time_passed < datetime.timedelta(hours=hours)


async def listen_for_register(interval_start, name_label, owner, ctx):
    label_hash = Web3.keccak(name_label.encode("utf-8"))
    event_filter = eth_registrar.events.NameRegistered.create_filter(
        fromBlock="latest",
        argument_filters={"label": label_hash, "owner": owner}
    )
    while less_hours_passed(interval_start, 72):
        events = event_filter.get_new_entries()
        logger.info(f"register events: {events}")
        if events:
            ens_name = add_eth_suffix(name_label)
            await ctx.send(f"Congratulations, {ctx.author.mention}! You are now the proud owner of `{ens_name}`.")
            break

        await asyncio.sleep(tx_checking_interval)



async def listen_for_commit(
        interval_start,
        commitment,
        name_label,
        eth_address,
        register_duration,
        salt_bytes,
        ctx):
    while less_hours_passed(interval_start, 24):
        commitment_timestamp = eth_registrar.functions.commitments(commitment).call()
        logger.info(f"Commitment Timestamp...{commitment_timestamp}")

        if commitment_timestamp > 0:
            # Wait until commit period ends
            await asyncio.sleep(65)

            # Add 10% to account for price fluctuation; the difference is refunded.
            rent_price_wei = eth_registrar.functions.rentPrice(name_label, register_duration).call()[0]
            rent_price_wei = int(float(rent_price_wei) * 1.1)
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

            ens_name = add_eth_suffix(name_label)

            embed = Embed(
                title=f"Finish Registration for `{ens_name}`",
                description=f"To complete the registration process for `{ens_name}`, please click on the link provided above.\n"
                            f"The ENS cost for 1 year registration is {round(rent_price_eth, 3)} ETH.\n"
                            f"Upon selecting this option, the link will automatically launch in your web browser and "
                            f"trigger the MetaMask extension or the app on the mobile.",
                color=BrandColors.GREEN,
                url=tx_url
            )

            await ctx.send(f"{ctx.author.mention} Great! Now you are just a step away from registering `{ens_name}`. ",
                           embeds=embed,
                           ephemeral=True)

            await listen_for_register(
                interval_start=datetime.datetime.now(),
                name_label=name_label,
                owner=eth_address,
                ctx=ctx)
            break

        await asyncio.sleep(tx_checking_interval)



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

        if not Web3.is_checksum_address(eth_address):
            await ctx.send(f"It appears that the Ethereum address you provided is not valid. "
                           f"Please provide the address in checksum format", ephemeral=True)
            return

        if "." in name_label:
            await ctx.send(f"We apologize for the inconvenience, but at the moment, we do not offer support for "
                           f"registering subnames. However, we plan to add this feature soon. "
                           f"Please feel free to share your intended use case with us!", ephemeral=True)
            return

        is_available = eth_registrar.functions.available(name_label).call()

        logger.info(f"available: {is_available}")

        if not is_available:
            await ctx.send(f"I apologize, but the name `{cured_name}` is not available for registration.", ephemeral=True)
            return

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
            title=f"Begin Registration for `{cured_name}`",
            description=f"To initiate the registration process for `{cured_name}`, please click on the link above.\n"
                        f"Upon clicking this, the URL will open in your browser, which will then automatically launch"
                        f" your MetaMask browser extension or the app on the mobile. Please make sure you have "
                        f"the MetaMask installed.\n"
                        f"You will be notified once we are ready to proceed with the second step of the registration process.",
            color=BrandColors.YELLOW,
            url=tx_url
        )

        await ctx.send(f"You are about to begin a two-step registration process for `{cured_name}`.", embeds=embed, ephemeral=True)
        await listen_for_commit(
            commitment=commitment,
            interval_start=datetime.datetime.now(),
            ctx=ctx,
            name_label=name_label,
            eth_address=eth_address,
            register_duration=register_duration,
            salt_bytes=salt_bytes
        )
    except DisallowedNameError as e:
        await ctx.send(f"I apologize, but the name `{ens_name}` cannot be accepted for registration.", ephemeral=True)

bot.start(namebazaarGPT_token)
