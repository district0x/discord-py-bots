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
from interactions import listen, Client, Intents, slash_command, slash_option, SlashContext, OptionType, File
from interactions.models.discord import Embed, BrandColors
from web3 import Web3
from quart import Quart, request, jsonify, abort
import nest_asyncio
from tx_db import TxDB
import hashlib
from quart_cors import cors
import httpx
import io

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("namebazaarGPT")

namebazaarGPT_token = os.getenv('NAMEBAZAAR_GPT_TOKEN')
namebazaarGPT_client_id = os.getenv('NAMEBAZAAR_GPT_CLIENT_ID')
openai.api_key = os.getenv('OPENAI_API_KEY')
pinecone_api_key = os.getenv('PINECONE_API_KEY')
opensea_api_key = os.getenv('OPENSEA_API_KEY')
max_uses_per_day = os.getenv('MAX_USES_PER_DAY')
admin_user_id = os.getenv('ADMIN_USER_ID')
infura_url = os.getenv('INFURA_URL')
web3_network = os.getenv('WEB3_NETWORK')
tx_page_url = os.getenv('TX_PAGE_URL')
server_host = os.getenv('SERVER_HOST')
server_port = os.getenv('SERVER_PORT')

contract_addresses = {  # Make sure addresses are checksum format
    "mainnet": {
        "ETHRegistrarController": "0x253553366Da8546fC250F225fe3d25d0C782303b",
        "ETHRegistrar": "0x57f1887a8bf19b14fc0df6fd9b2acc9af147ea85",
        "PublicResolver": "0x4976fb03C32e5B8cfe2b6cCB31c09Ba78EBaBa41"
    },
    "goerli": {
        "ETHRegistrarController": "0xCc5e7dB10E65EED1BBD105359e7268aa660f6734",
        "ETHRegistrar": "0xf7a220ad9d818cd3083a57b321f0473cd92dc73d",
        "PublicResolver": "0x19c2d5D0f035563344dBB7bE5fD09c8dad62b001"
    }
}

opeansea_urls = {
    "mainnet" : {
        "listings": "https://api.opensea.io/v2/orders/ethereum/seaport/listings",
        "fulfillment": "https://api.opensea.io/v2/listings/fulfillment_data"
    },
    "goerli": {
        "listings" : "https://testnets-api.opensea.io/v2/orders/goerli/seaport/listings"
    }
}

pinecone.init(api_key=pinecone_api_key, environment="northamerica-northeast1-gcp")
openai_embed_model = "text-embedding-ada-002"
pinecone_index_name = "namebazaar-gpt"

intents = Intents.DEFAULT
intents.messages = True
intents.guilds = True
intents.message_content = True

tx_db = TxDB('tx.db')

bot = Client(intents=intents)


def hexlify(name):
    return binascii.hexlify(name).decode('utf-8')


def get_abi(contract_name):
    with open(f"abi/{contract_name}.abi", 'r') as f:
        return json.load(f)


def get_contract_address(contract_name):
    return contract_addresses[web3_network][contract_name]


def get_opensea_url(endpoint):
    return opeansea_urls[web3_network][endpoint]


def add_eth_suffix(ens_name):
    if not ens_name.endswith(".eth"):
        ens_name += ".eth"
    return ens_name


def remove_eth_suffix(s: str) -> str:
    if s.endswith(".eth"):
        return s[:-4]
    else:
        return s


def get_tx_page_url(tx_key, tx_data):
    return f"{tx_page_url}?tx_key={tx_key}&to={tx_data['to']}&data={tx_data['data']}&value={tx_data['value']}" \
           f"&host={server_host}&port={server_port}"


web3 = Web3(Web3.WebsocketProvider(infura_url))
eth_registrar = web3.eth.contract(address=get_contract_address("ETHRegistrarController"),
                                  abi=get_abi("ETHRegistrarController"))


def less_hours_passed(start_time, hours):
    now = datetime.datetime.now()
    time_passed = now - start_time
    return time_passed < datetime.timedelta(hours=hours)


def get_tx_key(tx_data):
    return hashlib.sha256(f"{tx_data['to']}{tx_data['data']}{tx_data['value']}".encode()).hexdigest()[:32]


async def wait_for_receipt(tx_hash: str) -> dict:
    receipt = None
    start = datetime.datetime.now()
    while receipt is None and less_hours_passed(start, 24):
        try:
            receipt = web3.eth.get_transaction_receipt(tx_hash)
        except ValueError:
            logger.error(f"Invalid transaction hash {tx_hash}")
        except Exception as e:
            # Thows exception when transaction hash is not yet found
            await asyncio.sleep(15)
            continue
        await asyncio.sleep(15)
    return receipt


@listen()
async def on_ready():
    # ready events pass no data, so dont have params
    logger.info("Bot is ready")


