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
from interactions import listen, Client, Intents, slash_command, slash_option, SlashContext, OptionType, File, \
    component_callback, ComponentContext
from interactions.models.discord import Embed, BrandColors, ButtonStyle, Button
from web3 import Web3
from quart import Quart, request, jsonify, abort
import nest_asyncio
from tx_db import TxDB
from user_address_db import UserAddressDB
import hashlib
from quart_cors import cors
import httpx
import io
import zlib
import base64
import urllib.parse
import random

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
        "ETHRegistrar": "0x57f1887a8BF19b14fC0dF6Fd9B2acc9Af147eA85",
        "ENSRegistry": "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e",
        "PublicResolver": "0x231b0Ee14048e9dCcD1d247744d114a4EB5E8E63",
        "NameWrapper": "0xD4416b13d2b3a9aBae7AcD5D6C2BbDBE25686401",
        "Seaport": "0x00000000000000ADc04C56Bf30aC9d3c0aAF14dC",
        "OpenSeaConduit": "0x1E0049783F008A0085193E00003D00cd54003c71"
    },
    "goerli": {
        "ETHRegistrarController": "0xCc5e7dB10E65EED1BBD105359e7268aa660f6734",
        "ETHRegistrar": "0xf7a220ad9d818cd3083a57b321f0473cd92dc73d",
        "PublicResolver": "0x19c2d5D0f035563344dBB7bE5fD09c8dad62b001"
    }
}

opeansea_urls = {
    "mainnet": {
        "listings": "https://api.opensea.io/v2/orders/ethereum/seaport/listings",
        "fulfillment": "https://api.opensea.io/v2/listings/fulfillment_data"
    },
    "goerli": {
        "listings": "https://testnets-api.opensea.io/v2/orders/goerli/seaport/listings"
    }
}

subgraph_url = "https://api.thegraph.com/subgraphs/name/ensdomains/ens"

intents = Intents.MESSAGES
intents.messages = True
intents.guilds = True
intents.message_content = True
intents.members = True

tx_db = TxDB('nb.db')
user_address_db = UserAddressDB('nb.db')
bot = Client(intents=intents)


def mention(user_id):
    return f"<@{user_id}>"


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


def is_top_level_eth(ens_name):
    parts = ens_name.split(".")

    if len(parts) == 2 and parts[1] == "eth":
        return True

    return False


def get_tx_page_url(tx_key, tx_data, sign_spec=None):
    base_url = f"{tx_page_url}?" \
               f"tx_key={tx_key}&" \
               f"to={tx_data['to']}&" \
               f"data={tx_data['data']}&" \
               f"value={tx_data['value']}&" \
               f"host={server_host}&" \
               f"port={server_port}"
    if sign_spec:
        base_url += f"&sign_spec={sign_spec}"
    return base_url


web3 = Web3(Web3.WebsocketProvider(infura_url))
eth_registrar_controller = web3.eth.contract(address=get_contract_address("ETHRegistrarController"),
                                             abi=get_abi("ETHRegistrarController"))
eth_registrar = web3.eth.contract(address=get_contract_address("ETHRegistrar"), abi=get_abi("ETHRegistrar"))
public_resolver = web3.eth.contract(address=get_contract_address("PublicResolver"), abi=get_abi("PublicResolver"))
name_wrapper = web3.eth.contract(address=get_contract_address("NameWrapper"), abi=get_abi("NameWrapper"))
ens_registry = web3.eth.contract(address=get_contract_address("ENSRegistry"), abi=get_abi("ENSRegistry"))
opensea_conduit = web3.eth.contract(address=get_contract_address("OpenSeaConduit"), abi=get_abi("OpenSeaConduit"))
seaport_abi = get_abi("Seaport")
seaport = web3.eth.contract(address=get_contract_address("Seaport"), abi=seaport_abi)


def less_hours_passed(start_time, hours):
    now = datetime.datetime.now()
    time_passed = now - start_time
    return time_passed < datetime.timedelta(hours=hours)


