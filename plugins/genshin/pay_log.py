import contextlib

import genshin
from telegram import Update, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, filters, ConversationHandler
from telegram.helpers import create_deep_linked_url

from core.baseplugin import BasePlugin
from core.cookies import CookiesService
from core.cookies.error import CookiesNotFoundError
from core.plugin import Plugin, handler, conversation
from core.template import TemplateService
from core.user import UserService
from core.user.error import UserNotFoundError
from modules.gacha_log.helpers import from_url_get_authkey
from modules.pay_log.error import PayLogNotFound, PayLogAccountNotFound, PayLogInvalidAuthkey, PayLogAuthkeyTimeout
from modules.pay_log.log import PayLog
from utils.bot import get_args
from utils.decorators.admins import bot_admins_rights_check
from utils.decorators.error import error_callable
from utils.decorators.restricts import restricts
from utils.genshin import get_authkey_by_stoken
from utils.helpers import get_genshin_client
from utils.log import logger
from utils.models.base import RegionEnum

INPUT_URL, CONFIRM_DELETE = range(10100, 10102)


class PayLogPlugin(Plugin.Conversation, BasePlugin.Conversation):
    """充值记录导入/导出/分析"""

    def __init__(
        self,
        template_service: TemplateService = None,
        user_service: UserService = None,
        cookie_service: CookiesService = None,
    ):
        self.template_service = template_service
        self.user_service = user_service
        self.cookie_service = cookie_service
        self.pay_log = PayLog()

    async def _refresh_user_data(self, user: User, authkey: str = None) -> str:
        """刷新用户数据
        :param user: 用户
        :param authkey: 认证密钥
        :return: 返回信息
        """
        try:
            logger.debug("尝试获取已绑定的原神账号")
            client = await get_genshin_client(user.id, need_cookie=False)
            new_num = await self.pay_log.get_log_data(user.id, client, authkey)
            return "更新完成，本次没有新增数据" if new_num == 0 else f"更新完成，本次共新增{new_num}条充值记录"
        except PayLogNotFound:
            return "派蒙没有找到你的充值记录，快去充值吧~"
        except PayLogAccountNotFound:
            return "导入失败，可能文件包含的祈愿记录所属 uid 与你当前绑定的 uid 不同"
        except PayLogInvalidAuthkey:
            return "更新数据失败，authkey 无效"
        except PayLogAuthkeyTimeout:
            return "更新数据失败，authkey 已经过期"
        except UserNotFoundError:
            logger.info("未查询到用户 %s[%s] 所绑定的账号信息", user.full_name, user.id)
            return "派蒙没有找到您所绑定的账号信息，请先私聊派蒙绑定账号"

    @conversation.entry_point
    @handler(CommandHandler, command="pay_log_import", filters=filters.ChatType.PRIVATE, block=False)
    @handler(MessageHandler, filters=filters.Regex("^导入充值记录$") & filters.ChatType.PRIVATE, block=False)
    @restricts()
    @error_callable
    async def command_start(self, update: Update, context: CallbackContext) -> int:
        message = update.effective_message
        user = update.effective_user
        args = get_args(context)
        logger.info("用户 %s[%s] 导入充值记录命令请求", user.full_name, user.id)
        authkey = from_url_get_authkey(args[0] if args else "")
        if not args:
            try:
                user_info = await self.user_service.get_user_by_id(user.id)
            except UserNotFoundError:
                user_info = None
            if user_info and user_info.region == RegionEnum.HYPERION:
                try:
                    cookies = await self.cookie_service.get_cookies(user_info.user_id, user_info.region)
                except CookiesNotFoundError:
                    cookies = None
                if cookies and cookies.cookies and "stoken" in cookies.cookies:
                    if stuid := next(
                        (value for key, value in cookies.cookies.items() if key in ["ltuid", "login_uid"]), None
                    ):
                        cookies.cookies["stuid"] = stuid
                        client = genshin.Client(
                            cookies=cookies.cookies,
                            game=genshin.types.Game.GENSHIN,
                            region=genshin.Region.CHINESE,
                            lang="zh-cn",
                            uid=user_info.yuanshen_uid,
                        )
                        with contextlib.suppress(Exception):
                            authkey = await get_authkey_by_stoken(client)
        if not authkey:
            await message.reply_text(
                "<b>开始导入充值历史记录：请通过 https://paimon.moe/wish/import 获取抽卡记录链接后发送给我"
                "（非 paimon.moe 导出的文件数据）</b>\n\n"
                "> 在绑定 Cookie 时添加 stoken 可能有特殊效果哦（国服）\n"
                "<b>注意：导入的数据将会与旧数据进行合并。</b>",
                parse_mode="html",
            )
            return INPUT_URL
        text = "小派蒙正在从服务器获取数据，请稍后"
        if not args:
            text += "\n\n> 由于你绑定的 Cookie 中存在 stoken ，本次通过 stoken 自动刷新数据"
        reply = await message.reply_text(text)
        await message.reply_chat_action(ChatAction.TYPING)
        data = await self._refresh_user_data(user, authkey=authkey)
        await reply.edit_text(data)
        return ConversationHandler.END

    @conversation.state(state=INPUT_URL)
    @handler.message(filters=filters.TEXT & ~filters.COMMAND, block=False)
    @restricts()
    @error_callable
    async def import_data_from_message(self, update: Update, _: CallbackContext) -> int:
        message = update.effective_message
        user = update.effective_user
        if not message.text:
            await message.reply_text("输入错误，请重新输入")
            return INPUT_URL
        authkey = from_url_get_authkey(message.text)
        reply = await message.reply_text("小派蒙正在从服务器获取数据，请稍后")
        await message.reply_chat_action(ChatAction.TYPING)
        text = await self._refresh_user_data(user, authkey=authkey)
        await reply.edit_text(text)
        return ConversationHandler.END

    @conversation.entry_point
    @handler(CommandHandler, command="pay_log_delete", filters=filters.ChatType.PRIVATE, block=False)
    @handler(MessageHandler, filters=filters.Regex("^删除充值记录$") & filters.ChatType.PRIVATE, block=False)
    @restricts()
    @error_callable
    async def command_start_delete(self, update: Update, context: CallbackContext) -> int:
        message = update.effective_message
        user = update.effective_user
        logger.info("用户 %s[%s] 删除充值记录命令请求", user.full_name, user.id)
        try:
            client = await get_genshin_client(user.id, need_cookie=False)
            context.chat_data["uid"] = client.uid
        except UserNotFoundError:
            logger.info("未查询到用户 %s[%s] 所绑定的账号信息", user.full_name, user.id)
            buttons = [[InlineKeyboardButton("点我绑定账号", url=create_deep_linked_url(context.bot.username, "set_uid"))]]
            if filters.ChatType.GROUPS.filter(message):
                reply_message = await message.reply_text(
                    "未查询到您所绑定的账号信息，请先私聊派蒙绑定账号", reply_markup=InlineKeyboardMarkup(buttons)
                )
                self._add_delete_message_job(context, reply_message.chat_id, reply_message.message_id, 30)
                self._add_delete_message_job(context, message.chat_id, message.message_id, 30)
            else:
                await message.reply_text("未查询到您所绑定的账号信息，请先绑定账号", reply_markup=InlineKeyboardMarkup(buttons))
            return ConversationHandler.END
        _, status = await self.pay_log.load_history_info(str(user.id), str(client.uid), only_status=True)
        if not status:
            await message.reply_text("你还没有导入充值记录哦~")
            return ConversationHandler.END
        await message.reply_text("你确定要删除充值记录吗？（此项操作无法恢复），如果确定请发送 ”确定“，发送其他内容取消")
        return CONFIRM_DELETE

    @conversation.state(state=CONFIRM_DELETE)
    @handler.message(filters=filters.TEXT & ~filters.COMMAND, block=False)
    @restricts()
    @error_callable
    async def command_confirm_delete(self, update: Update, context: CallbackContext) -> int:
        message = update.effective_message
        user = update.effective_user
        if message.text == "确定":
            status = await self.pay_log.remove_history_info(str(user.id), str(context.chat_data["uid"]))
            await message.reply_text("充值记录已删除" if status else "充值记录删除失败")
            return ConversationHandler.END
        await message.reply_text("已取消")
        return ConversationHandler.END

    @handler(CommandHandler, command="pay_log_force_delete", block=False)
    @bot_admins_rights_check
    async def command_pay_log_force_delete(self, update: Update, context: CallbackContext):
        message = update.effective_message
        args = get_args(context)
        if not args:
            await message.reply_text("请指定用户ID")
            return
        try:
            cid = int(args[0])
            if cid < 0:
                raise ValueError("Invalid cid")
            client = await get_genshin_client(cid, need_cookie=False)
            _, status = await self.pay_log.load_history_info(str(cid), str(client.uid), only_status=True)
            if not status:
                await message.reply_text("该用户还没有导入充值记录")
                return
            status = await self.pay_log.remove_history_info(str(cid), str(client.uid))
            await message.reply_text("充值记录已强制删除" if status else "充值记录删除失败")
        except PayLogNotFound:
            await message.reply_text("该用户还没有导入充值记录")
        except UserNotFoundError:
            await message.reply_text("该用户暂未绑定账号")
        except (ValueError, IndexError):
            await message.reply_text("用户ID 不合法")

    @handler(CommandHandler, command="pay_log_export", filters=filters.ChatType.PRIVATE, block=False)
    @handler(MessageHandler, filters=filters.Regex("^导出充值记录$") & filters.ChatType.PRIVATE, block=False)
    @restricts()
    @error_callable
    async def command_start_export(self, update: Update, context: CallbackContext) -> None:
        message = update.effective_message
        user = update.effective_user
        logger.info("用户 %s[%s] 导出充值记录命令请求", user.full_name, user.id)
        try:
            client = await get_genshin_client(user.id, need_cookie=False)
            await message.reply_chat_action(ChatAction.TYPING)
            path = self.pay_log.get_file_path(str(user.id), str(client.uid))
            await message.reply_chat_action(ChatAction.UPLOAD_DOCUMENT)
            await message.reply_document(document=open(path, "rb+"), caption="充值记录导出文件")
        except PayLogNotFound:
            buttons = [
                [InlineKeyboardButton("点我导入", url=create_deep_linked_url(context.bot.username, "pay_log_import"))]
            ]
            await message.reply_text("派蒙没有找到你的充值记录，快来私聊派蒙导入吧~", reply_markup=InlineKeyboardMarkup(buttons))
        except PayLogAccountNotFound:
            await message.reply_text("导出失败，可能文件包含的祈愿记录所属 uid 与你当前绑定的 uid 不同")
        except UserNotFoundError:
            logger.info("未查询到用户 %s[%s] 所绑定的账号信息", user.full_name, user.id)
            buttons = [[InlineKeyboardButton("点我绑定账号", url=create_deep_linked_url(context.bot.username, "set_uid"))]]
            if filters.ChatType.GROUPS.filter(message):
                reply_message = await message.reply_text(
                    "未查询到您所绑定的账号信息，请先私聊派蒙绑定账号", reply_markup=InlineKeyboardMarkup(buttons)
                )
                self._add_delete_message_job(context, reply_message.chat_id, reply_message.message_id, 30)
                self._add_delete_message_job(context, message.chat_id, message.message_id, 30)
            else:
                await message.reply_text("未查询到您所绑定的账号信息，请先绑定账号", reply_markup=InlineKeyboardMarkup(buttons))

    @handler(CommandHandler, command="pay_log", block=False)
    @handler(MessageHandler, filters=filters.Regex("^充值记录$"), block=False)
    @restricts()
    @error_callable
    async def command_start_analysis(self, update: Update, context: CallbackContext) -> None:
        message = update.effective_message
        user = update.effective_user
        logger.info("用户 %s[%s] 充值记录统计命令请求", user.full_name, user.id)
        try:
            client = await get_genshin_client(user.id, need_cookie=False)
            await message.reply_chat_action(ChatAction.TYPING)
            data = await self.pay_log.get_analysis(user.id, client)
            await message.reply_chat_action(ChatAction.UPLOAD_PHOTO)
            png_data = await self.template_service.render(
                "genshin/pay_log/pay_log.html", data, full_page=True, query_selector=".container"
            )
            await png_data.reply_photo(message)
        except PayLogNotFound:
            buttons = [
                [InlineKeyboardButton("点我导入", url=create_deep_linked_url(context.bot.username, "pay_log_import"))]
            ]
            await message.reply_text("派蒙没有找到你的充值记录，快来点击按钮私聊派蒙导入吧~", reply_markup=InlineKeyboardMarkup(buttons))
        except UserNotFoundError:
            logger.info("未查询到用户 %s[%s] 所绑定的账号信息", user.full_name, user.id)
            buttons = [[InlineKeyboardButton("点我绑定账号", url=create_deep_linked_url(context.bot.username, "set_uid"))]]
            if filters.ChatType.GROUPS.filter(message):
                reply_message = await message.reply_text(
                    "未查询到您所绑定的账号信息，请先私聊派蒙绑定账号", reply_markup=InlineKeyboardMarkup(buttons)
                )
                self._add_delete_message_job(context, reply_message.chat_id, reply_message.message_id, 30)
                self._add_delete_message_job(context, message.chat_id, message.message_id, 30)
            else:
                await message.reply_text("未查询到您所绑定的账号信息，请先绑定账号", reply_markup=InlineKeyboardMarkup(buttons))