@slash_command(name="buy", description="Buy ENS name")
@slash_option(
    name="ens_name",
    description="Please provide the ENS name that you wish to buy.",
    required=True,
    opt_type=OptionType.STRING,
    max_length=100,
    min_length=3
)
async def buy(ctx: SlashContext, ens_name):
    try:
        ens_name = add_eth_suffix(ens_name)
        cured_name = ens_cure(ens_name)
        name_label = remove_eth_suffix(cured_name)

        label_hash = Web3.keccak(text=name_label)
        token_id = int.from_bytes(label_hash, byteorder='big')
        logger.info(f"token id: {token_id}")

        headers = {
            "accept": "application/json",
            "X-API-KEY": opensea_api_key
        }

        url = f"{get_opensea_url('listings')}?" \
              f"asset_contract_address={get_contract_address('ETHRegistrar')}&" \
              f"token_ids={token_id}"

        client = httpx.AsyncClient()

        response = await client.get(url, headers=headers)

        parsed_json = json.loads(response.text)
        formatted_json = json.dumps(parsed_json, indent=4)

        if not parsed_json["orders"]:
            await ctx.send(f"It appears that `{ens_name}` is not currently listed for sale on OpenSea.", ephemeral=True)
            return

        url = get_opensea_url("fulfillment")

        payload = {
            "listing": {
                "hash": parsed_json["orders"][0]["order_hash"],
                "chain": "ethereum",
                "protocol_address": parsed_json["orders"][0]["protocol_address"]
            },
            "fulfiller": {
                "address": "0x0940f7D6E7ad832e0085533DD2a114b424d5E83A"
            }
        }

        response = await client.post(url, json=payload, headers=headers)

        parsed_json = json.loads(response.text)
        formatted_json = json.dumps(parsed_json, indent=4)

        string_io = io.StringIO(formatted_json)
        string_as_file = File(file=string_io, file_name="myfile.txt")

        await ctx.send(f"Here OpenSea response for `{ens_name}`:", files=[string_as_file])

    except DisallowedNameError as e:
        await ctx.send(f"I apologize, but the name `{ens_name}` is not a valid ENS name.", ephemeral=True)
    except Exception as e:
        await ctx.send(f"I'm sorry, but an error occurred while trying to initiate the purchase of {ens_name}.", ephemeral=True)
        logger.error(f"Buy command exception {str(e)}")



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
    name="owner_address",
    description="Please provide the Ethereum address you wish to register an ENS name with.",
    required=True,
    opt_type=OptionType.STRING,
    max_length=42,
    min_length=42
)
async def register(ctx: SlashContext, ens_name, owner_address):
    register_duration = 31536000
    logger.info(f"register {ens_name}")

    try:
        ens_name = add_eth_suffix(ens_name)
        cured_name = ens_cure(ens_name)
        name_label = remove_eth_suffix(cured_name)

        if not Web3.is_checksum_address(owner_address):
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
            await ctx.send(f"I apologize, but the name `{cured_name}` is not available for registration.",
                           ephemeral=True)
            return

        salt_bytes = os.urandom(32)

        commitment = eth_registrar.functions.makeCommitment(
            name_label,
            owner_address,
            register_duration,
            salt_bytes,
            get_contract_address("PublicResolver"),
            [],
            False,
            15
        ).call()

        logger.info(f"salt_bytes: {salt_bytes}")
        logger.info(f"salt_hex: {salt_bytes.hex()}")

        tx_data = eth_registrar.functions.commit(commitment).build_transaction()

        logger.info(tx_data)

        tx_key = get_tx_key(tx_data)
        tx_url = get_tx_page_url(tx_key, tx_data)

        tx_db.add_tx({"tx_key": tx_key,
                      "user": ctx.author.mention,
                      "action": "commit",
                      "channel": ctx.channel_id,
                      "next_action_data": json.dumps({"name_label": name_label,
                                                      "owner_address": owner_address,
                                                      "register_duration": register_duration,
                                                      "salt_hex": salt_bytes.hex()})})

        embed = Embed(
            title=f"Begin Registration for `{cured_name}`",
            description=f"To initiate the registration process for `{cured_name}`, please click on the link above.\n"
                        f"Upon clicking this, the URL will open in your browser, which will then automatically launch"
                        f" your MetaMask browser extension or the app on the mobile. Please make sure you have "
                        f"the MetaMask installed.\n"
                        f"You will be notified once we are ready to proceed with the second step of the registration process.",
            color=BrandColors.YELLOW,
            url=tx_url)

        await ctx.send(f"You are about to begin a two-step registration process for `{cured_name}`.", embeds=embed,
                       ephemeral=True)

    except DisallowedNameError as e:
        await ctx.send(f"I apologize, but the name `{ens_name}` cannot be accepted for registration.", ephemeral=True)
    except Exception as e:
        # Handle the exception here
        logger.info(f"REGISTER EXCEPTION {str(e)}")
        await ctx.respond('An error occurred: {}'.format(str(e)))


