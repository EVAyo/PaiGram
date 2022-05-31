import re

from httpx import ConnectTimeout
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ChatAction, ParseMode
from telegram.ext import CallbackContext, filters

from logger import Log
from model.helpers import url_to_file
from plugins.base import BasePlugins
from service import BaseService
from metadata.shortname import roleToName


class Strategy(BasePlugins):
    def __init__(self, service: BaseService):
        super().__init__(service)

    async def command_start(self, update: Update, context: CallbackContext) -> None:
        message = update.message
        user = update.effective_user
        args = message.text.split(" ")
        search_command = re.search(r"^角色攻略查询(.*)", message.text)
        keyboard = [
            [
                InlineKeyboardButton(text="查看角色攻略列表并查询", switch_inline_query_current_chat="查看角色攻略列表并查询")
            ]
        ]
        await update.message.reply_chat_action(ChatAction.TYPING)
        if search_command:
            role_name = roleToName(search_command[1])
            if role_name == "":
                reply_message = await message.reply_text("请回复你要查询的攻略的角色名",
                                                         reply_markup=InlineKeyboardMarkup(keyboard))
                if filters.ChatType.GROUPS.filter(reply_message):
                    self._add_delete_message_job(context, message.chat_id, message.message_id)
                    self._add_delete_message_job(context, reply_message.chat_id, reply_message.message_id)
                return
        elif len(args) >= 2:
            role_name = roleToName(args[1])
        else:
            reply_message = await message.reply_text("请回复你要查询的攻略的角色名",
                                                     reply_markup=InlineKeyboardMarkup(keyboard))
            if filters.ChatType.GROUPS.filter(reply_message):
                self._add_delete_message_job(context, message.chat_id, message.message_id)
                self._add_delete_message_job(context, reply_message.chat_id, reply_message.message_id)
            return
        try:
            url = await self.service.get_game_info.get_characters_cultivation_atlas(role_name)
        except ConnectTimeout as error:
            reply_message = await message.reply_text("出错了呜呜呜 ~ 服务器连接超时 服务器熟啦 ~ ",
                                                     reply_markup=ReplyKeyboardRemove())
            Log.error("服务器请求ConnectTimeout \n", error)
            if filters.ChatType.GROUPS.filter(reply_message):
                self._add_delete_message_job(context, message.chat_id, message.message_id)
                self._add_delete_message_job(context, reply_message.chat_id, reply_message.message_id)
            return
        if url == "":
            reply_message = await message.reply_text(f"没有找到 {role_name} 的攻略",
                                                     reply_markup=InlineKeyboardMarkup(keyboard))
            if filters.ChatType.GROUPS.filter(reply_message):
                self._add_delete_message_job(context, message.chat_id, message.message_id)
                self._add_delete_message_job(context, reply_message.chat_id, reply_message.message_id)
            return

        Log.info(f"用户 {user.full_name}[{user.id}] 查询角色攻略命令请求 || 参数 {role_name}")

        await message.reply_chat_action(ChatAction.UPLOAD_PHOTO)
        file_path = await url_to_file(url, "")
        caption = "Form [米游社](https://bbs.mihoyo.com/ys/) 西风驿站  " \
                  f"查看 [原图]({url})"
        await message.reply_photo(photo=open(file_path, "rb"), caption=caption, filename=f"{role_name}.png",
                                  allow_sending_without_reply=True, parse_mode=ParseMode.MARKDOWN_V2)
