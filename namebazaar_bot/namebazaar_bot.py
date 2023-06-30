import asyncio
import binascii
from datetime import datetime, timedelta
import json
import logging
import os
import re
import websockets
from dotenv import load_dotenv
from ens_normalize import ens_cure, DisallowedNameError
from interactions import listen, Client, Intents, slash_command, slash_option, SlashContext, OptionType, \
    component_callback, ComponentContext, auto_defer
from interactions.models.discord import Embed, BrandColors, ButtonStyle, Button
from web3 import Web3
from eth_account.messages import encode_defunct, _hash_eip191_message
from decimal import Decimal, ROUND_DOWN
from quart import Quart, request, jsonify, abort
import nest_asyncio
from db.tx_db import TxDB
from db.user_address_db import UserAddressDB
from quart_cors import cors
import httpx
import httpx_cache
import discord_opensea.discord_opensea as discord_opensea
import discord_web3.discord_web3 as discord_web3
import discord_utils.discord_utils as discord_utils
from discord_utils.discord_utils import mention, with_probability
from discord_web3.discord_web3 import get_contract, get_tx_page_url
from discord_opensea.discord_opensea import AssetType

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("namebazaar_bot")

namebazaar_bot_token = os.getenv('NAMEBAZAAR_BOT_TOKEN')
namebazaar_bot_client_id = os.getenv('NAMEBAZAAR_BOT_CLIENT_ID')
discord_opensea.api_key = os.getenv('OPENSEA_API_KEY')
discord_web3.etherscan_api_key = os.getenv('ETHERSCAN_API_KEY')
infura_url = os.getenv('INFURA_URL')
discord_web3.tx_page_url = os.getenv('TX_PAGE_URL')
discord_web3.server_host = os.getenv('SERVER_HOST')
discord_web3.server_port = os.getenv('SERVER_PORT')
discord_web3.tx_check_interval = int(os.getenv('TX_CHECK_INTERVAL'))
stream_channel_id = int(os.getenv('STREAM_CHANNEL_ID'))
discord_opensea.stream_interval = int(os.getenv('STREAM_INTERVAL'))
db_path = os.getenv('SQLITE_DB_PATH')

contract_addresses = {  # Make sure addresses are checksum format
    "ETHRegistrarController": "0x253553366Da8546fC250F225fe3d25d0C782303b",
    "ETHRegistrar": "0x57f1887a8BF19b14fC0dF6Fd9B2acc9Af147eA85",
    "ENSRegistry": "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e",
    "PublicResolver": "0x231b0Ee14048e9dCcD1d247744d114a4EB5E8E63",
    "NameWrapper": "0xD4416b13d2b3a9aBae7AcD5D6C2BbDBE25686401"
}

subgraph_url = "https://api.thegraph.com/subgraphs/name/ensdomains/ens"

intents = Intents.DEFAULT
intents.messages = True
intents.guilds = True
intents.message_content = True
intents.members = True

tx_db = TxDB(db_path)
user_address_db = UserAddressDB(db_path)
bot = Client(intents=intents)


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

    if len(parts) == 3 and parts[1] == "eth⚠" and parts[2] == "eth":
        return True

    return False


web3 = discord_web3.get_ws_web3(infura_url)

eth_registrar_controller = get_contract(web3, contract_addresses["ETHRegistrarController"], "ETHRegistrarController")
eth_registrar = get_contract(web3, contract_addresses["ETHRegistrar"], "ETHRegistrar")
public_resolver = get_contract(web3, contract_addresses["PublicResolver"], "PublicResolver")
name_wrapper = get_contract(web3, contract_addresses["NameWrapper"], "NameWrapper")
ens_registry = get_contract(web3, contract_addresses["ENSRegistry"], "ENSRegistry")


def namehash(name):
    if name == '':
        return b'\0' * 32
    else:
        label, _, remainder = name.partition('.')
        return Web3.keccak(namehash(remainder) + Web3.keccak(text=label))


def cure_emoji_name(ens_name):
    return re.sub(r"\.\w+⚠", "", ens_name)


http_client = httpx.AsyncClient()
http_cache_client = httpx_cache.AsyncClient()


