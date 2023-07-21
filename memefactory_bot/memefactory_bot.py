import asyncio
import json
import logging
import os
import re
from dotenv import load_dotenv
from interactions import listen, Client, Intents, slash_command, slash_option, SlashContext, OptionType, \
    component_callback, ComponentContext, auto_defer
from web3 import Web3
from decimal import Decimal, ROUND_DOWN
from quart import Quart, request, jsonify, abort
import nest_asyncio
from db.tx_db import TxDB
from db.user_db import UserDB
from quart_cors import cors
import discord_opensea.discord_opensea as discord_opensea
import discord_web3.discord_web3 as discord_web3
from discord_web3.discord_web3 import get_contract
from discord_opensea.discord_opensea import AssetType

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("memefactory_bot")

memefactory_bot_token = os.getenv('MEMEFACTORY_BOT_TOKEN')
memefactory_bot_client_id = os.getenv('MEMEFACTORY_BOT_CLIENT_ID')
discord_opensea.api_key = os.getenv('OPENSEA_API_KEY')
discord_web3.etherscan_api_key = os.getenv('ETHERSCAN_API_KEY')
infura_url = os.getenv('INFURA_URL')
discord_web3.tx_page_url = os.getenv('TX_PAGE_URL')
discord_web3.server_host = os.getenv('SERVER_HOST')
discord_web3.server_port = os.getenv('SERVER_PORT')
discord_web3.tx_check_interval = int(os.getenv('TX_CHECK_INTERVAL'))
stream_channel_id = int(os.getenv('STREAM_CHANNEL_ID'))
discord_opensea.stream_interval = int(os.getenv('STREAM_INTERVAL'))
user_db_path = os.getenv('USER_DB_PATH')
tx_db_path = os.getenv('TX_DB_PATH')

contract_addresses = {
    "MemeToken": "0xd23043ce917aC39309F49dbA82f264994d3AdE76"
}

asset_contract_address = contract_addresses["MemeToken"]
chain = "ethereum"
slug = "memetoken"

intents = Intents.DEFAULT
intents.messages = True
intents.guilds = True
intents.message_content = True
intents.members = True

tx_db = TxDB(tx_db_path)
user_db = UserDB(user_db_path)
bot = Client(intents=intents)

web3 = discord_web3.get_ws_web3(infura_url)
memetoken = get_contract(web3, asset_contract_address, "MemeToken")


@listen()
async def on_ready():
    # ready events pass no data, so dont have params
    logger.info("MemefactoryBot is ready")
    await discord_opensea.start_stream(bot, slug, stream_channel_id)


@slash_command(name="memes", description="List of MemeFactory memes")
@slash_option(
    name="start_index",
    description="Index to start listing MemeFactory memes from. (Default latest)",
    required=False,
    opt_type=OptionType.INTEGER,
    min_value=0
)
@auto_defer(ephemeral=True)
async def memes(ctx: SlashContext, start_index=0):
    return await discord_opensea.nfts(
        ctx=ctx,
        bot=bot,
        web3=web3,
        user_db=user_db,
        tx_db=tx_db,
        chain=chain,
        asset_contract=memetoken,
        start_index=start_index)


@slash_command(name="meme", description="Display details of a meme")
@slash_option(
    name="token_id",
    description="Token ID of a MemeFactory Meme",
    required=True,
    opt_type=OptionType.INTEGER,
)
@auto_defer(ephemeral=True)
async def meme(ctx: SlashContext, token_id):
    return await discord_opensea.nft(ctx, chain, asset_contract_address, token_id)


@slash_command(name="listing", description="Fetch cheapest listing for a given MemeFactory meme.")
@slash_option(
    name="token_id",
    description="Token ID of a MemeFactory Meme",
    required=True,
    opt_type=OptionType.INTEGER,
)
@auto_defer(ephemeral=True)
async def listing(ctx: SlashContext, token_id):
    return await discord_opensea.cheapest_listing(ctx, asset_contract_address, token_id)


