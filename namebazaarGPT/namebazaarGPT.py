import asyncio
import binascii
from datetime import datetime
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
from eth_account.messages import encode_defunct, _hash_eip191_message
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
tx_check_interval = os.getenv('TX_CHECK_INTERVAL')

contract_addresses = {  # Make sure addresses are checksum format
    "mainnet": {
        "ETHRegistrarController": "0x253553366Da8546fC250F225fe3d25d0C782303b",
        "ETHRegistrar": "0x57f1887a8BF19b14fC0dF6Fd9B2acc9Af147eA85",
        "ENSRegistry": "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e",
        "PublicResolver": "0x231b0Ee14048e9dCcD1d247744d114a4EB5E8E63",
        "NameWrapper": "0xD4416b13d2b3a9aBae7AcD5D6C2BbDBE25686401",
        "Seaport": "0x00000000000000ADc04C56Bf30aC9d3c0aAF14dC",
        "OpenSeaConduit": "0x1E0049783F008A0085193E00003D00cd54003c71",
        "Recover": "0x8564DAc105Ae26764467751a25DB1085B1176975",
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F"
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
        "fulfillment": "https://api.opensea.io/v2/listings/fulfillment_data",
        "offers": "https://api.opensea.io/v2/orders/ethereum/seaport/offers"
    },
    "goerli": {
        "listings": "https://testnets-api.opensea.io/v2/orders/goerli/seaport/listings"
    }
}

os_api_headers = {
    "accept": "application/json",
    "X-API-KEY": opensea_api_key,
    "content-type": "application/json"
}

subgraph_url = "https://api.thegraph.com/subgraphs/name/ensdomains/ens"

intents = Intents.DEFAULT
intents.messages = True
intents.guilds = True
intents.message_content = True
intents.members = True

tx_db = TxDB('nb.db')
user_address_db = UserAddressDB('nb.db')
bot = Client(intents=intents)

tx_link_instruction_text = f"please click on the link above. Upon clicking, the URL will open in your browser, " \
                           f"automatically launching your MetaMask browser extension or the mobile app. " \
                           f"Make sure you have MetaMask installed."


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
               f"from={tx_data.get('from', '')}&" \
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
recover = web3.eth.contract(address=get_contract_address("Recover"), abi=get_abi("Recover"))
weth = web3.eth.contract(address=get_contract_address("WETH"), abi=get_abi("WETH"))
usdc = web3.eth.contract(address=get_contract_address("USDC"), abi=get_abi("USDC"))
dai = web3.eth.contract(address=get_contract_address("DAI"), abi=get_abi("DAI"))


def less_hours_passed(start_time, hours):
    now = datetime.now()
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
    start = datetime.now()
    while receipt is None and less_hours_passed(start, 24):
        try:
            receipt = web3.eth.get_transaction_receipt(tx_hash)
        except ValueError:
            logger.error(f"Invalid transaction hash {tx_hash}")
        except Exception as e:
            # Thows exception when transaction hash is not yet found
            await asyncio.sleep(tx_check_interval)
            continue
        await asyncio.sleep(tx_check_interval)
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


def recursive_values(data):
    if isinstance(data, dict):
        return tuple(recursive_values(v) if isinstance(v, (dict, list)) else v for v in data.values())
    elif isinstance(data, list):
        return [recursive_values(v) if isinstance(v, (dict, list)) else v for v in data]
    else:
        return data


def prepare_tx_args(data):
    if isinstance(data, dict):
        # Prepare the dictionary items
        for key in data:
            if isinstance(data[key], str):
                if data[key].isdigit():
                    # Convert numeric strings to integers
                    data[key] = int(data[key])
                elif data[key].startswith('0x') and len(data[key]) == 42:
                    # Convert Ethereum addresses to checksum format
                    data[key] = Web3.to_checksum_address(data[key])
                    # Convert hex strings to bytes
                    # data[key] = bytes.fromhex(data[key][2:])
            elif isinstance(data[key], list):
                # Recursively prepare parameters in lists
                data[key] = [prepare_tx_args(param) if isinstance(param, dict) else param for param in
                             data[key]]

        # Extract values
        return tuple(prepare_tx_args(v) if isinstance(v, (dict, list)) else v for v in data.values())
    elif isinstance(data, list):
        return [prepare_tx_args(v) if isinstance(v, (dict, list)) else v for v in data]
    else:
        return data


format_time_remaining_units = [
    {'name': 'second', 'limit': 60, 'in_seconds': 1},
    {'name': 'minute', 'limit': 60 * 60, 'in_seconds': 60},
    {'name': 'hour', 'limit': 24 * 60 * 60, 'in_seconds': 60 * 60},
    {'name': 'day', 'limit': 7 * 24 * 60 * 60, 'in_seconds': 24 * 60 * 60},
    {'name': 'week', 'limit': 30.44 * 24 * 60 * 60, 'in_seconds': 7 * 24 * 60 * 60},
    {'name': 'month', 'limit': 365.24 * 24 * 60 * 60, 'in_seconds': 30.44 * 24 * 60 * 60},
    {'name': 'year', 'limit': None, 'in_seconds': 365.24 * 24 * 60 * 60}
]