def generate_tx_key():
    return hashlib.sha256(f"{random.randint(10, 999999999999999)}".encode()).hexdigest()[:32]


def namehash(name):
    if name == '':
        return b'\0' * 32
    else:
        label, _, remainder = name.partition('.')
        return Web3.keccak(namehash(remainder) + Web3.keccak(text=label))


def generate_opensea_salt():
    salt_length = 77
    salt_min_value = 10 ** (salt_length - 1)
    salt_max_value = (10 ** salt_length) - 1
    return random.randint(salt_min_value, salt_max_value)


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


def prepare_tx_parameters(parameters):
    for key in parameters:
        if isinstance(parameters[key], str):
            if parameters[key].isdigit():
                # Convert numeric strings to integers
                parameters[key] = int(parameters[key])
            elif parameters[key].startswith('0x') and len(parameters[key]) == 42:
                parameters[key] = Web3.to_checksum_address(parameters[key])
                # Convert hex strings to bytes
                # parameters[key] = bytes.fromhex(parameters[key][2:])
        elif isinstance(parameters[key], list):
            # Recursively prepare parameters in lists
            parameters[key] = [prepare_tx_parameters(param) if isinstance(param, dict) else param for param in
                               parameters[key]]
    return parameters


def compress_string_to_url(s):
    compressed = zlib.compress(s.encode())
    encoded = base64.b64encode(compressed)
    url_safe_encoded = urllib.parse.quote_plus(encoded)
    return url_safe_encoded


def split_opensea_consideration(wei_value):
    # Split the provided wei_value into two parts: 97.5% and 2.5%
    part1 = int(wei_value * 0.975)
    part2 = int(wei_value * 0.025)

    return part1, part2


http_client = httpx.AsyncClient()


@listen()
async def on_ready():
    # ready events pass no data, so dont have params
    logger.info("Bot is ready")


async def _buy(ctx, ens_name):
    try:
        ens_name = add_eth_suffix(ens_name)
        cured_name = ens_cure(ens_name)

        if not is_top_level_eth(cured_name):
            await ctx.send(f"Apologies, but at the moment, our support is limited to top-level .eth names only.",
                           ephemeral=True)
            return

        name_label = remove_eth_suffix(cured_name)

        label_hash = Web3.keccak(text=name_label)
        node = namehash(cured_name)
        unwrapped_token_id = int.from_bytes(label_hash, byteorder='big')
        wrapped_token_id = int.from_bytes(node, byteorder='big')

        is_wrapped = name_wrapper.functions.isWrapped(node).call()

        headers = {
            "accept": "application/json",
            "X-API-KEY": opensea_api_key
        }

        url = f"{get_opensea_url('listings')}?" \
              f"asset_contract_address={name_wrapper.address if is_wrapped else eth_registrar.address}&" \
              f"token_ids={wrapped_token_id if is_wrapped else unwrapped_token_id}&" \
              f"order_by=eth_price&" \
              f"order_direction=asc"

        response = await http_client.get(url, headers=headers)

        listings = response.json()

        if not "orders" in listings:
            await ctx.send(f"It appears that `{cured_name}` is not currently listed for sale on OpenSea.",
                           ephemeral=True)
            return

        order_hash = listings["orders"][0]["order_hash"]
        protocol_address = listings["orders"][0]["protocol_address"]

        url = get_opensea_url("fulfillment")

        payload = {
            "listing": {
                "hash": order_hash,
                "chain": "ethereum",
                "protocol_address": protocol_address
            },
            "fulfiller": {
                "address": "0x0940f7D6E7ad832e0085533DD2a114b424d5E83A"
            }
        }

        response = await http_client.post(url, json=payload, headers=headers)
        fulfillment = json.loads(response.text)

        logger.info(fulfillment["protocol"])

        tx_to = Web3.to_checksum_address(fulfillment["fulfillment_data"]["transaction"]["to"])

        seaport = web3.eth.contract(address=tx_to, abi=seaport_abi)

        fn_signature = fulfillment["fulfillment_data"]["transaction"]["function"]
        fn_name = fn_signature.split("(")[0]
        args_dict = prepare_tx_parameters(fulfillment["fulfillment_data"]["transaction"]["input_data"]["parameters"])

        tx_data = seaport.encodeABI(fn_name=fn_name, args=[list(args_dict.values())])
        tx_value = int(fulfillment["fulfillment_data"]["transaction"]["value"])

        tx = {
            "to": Web3.to_checksum_address(fulfillment["fulfillment_data"]["transaction"]["to"]),
            "data": compress_string_to_url(tx_data),
            "value": tx_value
        }
        tx_key = generate_tx_key()
        tx_url = get_tx_page_url(tx_key, tx)
        price = str(round(web3.from_wei(tx_value, "ether"), 4))

        tx_db.add_tx({"tx_key": tx_key,
                      "user": ctx.author_id,
                      "action": "buy",
                      "channel": ctx.channel_id,
                      "next_action_data": json.dumps({"ens_name": cured_name,
                                                      "price": price})})

        embed = Embed(
            title=f"Buy `{cured_name}`",
            description=f"Click to buy `{cured_name}`",
            fields=[{"name": "Price", "value": f"{price} ETH"}],
            color=BrandColors.GREEN,
            url=tx_url)

        await ctx.send(f"You are about to buy `{cured_name}`.", embeds=embed, ephemeral=True)
    except DisallowedNameError as e:
        await ctx.send(f"I apologize, but the name `{ens_name}` is not a valid ENS name.", ephemeral=True)
    except Exception as e:
        await ctx.send(f"I'm sorry, but an error occurred while trying to initiate the purchase of `{ens_name}`.",
                       ephemeral=True)
        logger.error(f"Buy command exception {str(e)}")
        raise e


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
    await _buy(ctx, ens_name)