@slash_command(name="buy", description="Buy MemeFactory meme from OpenSea")
@auto_defer(ephemeral=True)
@slash_option(
    name="token_id",
    description="Please provide the token ID of a meme you wish to buy.",
    required=True,
    opt_type=OptionType.INTEGER,
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
async def buy(ctx: SlashContext, token_id, bid=None, currency=None):
    asset_name, asset_img, _ = await discord_opensea.get_nft_basic_info(chain, asset_contract_address, token_id)

    return await discord_opensea.buy(
        ctx=ctx,
        web3=web3,
        user_db=user_db,
        tx_db=tx_db,
        asset_name=asset_name,
        asset_img=asset_img,
        asset_contract_address=asset_contract_address,
        token_id=token_id,
        asset_type=AssetType.ERC721,
        bid=bid,
        currency=currency)


@component_callback(re.compile(r"^buy_btn_"))
async def buy_btn_callback(ctx: ComponentContext):
    await ctx.defer(ephemeral=True)
    token_id = discord_opensea.compile_buy_btn(ctx.custom_id)
    asset_name, asset_img, _ = await discord_opensea.get_nft_basic_info(chain, asset_contract_address, token_id)
    return await discord_opensea.buy(
        ctx=ctx,
        web3=web3,
        user_db=user_db,
        tx_db=tx_db,
        asset_name=asset_name,
        asset_img=asset_img,
        token_id=token_id,
        asset_contract_address=asset_contract_address,
        asset_type=AssetType.ERC721)


@component_callback(re.compile(r"^offer_btn_"))
async def offer_btn_callback(ctx: ComponentContext):
    await ctx.defer(ephemeral=True)
    token_id, price, token_name = discord_opensea.compile_offer_btn(ctx.custom_id)
    asset_name, asset_img, _ = await discord_opensea.get_nft_basic_info(chain, asset_contract_address, token_id)
    return await discord_opensea.buy(
        ctx=ctx,
        web3=web3,
        user_db=user_db,
        tx_db=tx_db,
        asset_name=asset_name,
        asset_img=asset_img,
        token_id=token_id,
        asset_contract_address=asset_contract_address,
        asset_type=AssetType.ERC721,
        bid=price,
        currency=token_name,
        force_bid=True)


@slash_command(name="offers", description="List of offers/bid for a given MemeFactory meme")
@auto_defer(ephemeral=True)
@slash_option(
    name="token_id",
    description="Please provide the token id that you wish to get offers for.",
    required=True,
    opt_type=OptionType.INTEGER)
async def offers(ctx: SlashContext, token_id):
    asset_name, asset_img, _ = await discord_opensea.get_nft_basic_info(chain, asset_contract_address, token_id)

    return await discord_opensea.offers(
        bot=bot,
        ctx=ctx,
        user_db=user_db,
        tx_db=tx_db,
        web3=web3,
        asset_contract_address=asset_contract_address,
        token_id=token_id,
        asset_name=asset_name,
        asset_img=asset_img,
        asset_owner=owner)


@slash_command(name="link-wallet", description="Link your Ethereum address to your Discord account.")
async def link_wallet(ctx: SlashContext):
    return await discord_web3.link_wallet(ctx=ctx, tx_db=tx_db)


@slash_command(name="unlink-wallet", description="Unlink your Ethereum address from your Discord account.")
async def unlink_wallet(ctx: SlashContext):
    return await discord_web3.unlink_wallet(ctx=ctx, user_db=user_db)


@slash_command(name="sell", description="Sell your MemeFactory meme on OpenSea")
@auto_defer(ephemeral=True)
@slash_option(
    name="token_id",
    description="Please provide the MemeFactory meme that you wish to sell.",
    required=True,
    opt_type=OptionType.INTEGER
)
@slash_option(
    name="start_price",
    description="Specify the initial selling price for your meme in ETH.",
    required=True,
    opt_type=OptionType.NUMBER,
)
@slash_option(
    name="end_price",
    description="Specify the final selling price for your meme in ETH. If empty, it equals the start price.",
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
    description="Specify the selling currency for your meme (default is ETH).",
    required=False,
    opt_type=OptionType.STRING,
    choices=discord_opensea.currency_choices)
async def sell(ctx: SlashContext, token_id, start_price, end_price=None, duration_days=100, currency="eth"):
    asset_name, asset_img, _ = await discord_opensea.get_nft_basic_info(chain, asset_contract_address, token_id)

    return await discord_opensea.sell(
        ctx=ctx,
        user_db=user_db,
        tx_db=tx_db,
        asset_name=asset_name,
        asset_img=asset_img,
        asset_type=AssetType.ERC721,
        asset_contract=memetoken,
        token_id=token_id,
        currency=currency,
        start_price=start_price,
        end_price=end_price,
        duration_days=duration_days)


@slash_command(name="owned-memes", description="Shows list of MemeFactory memes owned by a given address")
@auto_defer(ephemeral=True)
@slash_option(
    name="owner_address",
    description="Please provide the Ethereum address you wish to get list of owned memes for.",
    required=True,
    opt_type=OptionType.STRING,
    max_length=42,
    min_length=42
)
async def owned_names(ctx: SlashContext, owner_address):
    return await discord_opensea.owned_nfts(
        ctx=ctx,
        bot=bot,
        web3=web3,
        user_db=user_db,
        tx_db=tx_db,
        chain=chain,
        asset_contract=memetoken,
        owner_address=owner_address)


@slash_command(name="my-memes", description="Shows list of memes owned by your linked wallet address")
@auto_defer(ephemeral=True)
async def my_memes(ctx: SlashContext):
    user_address = user_db.get_address(ctx.author_id)

    return await discord_opensea.owned_nfts(
        ctx=ctx,
        bot=bot,
        web3=web3,
        user_db=user_db,
        tx_db=tx_db,
        chain=chain,
        asset_contract=memetoken,
        owner_address=user_address)


@slash_command(name="flex", description="Publicly display a list of the memes you own. Show off your collection!")
@auto_defer(ephemeral=False)
async def flex(ctx: SlashContext):
    user_address = user_db.get_address(ctx.author_id)

    await ctx.send(f"Let's take a moment to admire the dazzling collection of MemeFactory memes owned by " \
                   f"{ctx.author.mention}!\nWhat an incredible accomplishment! 💪💪💪\n")
    return await discord_opensea.owned_nfts(
        ctx=ctx,
        bot=bot,
        web3=web3,
        user_db=user_db,
        tx_db=tx_db,
        chain=chain,
        asset_contract=memetoken,
        owner_address=user_address)


@slash_command(name="my-wallet", description="Shows your currently linked wallet address")
async def my_wallet(ctx: SlashContext):
    return await discord_web3.my_wallet(ctx, user_db)


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

    web3_callbacks = discord_web3.get_web3_callbacks(
        bot, web3, user_db, tx, tx_result, json_data, next_action_data)
    opensea_callbacks = discord_opensea.get_opensea_callbacks(bot, web3, tx_db, tx, tx_result, next_action_data)

    merged_callbacks = {**web3_callbacks, **opensea_callbacks}

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
        asyncio.create_task(bot.start(memefactory_bot_token))
    ]
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        bot.stop()
