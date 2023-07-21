import logging
from web3 import Web3
import hashlib
import zlib
import base64
import urllib.parse
import httpx
import httpx_cache
from decimal import Decimal, ROUND_DOWN
from db.tx_db import TxDB
from db.user_db import UserDB
from datetime import datetime, timedelta
from eth_account.messages import encode_defunct, _hash_eip191_message
from interactions import SlashContext, Embed, BrandColors
import json
import random
import asyncio

http_cache_client = httpx_cache.AsyncClient()
http_client = httpx.AsyncClient()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("discord_web3")
etherscan_api_key = None
tx_check_interval = 3
eth_price_cache_expire = 300  # seconds
tx_page_url = "http://localhost:8000/"
server_host = "localhost"
server_port = 80

tx_link_instruction_text = f"please click on the link above. Upon clicking, the URL will open in your browser, " \
                           f"automatically launching your MetaMask browser extension or the mobile app. " \
                           f"Make sure you have MetaMask installed."

contract_addresses = {
    "Recover": "0x8564DAc105Ae26764467751a25DB1085B1176975"
}


def get_ws_web3(url):
    return Web3(Web3.WebsocketProvider(url))


def get_contract(web3, address, abi_name):
    return web3.eth.contract(address=address, abi=get_abi(abi_name))


def get_abi(contract_name):
    with open(f"../abi/{contract_name}.abi", 'r') as f:
        return json.load(f)


def less_hours_passed(start_time, hours):
    now = datetime.now()
    time_passed = now - start_time
    return time_passed < timedelta(hours=hours)


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


def generate_tx_key():
    return hashlib.sha256(f"{random.randint(10, 999999999999999)}".encode()).hexdigest()[:32]


async def wait_for_receipt(web3: Web3, tx_hash: str) -> dict:
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


def compress_string_to_url(s):
    compressed = zlib.compress(s.encode())
    encoded = base64.b64encode(compressed)
    url_safe_encoded = urllib.parse.quote_plus(encoded)
    return url_safe_encoded


def format_wei_price(price, token_name="eth"):
    if token_name == "usdc":
        return f"{(round(int(price) / 1000000, 3))} {token_name.upper()}"
    return f"{(round(Web3.from_wei(int(price), 'ether'), 4))} {token_name.upper()}"


def format_eth_price(price, token_name="eth", decimals=3):
    return f"{(round(price, decimals))} {token_name.upper()}"


def safe_to_wei(amount, token_name):
    if token_name == "usdc":
        return int(amount * 1000000)
    return Web3.to_wei(amount, "ether")


def safe_to_ether(amount, token_name):
    if token_name == "usdc":
        return float(amount / 1000000)
    return Web3.from_wei(amount, "ether")


async def get_eth_usd_price():
    response = await http_cache_client.get(
        f"https://api.etherscan.io/api?module=stats&action=ethprice&apikey={etherscan_api_key}",
        headers={"cache-control": f"max-age={eth_price_cache_expire}"})

    response = response.json()
    return Decimal(response["result"]["ethusd"])


async def get_owned_nfts(asset_contract_address, user_address, page=0, offset=0):
    response = await http_client.get(
        f"https://api.etherscan.io/api"
        f"?module=account"
        f"&action=addresstokennftinventory"
        f"&address={user_address.lower()}"
        f"&contractaddress={asset_contract_address.lower()}"
        f"&page={page}"
        f"&offset={offset}"
        f"&apikey={etherscan_api_key}")

    response = response.json()

    return response["result"]


def get_token_of_owner(asset_contract, owner, index):
    return asset_contract.functions.tokenOfOwnerByIndex(owner, index).call()


def get_balance_of(asset_contract, owner):
    return asset_contract.functions.balanceOf(owner).call()


def get_nft_owner(asset_contract, token_id):
    return asset_contract.functions.ownerOf(token_id).call()


def get_nft_total_supply(asset_contract):
    return asset_contract.functions.totalSupply().call()


def get_nft_token_by_index(asset_contract, index):
    return asset_contract.functions.tokenByIndex(index).call()


def get_usd_price(amount, eth_usd_price, token_name):
    if token_name == "usdc" or token_name == "dai":
        return amount
    elif token_name == "eth" or token_name == "weth":
        return amount * eth_usd_price
    else:
        0


async def link_wallet(
        ctx: SlashContext, tx_db: TxDB, message="Let's get this linking stuff done, so we can start trading!"):
    tx_key = generate_tx_key()

    json_data = json.dumps({"username": ctx.author.tag})

    tx_db.add_tx(
        {"tx_key": tx_key,
         "user": ctx.author_id,
         "action": "link_wallet",
         "channel": ctx.channel_id,
         "next_action_data": json_data})

    tx = {"to": "",
          "data": compress_string_to_url(json_data),
          "value": 0}

    tx_url = get_tx_page_url(tx_key, tx, sign_spec="LinkWallet")

    embed = Embed(
        title=f"Link your Ethereum address with this Discord server",
        description=f"In order to link your Ethereum address, {tx_link_instruction_text}",
        color=BrandColors.GREEN,
        url=tx_url)

    return await ctx.send(message, embeds=embed, ephemeral=True)


async def unlink_wallet(
        ctx: SlashContext, user_db: UserDB,
        message="Your Ethereum address was successfully unlinked from your Discord account."):
    user_db.remove_user(ctx.author_id)
    return await ctx.send(message, ephemeral=True)


async def my_wallet(ctx: SlashContext, user_db: UserDB):
    user_address = user_db.get_address(ctx.author_id)
    if user_address is None:
        return await ctx.send("You currently don't have any Ethereum address linked with your Discord account.",
                              ephemeral=True)
    else:
        return await ctx.send(f"Your currently linked address is: `{user_address}`", ephemeral=True)


async def link_wallet_callback(
        bot, web3: Web3, user_db: UserDB, tx, tx_signature, message, next_action_data):
    try:
        user = bot.get_user(int(tx["user"]))

        message = encode_defunct(hexstr=message)
        message_hash = _hash_eip191_message(message)
        hex_message_hash = Web3.to_hex(message_hash)
        sig = Web3.to_bytes(hexstr=tx_signature)
        v, hex_r, hex_s = Web3.to_int(sig[-1]), Web3.to_hex(sig[:32]), Web3.to_hex(sig[32:64])

        recover = get_contract(web3, contract_addresses["Recover"], "Recover")
        signer = recover.functions.ecr(hex_message_hash, v, hex_r, hex_s).call()

        if not Web3.is_address(signer):
            await user.send(f"We apologize, but we were unable to retrieve the Ethereum address from your signature.")
            logger.error(f"Invalid address recovered from signature: {signer}")
            return

        user_db.add_user_address(tx["user"], Web3.to_checksum_address(signer), tx["tx_key"], tx_signature)

        await user.send(
            f"Thank you. Your Ethereum address `{signer}` has been successfully linked with your Discord account. "
            f"Feel free to start trading some NFTs now!")
    except Exception as e:
        logger.error(f"link_wallet_callback {str(e)}")
        raise e


def get_web3_callbacks(bot, web3, user_db, tx, tx_result, json_data, next_action_data):
    return {"link_wallet": (
        link_wallet_callback,
        (bot, web3, user_db, tx, tx_result, json_data.get("message", ""), next_action_data))}