async def send_register_finish_url(
        name_label, register_duration, owner_address, salt_bytes, ctx_author, ctx_channel):
    try:
        # Add 10% to account for price fluctuation; the difference is refunded.
        rent_price_wei = eth_registrar.functions.rentPrice(name_label, register_duration).call()[0]
        rent_price_wei = int(float(rent_price_wei) * 1.1)
        rent_price_eth = web3.from_wei(rent_price_wei, "ether")

        tx_data = eth_registrar.functions.register(
            name_label,
            owner_address,
            register_duration,
            salt_bytes,
            get_contract_address("PublicResolver"),
            [],
            False,
            15
        ).build_transaction({"value": rent_price_wei})

        logger.info(tx_data)

        tx_key = get_tx_key(tx_data)
        tx_url = get_tx_page_url(tx_key, tx_data)

        ens_name = add_eth_suffix(name_label)

        tx_db.add_tx({"tx_key": tx_key,
                      "user": ctx_author,
                      "action": "register",
                      "channel": ctx_channel,
                      "next_action_data": json.dumps({"ens_name": ens_name,
                                                      "owner_address": owner_address})})

        embed = Embed(
            title=f"Finish Registration for `{ens_name}`",
            description=f"To complete the registration process for `{ens_name}`, please click on the link provided above.\n"
                        f"The ENS cost for 1 year registration is {round(rent_price_eth, 3)} ETH.\n"
                        f"Upon selecting this option, the link will automatically launch in your web browser and "
                        f"trigger the MetaMask extension or the app on the mobile.",
            color=BrandColors.GREEN,
            url=tx_url
        )

        channel = bot.get_channel(ctx_channel)

        await channel.send(f"{ctx_author} Great! Now you are just a step away from registering `{ens_name}`. ",
                           embeds=embed,
                           ephemeral=True)
    except Exception as e:
        logger.error(f"Error in send_register_finish_url {str(e)}")
        raise e


async def send_register_congrats(ens_name, owner_address, ctx_author, ctx_channel):
    try:
        channel = bot.get_channel(ctx_channel)
        await channel.send(f"Great news! `{ens_name}` is now owned by {ctx_author}, who can now proudly call it their own!")
    except Exception as e:
        logger.error(f"Error in send_register_finish_url {str(e)}")
        raise e


async def action_commit(tx, tx_hash, next_action_data):
    try:
        # Run tasks in sequence using
        logger.info("action commit")
        await wait_for_receipt(tx_hash)
        logger.info("receipt found!")
        await asyncio.sleep(61)  # The second step of the registration can be done only after 60 seconds
        logger.info("sleep is over")
        await send_register_finish_url(name_label=next_action_data["name_label"],
                                       register_duration=int(next_action_data["register_duration"]),
                                       owner_address=next_action_data["owner_address"],
                                       salt_bytes=bytes.fromhex(next_action_data["salt_hex"]),
                                       ctx_channel=int(tx["channel"]),
                                       ctx_author=tx["user"])
    except Exception as e:
        logger.error(f"Error in action_commit {str(e)}")
        raise e


async def action_register(tx, tx_hash, next_action_data):
    try:
        await wait_for_receipt(tx_hash)
        await send_register_congrats(ens_name=next_action_data["ens_name"],
                                     owner_address=next_action_data["owner_address"],
                                     ctx_channel=int(tx["channel"]),
                                     ctx_author=tx["user"])
    except Exception as e:
        logger.error(f"Error in action_register {str(e)}")
        raise e



app = Quart(__name__)
app = cors(app, allow_origin="*")  # reconsider this in prod


@app.route('/tx', methods=['POST'])
async def user_post():
    data = await request.data
    json_data = json.loads(data.decode())
    logger.info(f'Received POST data: {json_data}')
    tx_key = json_data["txKey"]
    tx_hash = json_data["txHash"]

    if not tx_key or not tx_hash or not tx_db.tx_key_exists(tx_key):
        abort(400, description='Transaction key is invalid')

    tx_db.update_tx_hash(tx_key, tx_hash)
    tx = tx_db.get_tx(tx_key)

    logger.info(f'TX {tx}')

    next_action_data = json.loads(tx["next_action_data"])

    if tx["action"] == "commit":
        asyncio.create_task(action_commit(tx, tx_hash, next_action_data))
    elif tx["action"] == "register":
        asyncio.create_task(action_register(tx, tx_hash, next_action_data))

    return jsonify({"status": "success"})


async def main():
    nest_asyncio.apply()
    tasks = [
        asyncio.create_task(app.run_task(host=server_host, port=server_port)),
        asyncio.create_task(bot.start(namebazaarGPT_token))
    ]
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        bot.stop()