@component_callback(re.compile(r"^buy_btn_"))
async def my_callback(ctx: ComponentContext):
    ens_name = re.sub(r"^buy_btn_", "", ctx.custom_id)
    await _buy(ctx, ens_name)


@slash_command(name="test", description="This command is for testing purposes")
async def test(ctx: SlashContext):
    await ctx.send("This is just a test")


async def _connect_wallet(ctx: SlashContext, ctx_message):
    tx_key = generate_tx_key()

    json_data = json.dumps({"nickname": ctx.author.nickname})

    tx_db.add_tx({"tx_key": tx_key,
                  "user": ctx.author_id,
                  "action": "connect_wallet",
                  "channel": ctx.channel_id,
                  "next_action_data": json_data})

    tx = {
        "to": "",
        "data": compress_string_to_url(json_data),
        "value": 0
    }

    tx_url = get_tx_page_url(tx_key, tx, sign_spec="ConnectWallet")

    embed = Embed(
        title=f"Link your Ethereum Wallet with NameBazaarBot",
        description=f"This will open your MetaMask...",
        color=BrandColors.WHITE,
        url=tx_url)

    await ctx.send(ctx_message, embeds=embed, ephemeral=True)


@slash_command(name="connect_wallet", description="Link your Ethereum address to your Discord account.")
async def connect_wallet(ctx: SlashContext):
    await _connect_wallet(ctx, "Let's get this linking stuff done, so we can start trading!")