def format_time_remaining(to_time, from_time=None):
    if from_time is None:
        from_time = datetime.now()

    diff = (to_time - from_time).total_seconds()

    if diff < 0:
        return "Time has already passed"
    elif diff < 5:
        return "in a few moments"
    else:
        for unit in format_time_remaining_units:
            if unit['limit'] is None or diff < unit['limit']:
                diff = int(diff // unit['in_seconds'])
                return f"in {diff} {unit['name']}{'s' if diff > 1 else ''}"


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


def get_consideration_token_contract(token_address):
    token_mapping = {
        usdc.address.lower(): ("usdc", usdc),
        weth.address.lower(): ("weth", weth),
        dai.address.lower(): ("dai", dai)
    }
    return token_mapping.get(token_address.lower(), ("eth", None))


def format_wei_price(price, token_name="eth"):
    if token_name == "usdc":
        return str(round(int(price) / 1000000, 3))
    return str(round(web3.from_wei(int(price), "ether"), 4))


def safe_to_wei(amount, token_name):
    if token_name == "usdc":
        return int(amount * 1000000)
    return web3.to_wei(amount, "ether")


http_client = httpx.AsyncClient()


@listen()
async def on_ready():
    # ready events pass no data, so dont have params
    logger.info("Bot is ready")


async def approve_erc20_allowance(ctx: SlashContext, ens_name, user_address, price, allowance, token_name,
                                  token_contract, next_tx_to, next_tx_data, next_tx_value, next_tx_order_type,
                                  highest_bid, expiration_time):
    try:
        tx_key = generate_tx_key()

        tx_db.add_tx({"tx_key": tx_key,
                      "user": ctx.author_id,
                      "action": "approve_erc20_allowance",
                      "channel": ctx.channel_id,
                      "next_action_data": json.dumps(
                          {"ens_name": ens_name,
                           "price": price,
                           "highest_bid": highest_bid,
                           "expiration_time": expiration_time,
                           "token_name": token_name,
                           "next_tx_to": next_tx_to,
                           "next_tx_from": user_address,
                           "next_tx_data": next_tx_data,
                           "next_tx_value": next_tx_value,
                           "next_tx_order_type": next_tx_order_type})})
        tx_data = token_contract.encodeABI(fn_name="approve", args=[opensea_conduit.address, price])

        tx = {
            "to": token_contract.address,
            "from": user_address,
            "data": compress_string_to_url(tx_data),
            "value": 0
        }

        tx_url = get_tx_page_url(tx_key, tx)

        token_symbol = token_name.upper()
        embed = Embed(
            title=f"Approve OpenSea to transfer {token_symbol}",
            description=f"In order to approve `{token_symbol}` transfers, {tx_link_instruction_text}",
            fields=[{"name": "ENS name", "value": ens_name, "inline": True},
                    {"name": "Price",
                     "value": f"{format_wei_price(price, token_name)} {token_symbol}",
                     "inline": True},
                    {"name": "Current Allowance",
                     "value": f"{format_wei_price(allowance, token_name)} {token_symbol}",
                     "inline": True}],
            color=BrandColors.GREEN,
            url=tx_url)

        return await ctx.send(
            f"To proceed with the purchase of `{ens_name}`, we first need your authorization to allow OpenSea to "
            f"transfer `{token_symbol}` from your Ethereum address.",
            embeds=embed, ephemeral=True)
    except Exception as e:
        await ctx.send(f"I'm sorry, but an error occurred while trying to approve transactions for `{token_symbol}`.",
                       ephemeral=True)
        logger.error(f"approve_erc20 exception {str(e)}")
        raise e


async def send_buy_tx_url(ctx, ens_name, price, token_name, tx_to, tx_from, tx_data, tx_value, ctx_author_id,
                          ctx_channel_id, order_type, expiration_time, highest_bid):
    try:
        seaport = web3.eth.contract(address=tx_to, abi=seaport_abi)

        tx = {
            "to": tx_to,
            "from": tx_from,
            "data": compress_string_to_url(tx_data),
            "value": tx_value
        }
        tx_key = generate_tx_key()
        tx_url = get_tx_page_url(tx_key, tx, sign_spec="OrderComponents" if order_type == "english" else None)
        formatted_price = format_wei_price(price, token_name)
        token_symbol = token_name.upper()
        expiration_datetime = datetime.fromtimestamp(expiration_time)
        formatted_expiration = expiration_datetime.strftime("%Y-%m-%d %H:%M:%S")

        tx_db.add_tx(
            {"tx_key": tx_key,
             "user": ctx_author_id,
             "action": "bid" if order_type == "english" else "buy",
             "channel": ctx_channel_id,
             "next_action_data": json.dumps(
                 {"ens_name": ens_name,
                  "formatted_price": formatted_price,
                  "token_name": token_name,
                  "order_type": order_type,
                  "expiration_time": expiration_time,
                  "order_params": tx_data if order_type == "english" else ""})})

        if order_type == "english":
            embed = Embed(
                title=f"Place a `{formatted_price} {token_symbol}` bid in the {ens_name} auction",
                description=f"In order to place a bid in the `{ens_name}` auction, {tx_link_instruction_text}",
                fields=[{"name": "ENS Name", "value": ens_name, "inline": True},
                        {"name": "Your Bid", "value": f"{formatted_price} {token_symbol}", "inline": True},
                        {"name": "Highest Bid",
                         "value": f"{format_wei_price(highest_bid, token_name)} {token_symbol}", "inline": True},
                        {"name": "Auction Ends", "value": formatted_expiration, "inline": True}],
                color=BrandColors.GREEN,
                url=tx_url)
            return await ctx.send(
                f"`{ens_name}` is currently in an auction! Place your bid before it ends "
                f"{format_time_remaining(expiration_datetime)}!",
                embeds=embed, ephemeral=True)
        else:
            embed = Embed(
                title=f"Buy `{ens_name}`",
                description=f"In order to buy `{ens_name}`, {tx_link_instruction_text}",
                fields=[{"name": "ENS Name", "value": ens_name, "inline": True},
                        {"name": "Price", "value": f"{formatted_price} {token_symbol}", "inline": True},
                        {"name": "Offer Ends", "value": formatted_expiration}],
                color=BrandColors.GREEN,
                url=tx_url)
            return await ctx.send(f"You're about to own `{ens_name}`!", embeds=embed, ephemeral=True)


    except Exception as e:
        await ctx.send(f"I'm sorry, but an error occurred while trying to initiate the purchase of `{ens_name}`.",
                       ephemeral=True)
        logger.error(f"send_buy_tx_url exception {str(e)}")
        raise e


async def _buy(ctx, ens_name, bid=None):
    try:
        ens_name = add_eth_suffix(ens_name)
        cured_name = ens_cure(ens_name)

        if not is_top_level_eth(cured_name):
            await ctx.send(f"Apologies, but at the moment, our support is limited to top-level .eth names only.",
                           ephemeral=True)
            return

        user_address = user_address_db.get_address(ctx.author_id)
        if user_address is None:
            await _link_wallet(ctx,
                               "To buy an ENS name, we need your Ethereum address associated with your Discord account.")
            return

        name_label = remove_eth_suffix(cured_name)

        label_hash = Web3.keccak(text=name_label)
        node = namehash(cured_name)
        unwrapped_token_id = int.from_bytes(label_hash, byteorder='big')
        wrapped_token_id = int.from_bytes(node, byteorder='big')
        is_wrapped = name_wrapper.functions.isWrapped(node).call()
        asset_contract_address = name_wrapper.address if is_wrapped else eth_registrar.address
        token_id = wrapped_token_id if is_wrapped else unwrapped_token_id

        url = f"{get_opensea_url('listings')}?" \
              f"asset_contract_address={asset_contract_address}&" \
              f"token_ids={token_id}&" \
              f"order_by=eth_price&" \
              f"order_direction=asc&" \
              f"limit=1"

        response = await http_client.get(url, headers=os_api_headers)

        listings = response.json()

        if not "orders" in listings or len(listings["orders"]) == 0:
            return await ctx.send(f"It appears that `{cured_name}` is not currently listed for sale on OpenSea.",
                                  ephemeral=True)

        # logger.info(listings)

        cheapest_order = listings["orders"][0]
        order_hash = cheapest_order["order_hash"]
        protocol_address = cheapest_order["protocol_address"]
        current_price = int(cheapest_order["current_price"])
        order_type = cheapest_order["order_type"]
        cons_token = cheapest_order["protocol_data"]["parameters"]["consideration"][0]["token"]
        expiration_time = cheapest_order["expiration_time"]

        url = get_opensea_url("fulfillment")

        payload = {
            "listing": {
                "hash": order_hash,
                "chain": "ethereum",
                "protocol_address": protocol_address
            },
            "fulfiller": {
                "address": user_address
            }
        }

        response = await http_client.post(url, json=payload, headers=os_api_headers)
        fulfillment = response.json()

        # logger.info("----------------------------------------")
        # logger.info(fulfillment)

        tx_to = Web3.to_checksum_address(fulfillment["fulfillment_data"]["transaction"]["to"])
        fn_signature = fulfillment["fulfillment_data"]["transaction"]["function"]
        fn_name = fn_signature.split("(")[0]
        tx_value = int(fulfillment["fulfillment_data"]["transaction"]["value"])
        highest_bid = 0
        (cons_token_name, cons_token_contract) = get_consideration_token_contract(cons_token)

        if order_type == "basic":
            parameters = fulfillment["fulfillment_data"]["transaction"]["input_data"]["parameters"]
            args = prepare_tx_args(parameters)
            tx_data = seaport.encodeABI(fn_name=fn_name, args=[list(args)])
        elif order_type == "dutch":
            order = fulfillment["fulfillment_data"]["transaction"]["input_data"]["order"]
            fulfiller_conduit_key = fulfillment["fulfillment_data"]["transaction"]["input_data"]["fulfillerConduitKey"]
            order_args = prepare_tx_args(order)
            tx_data = seaport.encodeABI(fn_name=fn_name, args=[list(order_args), fulfiller_conduit_key])
        elif order_type == "english":
            url = f"{get_opensea_url('offers')}?" \
                  f"asset_contract_address={asset_contract_address}&" \
                  f"token_ids={token_id}&" \
                  f"order_by=eth_price&" \
                  f"order_direction=desc&" \
                  f"limit=1"

            response = await http_client.get(url, headers=os_api_headers)
            offers = response.json()

            bid_wei = None
            if bid is not None:
                bid_wei = safe_to_wei(bid, cons_token_name)

            if "orders" in offers and len(offers["orders"]) > 0:
                highest_bid = int(offers["orders"][0]["protocol_data"]["parameters"]["offer"][0]["startAmount"])

                if bid_wei and highest_bid >= bid_wei:
                    return await ctx.send(
                        f"Sorry, but your bid is not higher than the currently highest bid of ",
                        ephemeral=True)

                current_price = highest_bid + current_price

            (_, _, os_fee_start_price, _) = get_order_prices(current_price, unit="wei")
            order_params = get_order_parameters(
                offerer=user_address,
                offer_item_type=1,
                offer_token=cons_token,
                offer_token_id=0,
                offer_start_amount=current_price,
                offer_end_amount=current_price,
                cons_item_type=3 if is_wrapped else 2,
                cons_token=name_wrapper.address if is_wrapped else eth_registrar.address,
                cons_token_id=wrapped_token_id if is_wrapped else unwrapped_token_id,
                cons_start_amount=1,
                cons_end_amount=1,
                cons_recepient=user_address,
                os_cons_item_type=1,
                os_cons_token=cons_token,
                os_cons_start_amount=os_fee_start_price,
                os_cons_end_amount=os_fee_start_price,
                start_time=int(datetime.now().timestamp()),
                end_time=int(expiration_time) + 604800,  # + 1 week
                order_type=0)
            tx_data = json.dumps(order_params)

        if cons_token_name != "eth":
            allowance = int(cons_token_contract.functions.allowance(user_address, opensea_conduit.address).call())

            if allowance < current_price:
                return await approve_erc20_allowance(
                    ctx=ctx,
                    ens_name=cured_name,
                    user_address=user_address,
                    price=current_price,
                    allowance=allowance,
                    token_name=cons_token_name,
                    token_contract=cons_token_contract,
                    expiration_time=expiration_time,
                    highest_bid=highest_bid,
                    next_tx_to=tx_to,
                    next_tx_data=tx_data,
                    next_tx_value=tx_value,
                    next_tx_order_type=order_type)

        return await send_buy_tx_url(
            ctx=ctx,
            ens_name=cured_name,
            price=current_price,
            tx_to=tx_to,
            order_type=order_type,
            token_name=cons_token_name,
            expiration_time=expiration_time,
            highest_bid=highest_bid,
            tx_from=user_address,
            tx_data=tx_data,
            tx_value=tx_value,
            ctx_author_id=ctx.author_id,
            ctx_channel_id=ctx.channel_id)

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
@slash_option(
    name="bid",
    description="When participating in auctions, you can choose to specify your bid or let it be automatically calculated.",
    required=False,
    opt_type=OptionType.NUMBER,
)
async def buy(ctx: SlashContext, ens_name, bid):
    await _buy(ctx, ens_name, bid)


@component_callback(re.compile(r"^buy_btn_"))
async def my_callback(ctx: ComponentContext):
    ens_name = re.sub(r"^buy_btn_", "", ctx.custom_id)
    await _buy(ctx, ens_name)


@slash_command(name="test", description="This command is for testing purposes")
async def test(ctx: SlashContext):
    await ctx.send("This is just a test")


async def _link_wallet(ctx: SlashContext, ctx_message):
    tx_key = generate_tx_key()

    json_data = json.dumps({"username": ctx.author.tag})

    tx_db.add_tx({"tx_key": tx_key,
                  "user": ctx.author_id,
                  "action": "link_wallet",
                  "channel": ctx.channel_id,
                  "next_action_data": json_data})

    tx = {
        "to": "",
        "data": compress_string_to_url(json_data),
        "value": 0
    }

    tx_url = get_tx_page_url(tx_key, tx, sign_spec="LinkWallet")

    embed = Embed(
        title=f"Link your Ethereum address with NameBazaarBot",
        description=f"In order to link your Ethereum address, {tx_link_instruction_text}",
        color=BrandColors.GREEN,
        url=tx_url)

    await ctx.send(ctx_message, embeds=embed, ephemeral=True)


@slash_command(name="link_wallet", description="Link your Ethereum address to your Discord account.")
async def link_wallet(ctx: SlashContext):
    await _link_wallet(ctx, "Let's get this linking stuff done, so we can start trading!")


@slash_command(name="unlink_wallet", description="Unlink your Ethereum address from your Discord account.")
async def unlink_wallet(ctx: SlashContext):
    user_address_db.remove_user(ctx.author_id)
    await ctx.send(f"Your Ethereum address was successfully unlinked from your Discord account.", ephemeral=True)


async def _approve_opensea(ctx: SlashContext, user_address, nft_contract, ens_name, token_id, is_wrapped, start_price,
                           end_price, duration_days):
    tx_key = generate_tx_key()

    tx_db.add_tx({"tx_key": tx_key,
                  "user": ctx.author_id,
                  "action": "approve_opensea",
                  "channel": ctx.channel_id,
                  "next_action_data": json.dumps({"ens_name": ens_name,
                                                  "user_address": user_address,
                                                  "start_price": start_price,
                                                  "end_price": end_price,
                                                  "duration_days": duration_days,
                                                  "token_id": token_id,
                                                  "is_wrapped": is_wrapped})})

    tx_data = nft_contract.encodeABI(fn_name="setApprovalForAll", args=[opensea_conduit.address, True])

    tx = {
        "to": nft_contract.address,
        "from": user_address,
        "data": compress_string_to_url(tx_data),
        "value": 0
    }

    tx_url = get_tx_page_url(tx_key, tx)

    embed = Embed(
        title=f"Approve OpenSea to transfer ENS names",
        description=f"This will open your MetaMask...",
        color=BrandColors.GREEN,
        url=tx_url
    )

    return await ctx.send(
        "In order to sell this name, you will need to perform the following approval transaction for OpenSea.",
        embeds=embed, ephemeral=True)


def get_order_start_end_times(duration_days):
    start_time = int(datetime.now().timestamp())
    end_time = int((datetime.now() + datetime.timedelta(days=duration_days)).timestamp())
    return (start_time, end_time)


def get_order_prices(start_price, end_price=None, unit="ether"):
    if end_price is None:
        end_price = start_price

    start_price_wei = Web3.to_wei(start_price, unit)
    owner_start_price, os_fee_start_price = split_opensea_consideration(start_price_wei)
    if start_price == end_price:
        end_price_wei = start_price_wei
        owner_end_price = owner_start_price
        os_fee_end_price = os_fee_start_price
    else:
        end_price_wei = Web3.to_wei(end_price, unit)
        owner_end_price, os_fee_end_price = split_opensea_consideration(end_price_wei)

    return (owner_start_price, owner_end_price, os_fee_start_price, os_fee_end_price)


def get_order_parameters(offerer, offer_item_type, offer_token, offer_token_id, offer_start_amount, offer_end_amount,
                         cons_item_type, cons_token, cons_token_id, cons_start_amount, cons_end_amount, cons_recepient,
                         os_cons_item_type, os_cons_token, os_cons_start_amount, os_cons_end_amount, start_time,
                         end_time, order_type):
    return {
        "offerer": offerer,
        "offer": [{
            "itemType": offer_item_type,
            "token": offer_token,
            "identifierOrCriteria": str(offer_token_id),
            "startAmount": str(offer_start_amount),
            "endAmount": str(offer_end_amount)
        }],
        "consideration": [{
            "itemType": cons_item_type,
            "token": cons_token,
            "identifierOrCriteria": str(cons_token_id),
            "startAmount": str(cons_start_amount),
            "endAmount": str(cons_end_amount),
            "recipient": cons_recepient,
        }, {  ## OpenSea Fees have to be defined, at least 2.5%
            "itemType": os_cons_item_type,
            "token": os_cons_token,
            "identifierOrCriteria": 0,
            "startAmount": str(os_cons_start_amount),
            "endAmount": str(os_cons_end_amount),
            "recipient": "0x0000a26b00c1F0DF003000390027140000fAa719",
        }],
        "totalOriginalConsiderationItems": 2,
        "startTime": start_time,
        "endTime": end_time,
        "orderType": order_type,
        "zone": "0x004C00500000aD104D7DBd00e3ae0A5C00560C00",
        "zoneHash": "0x0000000000000000000000000000000000000000000000000000000000000000",
        "salt": str(generate_opensea_salt()),
        "conduitKey": "0x0000007b02230091a7ed01230072f7006a004d60a8d4e71d599b8104250f0000",
        "counter": 0,
    }


async def send_sell_sign_url(ctx, token_id, ens_name, user_address, is_wrapped, start_price, end_price, duration_days,
                             ctx_author_id, ctx_channel_id, ctx_message=""):
    start_time, end_time = get_order_start_end_times(duration_days)
    owner_start_price, owner_end_price, os_fee_start_price, os_fee_end_price = get_order_prices(start_price, end_price)

    order_params = get_order_parameters(
        offerer=user_address,
        offer_item_type=3 if is_wrapped else 2,
        offer_token=name_wrapper.address if is_wrapped else eth_registrar.address,
        offer_token_id=token_id,
        offer_start_amount=1,
        offer_end_amount=1,
        cons_item_type=0,
        cons_token="0x0000000000000000000000000000000000000000",
        cons_token_id=0,
        cons_start_amount=owner_start_price,
        cons_end_amount=owner_end_price,
        cons_recepient=user_address,
        os_cons_item_type=0,
        os_cons_token="0x0000000000000000000000000000000000000000",
        os_cons_start_amount=os_fee_start_price,
        os_cons_end_amount=os_fee_end_price,
        start_time=start_time,
        end_time=end_time,
        order_type=1)

    order_params_json = json.dumps(order_params)

    tx = {
        "to": seaport.address,
        "from": user_address,
        "data": compress_string_to_url(order_params_json),
        "value": 0
    }

    tx_key = generate_tx_key()
    tx_url = get_tx_page_url(tx_key, tx, sign_spec="OSCreateListing")

    tx_db.add_tx({"tx_key": tx_key,
                  "user": ctx_author_id,
                  "action": "sell",
                  "channel": ctx_channel_id,
                  "next_action_data": order_params_json})

    embed = Embed(
        title=f"Sign the sales contract for `{ens_name}`",
        description=f"To initiate the selling process for `{ens_name}`, {tx_link_instruction_text}",
        color=BrandColors.GREEN,
        url=tx_url)

    return await ctx.send(ctx_message, embeds=embed, ephemeral=True)


async def send_bid_sign_url(ctx,
                            token_id, ens_name, user_address, is_wrapped, start_price, end_price, duration_days,
                            ctx_author_id, ctx_channel_id, ctx_message=""):
    start_time, end_time = get_order_start_end_times(duration_days)
    owner_start_price, owner_end_price, os_fee_start_price, os_fee_end_price = get_order_prices(start_price, end_price)

    order_params = get_order_parameters(
        offerer=user_address,
        offer_item_type=1,
        offer_token=name_wrapper.address if is_wrapped else eth_registrar.address,
        offer_token_id=token_id,
        offer_start_amount=1,
        offer_end_amount=1,
        cons_item_type=0,
        cons_token="0x0000000000000000000000000000000000000000",
        cons_token_id=0,
        cons_start_amount=owner_start_price,
        cons_end_amount=owner_end_price,
        cons_recepient=user_address,
        os_cons_item_type=0,
        os_cons_token="0x0000000000000000000000000000000000000000",
        os_cons_start_amount=os_fee_start_price,
        os_cons_end_amount=os_fee_end_price,
        start_time=start_time,
        end_time=end_time,
        order_type=1)

    order_params_json = json.dumps(order_params)

    tx = {
        "to": seaport.address,
        "from": user_address,
        "data": compress_string_to_url(order_params_json),
        "value": 0
    }

    tx_key = generate_tx_key()
    tx_url = get_tx_page_url(tx_key, tx, sign_spec="OSCreateListing")

    tx_db.add_tx({"tx_key": tx_key,
                  "user": ctx_author_id,
                  "action": "sell",
                  "channel": ctx_channel_id,
                  "next_action_data": order_params_json})

    embed = Embed(
        title=f"Sign the sales contract for `{ens_name}`",
        description=f"To initiate the selling process for `{ens_name}`, {tx_link_instruction_text}",
        color=BrandColors.GREEN,
        url=tx_url)

    return await ctx.send(ctx_message, embeds=embed, ephemeral=True)


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
        user_address = user_address_db.get_address(ctx.author_id)
        if user_address is None:
            await _link_wallet(ctx,
                               "In order to facilitate the sale of your ENS name, we need your Ethereum address associated with your Discord account.")
            return

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

        if owner is None or owner.lower() != user_address.lower():
            await ctx.send(f"It appears that you don't own `{cured_name}`.", ephemeral=True)
            return

        nft_contract = name_wrapper if is_wrapped else eth_registrar
        is_approved = nft_contract.functions.isApprovedForAll(user_address, opensea_conduit.address).call()

        if not is_approved:
            await _approve_opensea(ctx=ctx,
                                   user_address=user_address,
                                   ens_name=ens_name,
                                   token_id=token_id,
                                   is_wrapped=is_wrapped,
                                   nft_contract=nft_contract,
                                   start_price=start_price,
                                   end_price=end_price,
                                   duration_days=duration_days)
            return

        return await send_sell_sign_url(ctx=ctx,
                                        user_address=user_address,
                                        ens_name=ens_name,
                                        token_id=token_id,
                                        is_wrapped=is_wrapped,
                                        start_price=start_price,
                                        end_price=end_price,
                                        duration_days=duration_days,
                                        ctx_author_id=ctx.author_id,
                                        ctx_channel_id=ctx.channel_id)
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

        logger.info(f"datA: {data}")

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
                return await ctx.send(f"```\n{formatted_names}```", ephemeral=True)
            else:
                return await ctx.send("Apologies, but no matching account was found for this address", ephemeral=True)
        else:
            return ctx.send(
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


@slash_command(name="my_names", description="Shows list of names owned by your linked wallet address")
async def my_names(ctx: SlashContext):
    try:
        user_address = user_address_db.get_address(ctx.author_id)
        if user_address is None:
            await _link_wallet(ctx,
                               "To display your owned ENS names, it requires your Ethereum address linked to your Discord account.")
        else:
            await _owned_names(ctx, user_address)
    except Exception as e:
        logger.error(f"my_names {str(e)}")
        await ctx.respond('An error occurred: {}'.format(str(e)))
        raise e


@slash_command(name="my_wallet", description="Shows your currently linked wallet address")
async def my_wallet(ctx: SlashContext):
    user_address = user_address_db.get_address(ctx.author_id)
    if user_address is None:
        await ctx.send("You currently don't have any Ethereum address linked with your Discord account.",
                       ephemeral=True)
    else:
        await ctx.send(f"Your currently linked address is: `{user_address}`", ephemeral=True)


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

    try:
        user_address = user_address_db.get_address(ctx.author_id)
        if user_address is None:
            await _link_wallet(ctx,
                               "To register your ENS name, we need your Ethereum address associated with your Discord account.")
            return

        ens_name = add_eth_suffix(ens_name)
        cured_name = ens_cure(ens_name)
        name_label = remove_eth_suffix(cured_name)

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
        set_addr_data = public_resolver.encodeABI(fn_name="setAddr", args=[node, user_address])[2:]

        salt_bytes = os.urandom(32)

        commitment = eth_registrar_controller.functions.makeCommitment(
            name_label,
            user_address,
            register_duration,
            salt_bytes,
            public_resolver.address,
            [bytes.fromhex(set_addr_data)],
            False,
            0
        ).call()

        tx = {
            "to": eth_registrar_controller.address,
            "from": user_address,
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
                                                      "owner_address": user_address,
                                                      "register_duration": register_duration,
                                                      "salt_hex": salt_bytes.hex(),
                                                      "set_addr_data": set_addr_data})})

        embed = Embed(
            title=f"Begin Registration for `{cured_name}`",
            description=f"To initiate the registration process for `{cured_name}`, {tx_link_instruction_text}",
            color=BrandColors.GREEN,
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
            "from": owner_address,
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
            description=f"To complete the registration process for `{ens_name}`, {tx_link_instruction_text}",
            fields=[{"name": "Registration length", "value": "1 year", "inline": True},
                    {"name": "Price", "value": f"{format_wei_price(rent_price_wei)} ETH", "inline": True}],
            color=BrandColors.GREEN,
            url=tx_url
        )

        await user.send(f"Great! Now you are just a step away from registering `{ens_name}`. ", embeds=embed)
    except Exception as e:
        logger.error(f"Error in send_register_finish_url {str(e)}")
        raise e


