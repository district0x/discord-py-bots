import asyncio
import textwrap
import uuid
from typing import Callable, Coroutine, List, Optional, Sequence, TYPE_CHECKING, Union
import attrs
from interactions.ext.paginators import Paginator, Page
from interactions import (
    Embed,
    ComponentContext,
    ActionRow,
    Button,
    ButtonStyle,
    spread_to_rows,
    ComponentCommand,
    BaseContext,
    Message,
    MISSING,
    Snowflake_Type,
    StringSelectMenu,
    StringSelectOption,
    Color,
    BrandColors,
)
from interactions.client.utils.serializer import export_converter
from interactions.models.discord.emoji import process_emoji, PartialEmoji


@attrs.define(eq=False, order=False, hash=False, kw_only=False)
class AsyncPage(Page):
    async def to_embed(self) -> Embed:
        """Process the page to an embed asynchronously."""
        return Embed(description=f"{self.prefix}\n{self.content}\n{self.suffix}", title=self.title)


@attrs.define(eq=False, order=False, hash=False, kw_only=False)
class AsyncPaginator(Paginator):
    async def to_dict(self) -> dict:
        """Convert this paginator into a dictionary for sending asynchronously."""
        page = self.pages[self.page_index]

        if isinstance(page, Page):
            page = await page.to_embed()  # Await the asynchronous to_embed() function
            if not page.title and self.default_title:
                page.title = self.default_title
        if not page.footer:
            page.set_footer(f"Page {self.page_index + 1}/{len(self.pages)}")
        if not page.color:
            page.color = self.default_color

        return {
            "embeds": [page.to_dict()],  # Await the asynchronous to_dict() function
            "components": [c.to_dict() for c in self.create_components()],
            # Await each component's to_dict() function
        }

    async def _on_button(self, ctx: ComponentContext, *args, **kwargs) -> Optional[Message]:
        if ctx.author.id != self.author_id:
            return (
                await ctx.send(self.wrong_user_message, ephemeral=True)
                if self.wrong_user_message
                else await ctx.defer(edit_origin=True)
            )
        if self._timeout_task:
            self._timeout_task.ping.set()
        match ctx.custom_id.split("|")[1]:
            case "first":
                self.page_index = 0
            case "last":
                self.page_index = len(self.pages) - 1
            case "next":
                if (self.page_index + 1) < len(self.pages):
                    self.page_index += 1
            case "back":
                if self.page_index >= 1:
                    self.page_index -= 1
            case "select":
                self.page_index = int(ctx.values[0])
            case "callback":
                if self.callback:
                    return await self.callback(ctx)

        await ctx.edit_origin(**await self.to_dict())  # Await the asynchronous to_dict() function
        return None

    async def send(self, ctx: BaseContext) -> Message:
        """
        Send this paginator.

        Args:
            ctx: The context to send this paginator with

        Returns:
            The resulting message

        """
        self._message = await ctx.send(**await self.to_dict())
        self._author_id = ctx.author.id

        if self.timeout_interval > 1:
            self._timeout_task = Timeout(self)
            _ = asyncio.create_task(self._timeout_task())

        return self._message

    async def reply(self, ctx: "PrefixedContext") -> Message:
        """
        Reply this paginator to ctx.

        Args:
            ctx: The context to reply this paginator with
        Returns:
            The resulting message
        """
        self._message = await ctx.reply(**await self.to_dict())
        self._author_id = ctx.author.id

        if self.timeout_interval > 1:
            self._timeout_task = Timeout(self)
            _ = asyncio.create_task(self._timeout_task())

        return self._message

    async def update(self) -> None:
        """
        Update the paginator to the current state.

        Use this if you have programmatically changed the page_index

        """
        await self._message.edit(**await self.to_dict())