@slash_command(name="sell", description="Sell ENS name")
@slash_option(
    name="ens_name",
    description="Please provide the ENS name that you wish to sell.",
    required=True,
    opt_type=OptionType.STRING,
    max_length=100,
    min_length=3
)
@slash_option(
    name="start_price",
    description="Specify the initial selling price for your name in ETH.",
    required=True,
    opt_type=OptionType.NUMBER,
)
@slash_option(
    name="end_price",
    description="Specify the final selling price for your name in ETH. If empty, it equals the start price.",
    required=False,
    opt_type=OptionType.NUMBER,
)
@slash_option(
    name="duration_days",
    description="Specify the duration, in days, for which your listing will remain valid. Default is 100 days)",
    required=False,
    opt_type=OptionType.INTEGER,
    min_value=1,
    max_value=1000
)
async def sell(ctx: SlashContext, ens_name, start_price, end_price=None, duration_days=100):
    try:
        connected_address = "0x0940f7D6E7ad832e0085533DD2a114b424d5E83A"

        if end_price is None:
            end_price = start_price

        ens_name = add_eth_suffix(ens_name)
        cured_name = ens_cure(ens_name)

        if not is_top_level_eth(cured_name):
            await ctx.send(f"Apologies, but at the moment, our support is limited to top-level .eth names only.",
                           ephemeral=True)
            return

        name_label = remove_eth_suffix(cured_name)
        node = namehash(cured_name)
        hex_node = node.hex()
        label_hash = Web3.keccak(text=name_label)
        token_id = int.from_bytes(label_hash, byteorder='big')
        hex_label = hex(token_id)

        query = f"""
                {{
                  registration(
                    id: "{hex_label}"
                  ) {{
                    registrant {{
                      id
                    }}
                  }}
                  wrappedDomain(
                    id: "{hex_node}"
                  ) {{
                    owner {{
                      id
                    }}
                  }}
                }}
                """
        response = await http_client.post(subgraph_url, json={"query": query})
        data = response.json().get('data', {})
        registration = data.get('registration')
        wrapped_domain = data.get('wrappedDomain')

        owner = None
        is_wrapped = False
        if registration is not None:
            owner = registration.get('registrant', {}).get('id')

        if wrapped_domain is not None:
            owner = wrapped_domain.get('owner', {}).get('id')
            token_id = int.from_bytes(node, byteorder='big')
            is_wrapped = True

        if owner is None or owner.lower() != connected_address.lower():
            await ctx.send(f"It appears that you don't own `{cured_name}`.", ephemeral=True)
            return

        start_time = int(datetime.datetime.now().timestamp())
        end_time = int((datetime.datetime.now() + datetime.timedelta(days=duration_days)).timestamp())

        start_price_wei = Web3.to_wei(start_price, "ether")
        end_price_wei = Web3.to_wei(end_price, "ether")
        owner_start_price, fees_start_price = split_opensea_consideration(start_price_wei)
        owner_end_price, fees_end_price = split_opensea_consideration(end_price_wei)

        order_params = {
            "offerer": connected_address,
            "offer": [{
                "itemType": 3 if is_wrapped else 2,
                "token": name_wrapper.address if is_wrapped else eth_registrar.address,
                "identifierOrCriteria": str(token_id),
                "startAmount": 1,
                "endAmount": 1
            }],
            "consideration": [{
                "itemType": 0,
                "token": "0x0000000000000000000000000000000000000000",
                "identifierOrCriteria": 0,
                "startAmount": str(owner_start_price),
                "endAmount": str(owner_end_price),
                "recipient": connected_address,
            }, {  ## OpenSea Fees have to be defined, at least 2.5%
                "itemType": 0,
                "token": "0x0000000000000000000000000000000000000000",
                "identifierOrCriteria": 0,
                "startAmount": str(fees_start_price),
                "endAmount": str(fees_end_price),
                "recipient": "0x0000a26b00c1F0DF003000390027140000fAa719",
            }],
            "totalOriginalConsiderationItems": 2,
            "startTime": start_time,
            "endTime": end_time,
            "orderType": 1,
            "zone": "0x004C00500000aD104D7DBd00e3ae0A5C00560C00",
            "zoneHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
            "salt": str(generate_opensea_salt()),
            "conduitKey": "0x0000007b02230091a7ed01230072f7006a004d60a8d4e71d599b8104250f0000",
            "counter": 0,
        }

        order_params_json = json.dumps(order_params)

        tx = {
            "to": seaport.address,
            "data": compress_string_to_url(order_params_json),
            "value": 0
        }

        tx_key = generate_tx_key()
        tx_url = get_tx_page_url(tx_key, tx, sign_spec="OSCreateListing")

        tx_db.add_tx({"tx_key": tx_key,
                      "user": ctx.author_id,
                      "action": "sell",
                      "channel": ctx.channel_id,
                      "next_action_data": order_params_json})

        embed = Embed(
            title=f"Sign the sales contract for `{cured_name}`",
            description=f"To initiate the selling process for `{cured_name}`, please click on the link above.\n"
                        f"Upon clicking this, the URL will open in your browser, which will then automatically launch"
                        f" your MetaMask browser extension or the app on the mobile. Please make sure you have "
                        f"the MetaMask installed.\n"
                        f"You will be notified once we are ready to proceed with the second step of the registration process.",
            color=BrandColors.GREEN,
            url=tx_url)

        await ctx.send(f"", embeds=embed, ephemeral=True)
    except DisallowedNameError as e:
        await ctx.send(f"I apologize, but the name `{ens_name}` is not a valid ENS name.", ephemeral=True)
    except Exception as e:
        await ctx.send(f"I'm sorry, but an error occurred while trying to initiate the selling of `{cured_name}`.",
                       ephemeral=True)
        logger.error(f"Sell command exception {str(e)}")
        raise e


