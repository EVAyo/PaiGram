import os
import random

import genshin
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import CallbackContext, ConversationHandler

from logger import Log
from model.base import ServiceEnum
from model.helpers import url_to_file
from plugins.base import BasePlugins
from service import BaseService
from service.base import UserInfoData


class GetUserCommandData:
    user_info: UserInfoData = UserInfoData()


class GetUser(BasePlugins):
    COMMAND_RESULT, = range(10200, 10201)

    def __init__(self, service: BaseService):
        super().__init__(service)
        self.current_dir = os.getcwd()

    async def command_start(self, update: Update, context: CallbackContext) -> int:
        user = update.effective_user
        Log.info(f"用户 {user.full_name}[{user.id}] 查询游戏用户命令请求")
        get_user_command_data: GetUserCommandData = context.chat_data.get("get_user_command_data")
        if get_user_command_data is None:
            get_user_command_data = GetUserCommandData()
            context.chat_data["get_user_command_data"] = get_user_command_data
        user_info = await self.service.user_service_db.get_user_info(user.id)
        if user_info.service == ServiceEnum.NULL:
            message = "请选择你要查询的类别"
            keyboard = [
                [
                    InlineKeyboardButton("miHoYo", callback_data="miHoYo"),
                    InlineKeyboardButton("HoYoLab", callback_data="HoYoLab")
                ]
            ]
            get_user_command_data.user_info = user_info
            await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
            return self.COMMAND_RESULT
        return ConversationHandler.END

    async def command_result(self, update: Update, context: CallbackContext) -> int:
        user = update.effective_user
        get_user_command_data: GetUserCommandData = context.chat_data["get_user_command_data"]
        query = update.callback_query
        await query.answer()
        await query.delete_message()
        if query.data == "miHoYo":
            client = genshin.ChineseClient(cookies=get_user_command_data.user_info.mihoyo_cookie)
            uid = get_user_command_data.user_info.mihoyo_game_uid
        elif query.data == "HoYoLab":
            client = genshin.GenshinClient(cookies=get_user_command_data.user_info.hoyoverse_cookie, lang="zh-cn")
            uid = get_user_command_data.user_info.hoyoverse_game_uid
        else:
            return ConversationHandler.END
        Log.info(f"用户 {user.full_name}[{user.id}] 查询武器命令请求 || 参数 UID {uid}")
        user_info = await client.get_user(int(uid))
        record_card_info = await client.get_record_card()
        await query.message.reply_chat_action(ChatAction.FIND_LOCATION)
        user_avatar = user_info.characters[0].icon
        user_data = {
            "name": record_card_info.nickname,
            "uid": record_card_info.uid,
            "user_avatar": await url_to_file(user_avatar),
            "action_day_number": user_info.stats.days_active,
            "achievement_number": user_info.stats.achievements,
            "avatar_number": user_info.stats.anemoculi,
            "spiral_abyss": user_info.stats.spiral_abyss,
            "way_point_number": user_info.stats.unlocked_waypoints,
            "domain_number": user_info.stats.unlocked_domains,
            "luxurious_number": user_info.stats.luxurious_chests,
            "precious_chest_number": user_info.stats.precious_chests,
            "exquisite_chest_number": user_info.stats.exquisite_chests,
            "common_chest_number": user_info.stats.common_chests,
            "magic_chest_number": user_info.stats.remarkable_chests,
            "anemoculus_number": user_info.stats.anemoculi,
            "geoculus_number": user_info.stats.geoculi,
            "electroculus_number": user_info.stats.electroculi,
            "world_exploration_list": [],
            "teapot_level": user_info.teapot.level,
            "teapot_comfort_num": user_info.teapot.comfort,
            "teapot_item_num": user_info.teapot.items,
            "teapot_visit_num": user_info.teapot.visitors,
            "teapot_list": []
        }
        for exploration in user_info.explorations:
            exploration_data = {
                "name": exploration.name,
                "exploration_percentage": exploration.percentage,
                "offerings": [],
                "icon": await url_to_file(exploration.icon)
            }
            for offering in exploration.offerings:
                offering_data = {
                    "data": f"{offering.name}：{offering.level}级"
                }
                exploration_data["offerings"].append(offering_data)
            user_data["world_exploration_list"].append(exploration_data)
        for teapot in user_info.teapot.realms:
            teapot_data = {
                "icon": await url_to_file(teapot.icon),
                "name": teapot.name
            }
            user_data["teapot_list"].append(teapot_data)
        background_image = random.choice(os.listdir(f"{self.current_dir}/resources/background/vertical"))
        user_data["background_image"] = f"file://{self.current_dir}/resources/background/vertical/{background_image}"
        png_data = await self.service.template.render('genshin/info', "info.html", user_data,
                                                      {"width": 1024, "height": 1024})
        await query.message.reply_chat_action(ChatAction.UPLOAD_PHOTO)
        await query.message.reply_photo(png_data, filename=f"{record_card_info.uid}.png",
                                        allow_sending_without_reply=True)
        await client.close()
        return ConversationHandler.END