def get_ens_token(ens_name):
    name_label = remove_eth_suffix(ens_name)
    label_hash = Web3.keccak(text=name_label)
    node = namehash(ens_name)
    unwrapped_token_id = int.from_bytes(label_hash, byteorder='big')
    wrapped_token_id = int.from_bytes(node, byteorder='big')
    is_wrapped = name_wrapper.functions.isWrapped(node).call()
    asset_contract_address = name_wrapper.address if is_wrapped else eth_registrar.address
    token_id = wrapped_token_id if is_wrapped else unwrapped_token_id
    return (asset_contract_address, token_id, is_wrapped)


async def get_ens_name_owner(ens_name):
    name_label = remove_eth_suffix(ens_name)
    node = namehash(ens_name)
    hex_node = node.hex()
    label_hash = Web3.keccak(text=name_label)
    token_id = int.from_bytes(label_hash, byteorder='big')
    hex_label = hex(token_id)

    query = f"""{{registration(
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

    return owner, token_id, is_wrapped


async def send_invalid_name_msg(ctx, ens_name):
    return await ctx.send(f"I apologize, but the name `{ens_name}` is not a valid ENS name.", ephemeral=True)


def item_received_bid_filter(payload):
    asset_name = payload.get("item", {}).get("metadata", {}).get("name", "")
    if re.search(r"\b\d{3,100}\.eth\b", asset_name) and with_probability(980):  # There's way too many of these
        return False
    return True


def item_listed_filter(payload):
    return with_probability(750)


@listen()
async def on_ready():
    # ready events pass no data, so dont have params
    logger.info("NamebazaarBot is ready")
    await discord_opensea.start_stream(bot, stream_channel_id, {"item_received_bid": item_received_bid_filter,
                                                                "item_listed": item_listed_filter})


@slash_command(name="buy", description="Buy ENS name from OpenSea")
@auto_defer(ephemeral=True)
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
    description="You can optionally make an offer, which will be auto-calculated if left empty for auctions.",
    required=False,
    opt_type=OptionType.NUMBER,
)
@slash_option(
    name="currency",
    description="Specify your bid currency. Default is the cheapest listing's currency.",
    required=False,
    opt_type=OptionType.STRING,
    choices=discord_opensea.currency_choices)
async def buy(ctx: SlashContext, ens_name, bid=None, currency=None):
    try:
        asset_name = add_eth_suffix(ens_name)
        cured_name = cure_emoji_name(ens_cure(asset_name))

        if not is_top_level_eth(cured_name):
            await ctx.send(f"Apologies, but at the moment, our support is limited to top-level .eth names only.",
                           ephemeral=True)
            return

        asset_contract_address, token_id, is_wrapped = get_ens_token(cured_name)

        return await discord_opensea.buy(
            ctx=ctx,
            web3=web3,
            user_address_db=user_address_db,
            tx_db=tx_db,
            asset_name=cured_name,
            asset_contract_address=asset_contract_address,
            token_id=token_id,
            asset_type=AssetType.ERC1155 if is_wrapped else AssetType.ERC721,
            bid=bid,
            currency=currency)
    except DisallowedNameError as e:
        await send_invalid_name_msg(ctx, asset_name)


@component_callback(re.compile(r"^buy_btn_"))
async def buy_btn_callback(ctx: ComponentContext):
    ens_name = re.sub(r"^buy_btn_", "", ctx.custom_id)
    await ctx.defer(ephemeral=True)

    asset_contract_address, token_id, is_wrapped = get_ens_token(ens_name)

    return await discord_opensea.buy(
        ctx=ctx,
        web3=web3,
        user_address_db=user_address_db,
        tx_db=tx_db,
        asset_name=ens_name,
        token_id=token_id,
        asset_contract_address=asset_contract_address,
        asset_type=AssetType.ERC1155 if is_wrapped else AssetType.ERC721)


@component_callback(re.compile(r"^offer_btn_"))
async def offer_btn_callback(ctx: ComponentContext):
    ens_name = re.sub(r"^offer_btn_([\d.]+)_(\w{3,4})_", "", ctx.custom_id)
    match = re.match(r"offer_btn_([\d.]+)_(\w{3,4})_", ctx.custom_id)

    if match:
        price = match.group(1)
        token_name = match.group(2)
        await ctx.defer(ephemeral=True)

        asset_contract_address, token_id, is_wrapped = get_ens_token(ens_name)

        return await discord_opensea.buy(
            ctx=ctx,
            web3=web3,
            user_address_db=user_address_db,
            tx_db=tx_db,
            asset_name=ens_name,
            token_id=token_id,
            asset_contract_address=asset_contract_address,
            asset_type=AssetType.ERC1155 if is_wrapped else AssetType.ERC721,
            bid=price,
            currency=token_name,
            force_bid=True)
    else:
        await ctx.send("Sorry, there's a problem with this action", ephemeral=True)


@slash_command(name="offers", description="List of offers/bid for a given ENS name")
@auto_defer(ephemeral=True)
@slash_option(
    name="ens_name",
    description="Please provide the ENS name that you wish to get offers for.",
    required=True,
    opt_type=OptionType.STRING,
    max_length=100,
    min_length=3)
async def offers(ctx: SlashContext, ens_name):
    try:
        ens_name = add_eth_suffix(ens_name)
        cured_name = cure_emoji_name(ens_cure(ens_name))

        if not is_top_level_eth(cured_name):
            await ctx.send(f"Apologies, but at the moment, our support is limited to top-level .eth names only.",
                           ephemeral=True)
            return

        asset_contract_address, token_id, is_wrapped = get_ens_token(cured_name)
        owner, _, _ = await get_ens_name_owner(ens_name)

        return await discord_opensea.offers(
            bot=bot,
            ctx=ctx,
            user_address_db=user_address_db,
            tx_db=tx_db,
            web3=web3,
            asset_contract_address=asset_contract_address,
            token_id=token_id,
            asset_name=ens_name,
            asset_owner=owner)
    except DisallowedNameError as e:
        return await send_invalid_name_msg(ctx, ens_name)


@slash_command(name="link-wallet", description="Link your Ethereum address to your Discord account.")
async def link_wallet(ctx: SlashContext):
    return await discord_web3.link_wallet(ctx=ctx, tx_db=tx_db)


@slash_command(name="unlink-wallet", description="Unlink your Ethereum address from your Discord account.")
async def unlink_wallet(ctx: SlashContext):
    return await discord_web3.unlink_wallet(ctx=ctx, user_address_db=user_address_db)


@slash_command(name="sell", description="Sell your ENS name on OpenSea")
@auto_defer(ephemeral=True)
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
@slash_option(
    name="currency",
    description="Specify the selling currency for your ENS name (default is ETH).",
    required=False,
    opt_type=OptionType.STRING,
    choices=discord_opensea.currency_choices)
async def sell(ctx: SlashContext, ens_name, start_price, end_price=None, duration_days=100, currency="eth"):
    try:
        ens_name = add_eth_suffix(ens_name)
        cured_name = ens_cure(ens_name)

        if not is_top_level_eth(cured_name):
            return await ctx.send(f"Apologies, but at the moment, our support is limited to top-level .eth names only.",
                                  ephemeral=True)

        owner, token_id, is_wrapped = await get_ens_name_owner(cured_name)
        user_address = user_address_db.get_address(ctx.author_id)

        if owner is None or owner.lower() != user_address.lower():
            await ctx.send(f"It appears that you don't own `{cured_name}`.", ephemeral=True)
            return

        asset_contract = name_wrapper if is_wrapped else eth_registrar

        return await discord_opensea.sell(
            ctx=ctx,
            user_address_db=user_address_db,
            tx_db=tx_db,
            asset_name=cured_name,
            asset_type=AssetType.ERC1155 if is_wrapped else AssetType.ERC721,
            asset_contract=asset_contract,
            token_id=token_id,
            currency=currency,
            start_price=start_price,
            end_price=end_price,
            duration_days=duration_days)

    except DisallowedNameError as e:
        await send_invalid_name_msg(ctx, ens_name)
    except Exception as e:
        await ctx.send(f"I'm sorry, but an error occurred while trying to initiate the selling of `{cured_name}`.",
                       ephemeral=True)
        logger.error(f"Sell command exception {str(e)}")
        raise e


async def _owned_names(ctx: SlashContext, owner_address, flex=False):
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

                if flex:
                    flex_msg = f"Let's take a moment to admire the dazzling collection of ENS names owned by " \
                               f"{mention(ctx.author_id)}!\nWhat an incredible accomplishment! 💪💪💪\n"
                    return await ctx.send(f"{flex_msg}```\n{formatted_names}```")
                else:
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


@slash_command(name="owned-names", description="Shows list of names owned by a given address")
@auto_defer(ephemeral=True)
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


@slash_command(name="my-names", description="Shows list of names owned by your linked wallet address")
@auto_defer(ephemeral=True)
async def my_names(ctx: SlashContext):
    try:
        user_address = user_address_db.get_address(ctx.author_id)
        if user_address is None:
            return await discord_web3.link_wallet(
                ctx=ctx,
                tx_db=tx_db,
                message="To display your owned ENS names, it requires your Ethereum "
                        "address linked to your Discord account.")
        else:
            await _owned_names(ctx, user_address)
    except Exception as e:
        logger.error(f"my_names {str(e)}")
        await ctx.respond('An error occurred: {}'.format(str(e)))
        raise e


@slash_command(name="flex", description="Publicly display a list of the names you own. Show off your collection!")
@auto_defer(ephemeral=False)
async def flex(ctx: SlashContext):
    try:
        user_address = user_address_db.get_address(ctx.author_id)
        if user_address is None:
            return await discord_web3.link_wallet(
                ctx=ctx,
                tx_db=tx_db,
                message="To display your owned ENS names, it requires your Ethereum "
                        "address linked to your Discord account.")
        else:
            return await _owned_names(ctx, user_address, flex=True)
    except Exception as e:
        logger.error(f"flex {str(e)}")
        await ctx.respond('An error occurred: {}'.format(str(e)))
        raise e


@slash_command(name="my-wallet", description="Shows your currently linked wallet address")
async def my_wallet(ctx: SlashContext):
    return await discord_web3.my_wallet(ctx, user_address_db)


@slash_command(name="register", description="Registers ENS name")
@auto_defer(ephemeral=True)
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
                      "next_action_data":
                          json.dumps(
                              {"name_label": name_label,
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
        await send_invalid_name_msg(ctx, ens_name)
    except Exception as e:
        # Handle the exception here
        logger.error(f"error in register {str(e)}")
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
            fields=[
                {"name": "ENS Name", "value": ens_name, "inline": True},
                {"name": "Registration length", "value": "1 year", "inline": True},
                {"name": "Price", "value": format_wei_price(rent_price_wei), "inline": True}],
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
        await send_register_finish_url(
            name_label=next_action_data["name_label"],
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
        ens_name = next_action_data['ens_name']

        components = Button(
            style=ButtonStyle.GRAY,
            label=f"Make First Offer",
            emoji="☝",
            custom_id=f"offer_btn_0_weth_{ens_name}")

        await channel.send(
            f"Great news! `{ens_name}` is now owned by {mention(tx['user'])}"
            f", who can now proudly call it their own!", components=components)
    except Exception as e:
        logger.error(f"Error in register_callback {str(e)}")
        raise e


app = Quart(__name__)
app = cors(app, allow_origin="*")  # reconsider this in prod


@app.route('/tx', methods=['POST'])
async def user_post():
    data = await request.data
    json_data = json.loads(data.decode())
    tx_key = json_data["txKey"]
    tx_result = json_data["txResult"]

    if not tx_key or not tx_result and not tx_db.tx_key_exists(tx_key):
        abort(400, description='Transaction key is invalid')

    if tx_db.tx_result_exists(tx_key):
        abort(409, description="This transaction has already been processed")

    tx_db.update_tx_result(tx_key, tx_result)
    tx = tx_db.get_tx(tx_key)

    next_action_data = json.loads(tx["next_action_data"])

    callbacks = {
        "commit": (commit_callback, (tx, tx_result, next_action_data)),
        "register": (register_callback, (tx, tx_result, next_action_data))
    }

    web3_callbacks = discord_web3.get_web3_callbacks(
        bot, web3, user_address_db, tx, tx_result, json_data, next_action_data)
    opensea_callbacks = discord_opensea.get_opensea_callbacks(bot, web3, tx_db, tx, tx_result, next_action_data)

    merged_callbacks = {**callbacks, **web3_callbacks, **opensea_callbacks}

    callback_data = merged_callbacks.get(tx["action"])

    if callback_data is None:
        abort(400, description='Invalid Action')

    callback, args = callback_data
    asyncio.create_task(callback(*args))

    return jsonify({"status": "success"})


async def main():
    nest_asyncio.apply()
    tasks = [
        asyncio.create_task(app.run_task(host="0.0.0.0", port="80")),
        asyncio.create_task(bot.start(namebazaar_bot_token))
    ]
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        bot.stop()