async def _owned_names(ctx: SlashContext, owner_address):
    try:
        query_template = """
        {
          account(id: "%s") {
            registrations {
              domain {
                name
              }
            }
            wrappedDomains {
              domain {
                name
              }
            }
          }
        }
        """
        query = query_template % owner_address.lower()
        response = await http_client.post(subgraph_url, json={"query": query})
        data = response.json()

        if "data" in data:
            account = data["data"]["account"]
            if account:
                registrations = account.get("registrations", [])
                wrapped_domains = account.get("wrappedDomains", [])
                if not registrations and not wrapped_domains:
                    await ctx.send(f"There are no names associated with this address.", ephemeral=True)
                    return

                wrapped_domain_names = [item["domain"]["name"] for item in wrapped_domains]
                registration_names = [item["domain"]["name"] for item in registrations]

                combined_names = wrapped_domain_names + registration_names
                unique_sorted_names = sorted(list(set(combined_names)))

                formatted_names = "\n".join(unique_sorted_names)
                await ctx.send(f"```\n{formatted_names}```", ephemeral=True)

            else:
                await ctx.send("Apologies, but no matching account was found for this address", ephemeral=True)
        else:
            await ctx.send(
                "Apologies, an error occurred while fetching data from the subgraph. Please try again later.",
                ephemeral=True)
    except Exception as e:
        await ctx.send(f"I'm sorry, but an error occurred while trying to obtain owned names.", ephemeral=True)
        logger.error(f"owned_names command exception {str(e)}")
        raise e


@slash_command(name="owned_names", description="Shows list of names owned by a given address")
@slash_option(
    name="owner_address",
    description="Please provide the Ethereum address you wish to get list of owned names for.",
    required=True,
    opt_type=OptionType.STRING,
    max_length=42,
    min_length=42
)
async def owned_names(ctx: SlashContext, owner_address):
    await _owned_names(ctx, owner_address)