async def commit_callback(tx, tx_hash, next_action_data):
    try:
        await wait_for_receipt(tx_hash)
        user = bot.get_user(int(tx["user"]))
        await user.send(f"The registration for `{add_eth_suffix(next_action_data['name_label'])}` is underway. "
                        f"We must wait for 1 minute to complete the registration process.")
        await asyncio.sleep(61)  # The second step of the registration can be done only after 60 seconds
        await send_register_finish_url \
            (name_label=next_action_data["name_label"],
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
        channel = bot.get_channel(int(tx["channel"]))
        await channel.send(
            f"Great news! `{next_action_data['ens_name']}` is now owned by {mention(tx['user'])}, who can now proudly call it their own!")
    except Exception as e:
        logger.error(f"Error in register_callback {str(e)}")
        raise e


async def bid_callback(tx, tx_signature, next_action_data):
    try:
        channel = bot.get_channel(int(tx["channel"]))
        user = bot.get_user(int(tx["user"]))

        ctx_author = tx["user"]

        order_params = {
            "parameters": json.loads(next_action_data["order_params"]),
            "signature": tx_signature,
            "protocol_address": get_contract_address("Seaport")
        }

        response = await http_client.post(get_opensea_url("offers"), json=order_params, headers=os_api_headers)
        response = response.json()

        if "errors" in response:
            await user.send(
                f"Apologies, an error occurred while attempting to send your order to OpenSea.\n"
                f"```{response['errors'][0]}```")
            return

        ens_name = next_action_data["ens_name"]
        formatted_price = next_action_data["formatted_price"]
        token_name = next_action_data["token_name"]
        expiration_datetime = datetime.fromtimestamp(next_action_data["expiration_time"])

        components = Button(
            style=ButtonStyle.GREEN,
            emoji="🤑",
            label=f"Place a bid",
            custom_id=f"buy_btn_{ens_name}",
        )

        return await channel.send(
            f"Exciting news! {user.mention} has just placed the highest bid of `{formatted_price} {token_name.upper()}` "
            f"in the auction for `{ens_name}`! Don't miss out and place your bid before the auction ends "
            f"{format_time_remaining(expiration_datetime)}!", components=components)
    except Exception as e:
        logger.error(f"Error in buy_callback {str(e)}")
        raise e


async def buy_callback(tx, tx_hash, next_action_data):
    try:
        await wait_for_receipt(tx_hash)
        channel = bot.get_channel(int(tx["channel"]))
        ens_name = next_action_data["ens_name"]
        formatted_price = next_action_data["formatted_price"]
        token_name = next_action_data["token_name"]
        ctx_author = tx["user"]
        return await channel.send(
            f"Exciting announcement! `{ens_name}` has been successfully purchased by {mention(ctx_author)} "
            f"for `{formatted_price} {token_name.upper()}`!")
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

        response = await http_client.post(get_opensea_url('listings'), json=order_params, headers=os_api_headers)
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
        expiration_date = datetime.fromtimestamp(order["expiration_time"])
        logger.info(f"asset: {asset}")

        price = format_wei_price(order["current_price"])

        if ens_name is None:
            ens_name = f"#{str(token_id)[:10]}"

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


async def link_wallet_callback(tx, tx_signature, message, next_action_data):
    try:
        user = bot.get_user(int(tx["user"]))

        message = encode_defunct(hexstr=message)
        message_hash = _hash_eip191_message(message)
        hex_message_hash = Web3.to_hex(message_hash)
        sig = Web3.to_bytes(hexstr=tx_signature)
        v, hex_r, hex_s = Web3.to_int(sig[-1]), Web3.to_hex(sig[:32]), Web3.to_hex(sig[32:64])

        signer = recover.functions.ecr(hex_message_hash, v, hex_r, hex_s).call()

        if not Web3.is_address(signer):
            await user.send(f"We apologize, but we were unable to retrieve the Ethereum address from your signature.")
            logger.error(f"Invalid address recovered from signature: {signer}")
            return

        user_address_db.add_user_address(tx["user"], Web3.to_checksum_address(signer), tx["tx_key"], tx_signature)

        await user.send(
            f"Thank you. Your Ethereum address `{signer}` has been successfully linked with your Discord account. "
            f"Feel free to start trading some ENS names now!")
    except Exception as e:
        logger.error(f"link_wallet_callback {str(e)}")
        raise e


async def approve_opensea_callback(tx, tx_hash, next_action_data):
    try:
        await wait_for_receipt(tx_hash)
        user = bot.get_user(int(tx["user"]))
        message = f"With the approval complete, we can now proceed to sell `{next_action_data['ens_name']}`."
        return await send_sell_sign_url(
            ctx=user,
            start_price=next_action_data["start_price"],
            end_price=next_action_data["end_price"],
            duration_days=next_action_data["duration_days"],
            user_address=next_action_data["user_address"],
            ens_name=next_action_data["ens_name"],
            token_id=next_action_data["token_id"],
            is_wrapped=next_action_data["is_wrapped"],
            ctx_author_id=tx["user"],
            ctx_channel_id=tx["channel"],
            ctx_message=message)
    except Exception as e:
        logger.error(f"Error in approve_opensea_callback {str(e)}")
        raise e


async def approve_erc20_allowance_callback(tx, tx_hash, next_action_data):
    try:
        await wait_for_receipt(tx_hash)
        user = bot.get_user(int(tx["user"]))
        return await send_buy_tx_url(
            ctx=user,
            ens_name=next_action_data["ens_name"],
            price=next_action_data["price"],
            token_name=next_action_data["token_name"],
            tx_to=next_action_data["next_tx_to"],
            tx_from=next_action_data["next_tx_from"],
            tx_data=next_action_data["next_tx_data"],
            tx_value=next_action_data["next_tx_value"],
            tx_order_type=next_action_data["next_tx_order_type"],
            highest_bid=next_action_data["highest_bid"],
            expiration_time=next_action_data["expiration_time"],
            ctx_author_id=tx["user"],
            ctx_channel_id=tx["channel"])
    except Exception as e:
        logger.error(f"Error in approve_erc20_allowance_callback {str(e)}")
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

    if tx_db.tx_result_exists(tx_key):
        abort(409, description="This transaction has already been processed")

    tx_db.update_tx_result(tx_key, tx_result)
    tx = tx_db.get_tx(tx_key)

    next_action_data = json.loads(tx["next_action_data"])

    if tx["action"] == "commit":
        asyncio.create_task(commit_callback(tx, tx_result, next_action_data))
    elif tx["action"] == "register":
        asyncio.create_task(register_callback(tx, tx_result, next_action_data))
    elif tx["action"] == "buy":
        asyncio.create_task(buy_callback(tx, tx_result, next_action_data))
    elif tx["action"] == "bid":
        asyncio.create_task(bid_callback(tx, tx_result, next_action_data))
    elif tx["action"] == "sell":
        asyncio.create_task(sell_callback(tx, tx_result, next_action_data))
    elif tx["action"] == "approve_opensea":
        asyncio.create_task(approve_opensea_callback(tx, tx_result, next_action_data))
    elif tx["action"] == "approve_erc20_allowance":
        asyncio.create_task(approve_erc20_allowance_callback(tx, tx_result, next_action_data))
    elif tx["action"] == "link_wallet":
        asyncio.create_task(link_wallet_callback(tx, tx_result, json_data["message"], next_action_data))

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