@slash_command(name="my_names", description="Shows list of names owned by your connected address")
async def my_names(ctx: SlashContext):
    connected_address = "0x0940f7D6E7ad832e0085533DD2a114b424d5E83A"
    await _owned_names(ctx, connected_address)


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
    register_duration = 31536000
    logger.info(f"register {ens_name}")
    owner_address = "0x0940f7D6E7ad832e0085533DD2a114b424d5E83A"

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

        is_available = eth_registrar_controller.functions.available(name_label).call()

        if not is_available:
            await ctx.send(f"I apologize, but the name `{cured_name}` is not available for registration.",
                           ephemeral=True)
            return

        node = namehash(ens_name)
        set_addr_data = public_resolver.encodeABI(fn_name="setAddr", args=[node, owner_address])[2:]

        salt_bytes = os.urandom(32)

        commitment = eth_registrar_controller.functions.makeCommitment(
            name_label,
            owner_address,
            register_duration,
            salt_bytes,
            public_resolver.address,
            [bytes.fromhex(set_addr_data)],
            False,
            0
        ).call()

        tx = {
            "to": eth_registrar_controller.address,
            "data": compress_string_to_url(eth_registrar_controller.encodeABI(fn_name="commit", args=[commitment])),
            "value": 0
        }

        tx_key = generate_tx_key()
        tx_url = get_tx_page_url(tx_key, tx)

        tx_db.add_tx({"tx_key": tx_key,
                      "user": ctx.author_id,
                      "action": "commit",
                      "channel": ctx.channel_id,
                      "next_action_data": json.dumps({"name_label": name_label,
                                                      "owner_address": owner_address,
                                                      "register_duration": register_duration,
                                                      "salt_hex": salt_bytes.hex(),
                                                      "set_addr_data": set_addr_data})})

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
        raise e


async def send_register_finish_url(
        name_label, register_duration, owner_address, salt_bytes, set_addr_data, ctx_author, ctx_channel):
    try:
        user = bot.get_user(int(ctx_author))
        # Add 10% to account for price fluctuation; the difference is refunded.
        rent_price_wei = eth_registrar_controller.functions.rentPrice(name_label, register_duration).call()[0]
        rent_price_wei = int(float(rent_price_wei) * 1.1)
        rent_price_eth = web3.from_wei(rent_price_wei, "ether")

        args = [
            name_label,
            owner_address,
            register_duration,
            salt_bytes,
            public_resolver.address,
            [bytes.fromhex(set_addr_data)],
            False,
            0
        ]

        tx = {
            "to": eth_registrar_controller.address,
            "data": compress_string_to_url(eth_registrar_controller.encodeABI(fn_name="register", args=args)),
            "value": rent_price_wei
        }

        tx_key = generate_tx_key()
        tx_url = get_tx_page_url(tx_key, tx)

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
                        f"The ENS cost for 1 year registration is {round(rent_price_eth, 4)} ETH.\n"
                        f"Upon selecting this option, the link will automatically launch in your web browser and "
                        f"trigger the MetaMask extension or the app on the mobile.",
            color=BrandColors.GREEN,
            url=tx_url
        )

        await user.send(f"Great! Now you are just a step away from registering `{ens_name}`. ",
                        embeds=embed,
                        ephemeral=True)
    except Exception as e:
        logger.error(f"Error in send_register_finish_url {str(e)}")
        raise e


async def send_register_congrats(ens_name, owner_address, ctx_author, ctx_channel):
    try:
        channel = bot.get_channel(ctx_channel)
        await channel.send(
            f"Great news! `{ens_name}` is now owned by {mention(ctx_author)}, who can now proudly call it their own!")
    except Exception as e:
        logger.error(f"Error in send_register_finish_url {str(e)}")
        raise e


async def commit_callback(tx, tx_hash, next_action_data):
    try:
        await wait_for_receipt(tx_hash)
        await asyncio.sleep(61)  # The second step of the registration can be done only after 60 seconds
        await send_register_finish_url(name_label=next_action_data["name_label"],
                                       register_duration=int(next_action_data["register_duration"]),
                                       owner_address=next_action_data["owner_address"],
                                       salt_bytes=bytes.fromhex(next_action_data["salt_hex"]),
                                       set_addr_data=next_action_data["set_addr_data"],
                                       ctx_channel=int(tx["channel"]),
                                       ctx_author=tx["user"])
    except Exception as e:
        logger.error(f"Error in commit_callback {str(e)}")
        raise e


async def register_callback(tx, tx_hash, next_action_data):
    try:
        await wait_for_receipt(tx_hash)
        await send_register_congrats(ens_name=next_action_data["ens_name"],
                                     owner_address=next_action_data["owner_address"],
                                     ctx_channel=int(tx["channel"]),
                                     ctx_author=tx["user"])
    except Exception as e:
        logger.error(f"Error in register_callback {str(e)}")
        raise e


async def buy_callback(tx, tx_hash, next_action_data):
    try:
        await wait_for_receipt(tx_hash)
        channel = bot.get_channel(int(tx["channel"]))
        ens_name = next_action_data["ens_name"]
        price = next_action_data["price"]
        ctx_author = tx["user"]
        await channel.send(
            f"Exciting announcement! `{ens_name}` has been successfully purchased by {mention(ctx_author)} for `{price}` ETH!")
    except Exception as e:
        logger.error(f"Error in buy_callback {str(e)}")
        raise e


async def sell_callback(tx, tx_signature, next_action_data):
    try:
        channel = bot.get_channel(int(tx["channel"]))
        user = bot.get_user(int(tx["user"]))

        ctx_author = tx["user"]

        order_params = {
            "parameters": next_action_data,
            "signature": tx_signature,
            "protocol_address": get_contract_address("Seaport")
        }

        logger.info(order_params)

        headers = {
            "accept": "application/json",
            "X-API-KEY": opensea_api_key,
            "content-type": "application/json"
        }

        response = await http_client.post(get_opensea_url('listings'), json=order_params, headers=headers)
        response = response.json()

        if "errors" in response:
            await user.send(
                f"Apologies, an error occurred while attempting to send your order to OpenSea.\n"
                f"```{response['errors'][0]}```")
            return

        order = response["order"]
        asset = order["maker_asset_bundle"]["assets"][0]
        token_id = asset["token_id"]
        contract_address = asset["asset_contract"]["address"]
        ens_name = asset["name"]
        expiration_date = datetime.datetime.fromtimestamp(order["expiration_time"])

        logger.info(f"price {order['current_price']}")
        price = round(Web3.from_wei(int(order["current_price"]), "ether"), 3)

        embed = Embed(
            title=f"View `{ens_name}` on OpenSea",
            fields=[
                {"name": "Price", "value": f"{price} ETH", "inline": True},
                {"name": "Expiration", "value": expiration_date.strftime("%Y-%m-%d"), "inline": True}
            ],
            color=BrandColors.GREEN,
            url=f"https://opensea.io/assets/ethereum/{contract_address}/{token_id}"
        )

        await user.send(f"Well done! Your listing for `{ens_name}` has been successfully added to OpenSea!",
                        embeds=embed)

        components = Button(
            style=ButtonStyle.GREEN,
            emoji="🤑",
            label=f"Buy {ens_name}",
            custom_id=f"buy_btn_{ens_name}",
        )

        await channel.send(f"{user.mention} has just added `{ens_name}` for sale at the price of `{price} ETH!`",
                           components=components)



    except Exception as e:
        logger.error(f"Error in sell_callback {str(e)}")
        raise e


app = Quart(__name__)
app = cors(app, allow_origin="*")  # reconsider this in prod


@app.route('/tx', methods=['POST'])
async def user_post():
    data = await request.data
    json_data = json.loads(data.decode())
    logger.info(f'Received POST data: {json_data}')
    tx_key = json_data["txKey"]
    tx_result = json_data["txResult"]

    if not tx_key or not tx_result or not tx_db.tx_key_exists(tx_key):
        abort(400, description='Transaction key is invalid')

    tx_db.update_tx_result(tx_key, tx_result)
    tx = tx_db.get_tx(tx_key)

    logger.info(f'TX {tx}')

    next_action_data = json.loads(tx["next_action_data"])

    if tx["action"] == "commit":
        asyncio.create_task(commit_callback(tx, tx_result, next_action_data))
    elif tx["action"] == "register":
        asyncio.create_task(register_callback(tx, tx_result, next_action_data))
    elif tx["action"] == "buy":
        asyncio.create_task(buy_callback(tx, tx_result, next_action_data))
    elif tx["action"] == "sell":
        asyncio.create_task(sell_callback(tx, tx_result, next_action_data))

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
