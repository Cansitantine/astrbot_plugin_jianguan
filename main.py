import asyncio
from collections import defaultdict, deque
import time

from aiocqhttp import CQHttp

from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

from astrbot.api.all import *
from astrbot.api.event.filter import *
from astrbot.api.message_components import *
import logging

# 配置日志记录器
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


@register("astrbot_plugin_jianguan", "Cansitantine", "QQ群组消息监控插件", "2.0.0", "https://github.com/Cansitantine/astrbot_plugin_jianguan")
class MessageMonitor(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        # 处理 time_window
        time_window_config = config.get("time_window")
        if isinstance(time_window_config, dict):
            self.time_window = float(time_window_config.get("default", "60"))
        else:
            self.time_window = float(time_window_config or "60")

        # 处理 repeat_threshold
        repeat_threshold_config = config.get("repeat_threshold")
        if isinstance(repeat_threshold_config, dict):
            self.repeat_threshold = int(repeat_threshold_config.get("default", "3"))
        else:
            self.repeat_threshold = int(repeat_threshold_config or "3")

        # 处理 warning_cool_down
        warning_cool_down_config = config.get("warning_cool_down")
        if isinstance(warning_cool_down_config, dict):
            self.warning_cool_down = float(warning_cool_down_config.get("default", "30"))
        else:
            self.warning_cool_down = float(warning_cool_down_config or "30")

        # 处理 remind_message
        remind_message_config = config.get("remind_message")
        if isinstance(remind_message_config, dict):
            self.remind_message = remind_message_config.get("default", "有用户发送了高频无意义消息，用户 ID：[sender_id]，所属群聊：[group_id]")
        else:
            self.remind_message = remind_message_config or "有用户发送了高频无意义消息，用户 ID：[sender_id]，所属群聊：[group_id]"

        # 处理 warning_message
        warning_message_config = config.get("warning_message")
        if isinstance(warning_message_config, dict):
            self.warning_message = warning_message_config.get("default", "您发送的消息被判定为高频无意义消息，请遵守群规！")
        else:
            self.warning_message = warning_message_config or "您发送的消息被判定为高频无意义消息，请遵守群规！"

        # 处理 enable_remind
        enable_remind_config = config.get("enable_remind")
        if isinstance(enable_remind_config, dict):
            enable_remind_str = enable_remind_config.get("default", "是")
        else:
            enable_remind_str = enable_remind_config or "是"
        self.enable_remind = enable_remind_str == "是"

        # 处理 enable_warning
        enable_warning_config = config.get("enable_warning")
        if isinstance(enable_warning_config, dict):
            enable_warning_str = enable_warning_config.get("default", "是")
        else:
            enable_warning_str = enable_warning_config or "是"
        self.enable_warning = enable_warning_str == "是"

        # 处理 enable_anti_spam
        enable_anti_spam_config = config.get("enable_anti_spam")
        if isinstance(enable_anti_spam_config, dict):
            enable_anti_spam_str = enable_anti_spam_config.get("default", "否")
        else:
            enable_anti_spam_str = enable_anti_spam_config or "否"
        self.enable_anti_spam = enable_anti_spam_str == "是"

        # 处理 enable_kick
        enable_kick_config = config.get("enable_kick")
        if isinstance(enable_kick_config, dict):
            enable_kick_str = enable_kick_config.get("default", "否")
        else:
            enable_kick_str = enable_kick_config or "否"
        self.enable_kick = enable_kick_str == "是"

        # 处理 anti_spam_group_ids
        anti_spam_group_ids_config = config.get("anti_spam_group_ids")
        if isinstance(anti_spam_group_ids_config, dict):
            anti_spam_group_ids = anti_spam_group_ids_config.get("default", [])
        else:
            anti_spam_group_ids = anti_spam_group_ids_config or []
        self.anti_spam_group_ids = [str(id) for id in anti_spam_group_ids]

        # 处理 kick_group_ids
        kick_group_ids_config = config.get("kick_group_ids")
        if isinstance(kick_group_ids_config, dict):
            kick_group_ids = kick_group_ids_config.get("default", [])
        else:
            kick_group_ids = kick_group_ids_config or []
        self.kick_group_ids = [str(id) for id in kick_group_ids]

        # 处理 remind_group_ids
        remind_group_ids_config = config.get("remind_group_ids")
        if isinstance(remind_group_ids_config, dict):
            remind_group_ids = remind_group_ids_config.get("default", [])
        else:
            remind_group_ids = remind_group_ids_config or []
        self.remind_group_ids = [str(id) for id in remind_group_ids]

        # 处理 warning_group_ids
        warning_group_ids_config = config.get("warning_group_ids")
        if isinstance(warning_group_ids_config, dict):
            warning_group_ids = warning_group_ids_config.get("default", [])
        else:
            warning_group_ids = warning_group_ids_config or []
        self.warning_group_ids = [str(id) for id in warning_group_ids]

        # 处理 detection_group_ids
        detection_group_ids_config = config.get("detection_group_ids")
        if isinstance(detection_group_ids_config, dict):
            detection_group_ids = detection_group_ids_config.get("default", [])
        else:
            detection_group_ids = detection_group_ids_config or []
        self.detection_group_ids = [str(id) for id in detection_group_ids]

        # 处理 ban_duration
        ban_duration_config = config.get("ban_duration")
        if isinstance(ban_duration_config, dict):
            self.ban_duration = int(ban_duration_config.get("default", "60"))
        else:
            self.ban_duration = int(ban_duration_config or "60")

        # 存储每个群组在时间窗口内的消息记录，格式为 {group_id: {message_content: [(message_id, sender_id, timestamp), ...]}}
        self.group_message_history = defaultdict(lambda: defaultdict(list))
        # 存储每个群组上次清理计数的时间，格式为 {group_id: last_clean_time}
        self.group_last_clean_time = defaultdict(float)
        # 存储上次警告用户的时间，格式为 {user_id: last_warning_time}
        self.last_warning_time = {}

    def _clean_old_messages(self, group_id, current_time):
        """清理时间窗口外的消息记录"""
        if current_time - self.group_last_clean_time[group_id] > self.time_window:
            for message_content in list(self.group_message_history[group_id].keys()):
                self.group_message_history[group_id][message_content] = [
                    (msg_id, sender_id, timestamp)
                    for msg_id, sender_id, timestamp in self.group_message_history[group_id][message_content]
                    if current_time - timestamp <= self.time_window
                ]
                if not self.group_message_history[group_id][message_content]:
                    del self.group_message_history[group_id][message_content]
            self.group_last_clean_time[group_id] = current_time

    def _is_spam(self, group_id, message_content, current_time, sender_id, message_id):
        """
        检查消息是否为高频无意义消息
        :param group_id: 群组 ID
        :param message_content: 消息内容
        :param current_time: 当前时间
        :param sender_id: 发送者 ID
        :param message_id: 消息的 ID
        :return: 如果消息是高频无意义消息返回 True，否则返回 False
        """
        self._clean_old_messages(group_id, current_time)
        self.group_message_history[group_id][message_content].append((message_id, sender_id, current_time))
        sender_messages = [
            msg_id for msg_id, s_id, _ in self.group_message_history[group_id][message_content] if s_id == sender_id
        ]
        return len(sender_messages) >= self.repeat_threshold

    async def _ban_user(self, client, group_id, sender_id, self_id):
        """独立的禁言模块"""
        try:
            await client.set_group_ban(
                group_id=int(group_id),
                user_id=sender_id,
                duration=self.ban_duration,
                self_id=int(self_id)
            )
            logger.info(f"Banned user: {sender_id} for {self.ban_duration} seconds")
        except Exception as e:
            logger.error(f"Failed to ban user: {e}")

    async def _delete_spam_messages(self, client, group_id, message_content, sender_id, self_id):
        """批量撤回无意义消息"""
        sender_messages = [
            msg_id for msg_id, s_id, _ in self.group_message_history[group_id][message_content] if s_id == sender_id
        ]
        for msg_id in sender_messages:
            try:
                await client.delete_msg(
                    message_id=msg_id,
                    self_id=int(self_id)
                )
                logger.info(f"Deleted spam message: {msg_id}")
            except Exception as e:
                logger.error(f"Failed to delete message {msg_id}: {e}")

    async def _send_remind_message(self, client, sender_id, group_id, self_id):
        """发送提醒消息"""
        if self.enable_remind:
            # 获取发送者的群昵称
            try:
                member_info = await client.get_group_member_info(
                    group_id=int(group_id),
                    user_id=int(sender_id),
                    no_cache=True,
                    self_id=int(self_id)
                )
                nickname = member_info.get('card') or member_info.get('nickname')
            except Exception as e:
                logger.error(f"Failed to get member info: {e}")
                nickname = "未知昵称"

            remind_msg = self.remind_message.replace("[sender_id]", str(sender_id)).replace("[group_id]", str(group_id))
            remind_msg = f"{remind_msg}，用户昵称：{nickname}"  # 添加群昵称到提醒消息中
            for remind_group_id in self.remind_group_ids:
                try:
                    await client.send_group_msg(
                        group_id=int(remind_group_id),
                        message=remind_msg,
                        self_id=int(self_id)
                    )
                    logger.info(f"Sent remind message to group {remind_group_id}: {remind_msg}")
                except Exception as e:
                    logger.error(f"Failed to send remind message to group {remind_group_id}: {e}")

    async def _send_warning_message(self, client, group_id, sender_id, self_id):
        """发送警告消息"""
        if self.enable_warning and group_id in self.warning_group_ids:
            current_time = time.time()
            last_warning = self.last_warning_time.get(sender_id, 0)
            if current_time - last_warning > self.warning_cool_down:
                warning_msg = f"[CQ:at,qq={sender_id}]{self.warning_message}"
                try:
                    await client.send_group_msg(
                        group_id=int(group_id),
                        message=warning_msg,
                        self_id=int(self_id)
                    )
                    logger.info(f"Sent warning message to user {sender_id} in group {group_id}: {warning_msg}")
                    self.last_warning_time[sender_id] = current_time
                except Exception as e:
                    logger.error(f"Failed to send warning message to user {sender_id} in group {group_id}: {e}")

    async def _kick_user(self, client, group_id, sender_id, self_id):
        """独立的移除群聊模块"""
        try:
            await client.set_group_kick(
                group_id=int(group_id),
                user_id=sender_id,
                self_id=int(self_id)
            )
            logger.info(f"Kicked user: {sender_id} from group {group_id}")
        except Exception as e:
            logger.error(f"Failed to kick user: {e}")

    @event_message_type(EventMessageType.GROUP_MESSAGE)
    async def detect_spam(self, event: AstrMessageEvent):
        """
        检测消息是否为高频无意义消息
        :param event: 消息事件
        """
        current_time = time.time()
        group_id = event.get_group_id()
        # 检查当前群组是否在检测群组列表中
        if str(group_id) not in self.detection_group_ids:
            logger.info(f"群 {group_id} 不在高频无意义消息检测和撤回生效群聊列表中，跳过检测")
            return

        sender_id_value = event.get_sender_id()
        if isinstance(sender_id_value, str):
            if sender_id_value.isdigit():
                sender_id = int(sender_id_value)
            else:
                logger.error(f"Invalid sender ID: {sender_id_value}")
                return
        elif isinstance(sender_id_value, int):
            sender_id = sender_id_value
        else:
            logger.error(f"Invalid sender ID type: {type(sender_id_value)}")
            return
        message_id_value = event.message_obj.message_id
        if isinstance(message_id_value, str):
            if message_id_value.isdigit():
                message_id = int(message_id_value)
            else:
                logger.error(f"Invalid message ID: {message_id_value}")
                return
        elif isinstance(message_id_value, int):
            message_id = message_id_value
        else:
            logger.error(f"Invalid message ID type: {type(message_id_value)}")
            return

        # 检查消息中是否包含图片
        messages = event.get_messages()
        image = next((msg for msg in messages if isinstance(msg, Image)), None)
        if image:
            file_id = image.file
            if not file_id:
                yield event.make_result().message("❌ 无法获取图片ID")
                return
            # 这里可以添加图片处理逻辑
            message_content = f"[图片: {file_id}]"
        else:
            # 处理非图片消息
            message_content = "".join([str(comp) for comp in messages])

        if self._is_spam(group_id, message_content, current_time, sender_id, message_id):
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
            assert isinstance(event, AiocqhttpMessageEvent)
            client = event.bot
            try:
                # 检查机器人是否有管理员权限
                member_info = await client.get_group_member_info(
                    group_id=int(group_id),
                    user_id=int(event.get_self_id()),
                    no_cache=True,
                    self_id=int(event.get_self_id())
                )
                if member_info.get('role') not in ['admin', 'owner']:
                    logger.warning(f"机器人在群 {group_id} 中没有管理员权限，无法执行禁言和撤回操作")
                    return

                # 批量撤回无意义消息
                await self._delete_spam_messages(client, group_id, message_content, sender_id, event.get_self_id())

                # 发送提醒消息
                await self._send_remind_message(client, sender_id, group_id, event.get_self_id())

                # 发送警告消息
                await self._send_warning_message(client, group_id, sender_id, event.get_self_id())

                # 执行禁言操作
                if self.enable_anti_spam and str(group_id) in self.anti_spam_group_ids:
                    await self._ban_user(client, group_id, sender_id, event.get_self_id())

                # 执行移除群聊操作
                if self.enable_kick and str(group_id) in self.kick_group_ids:
                    await self._kick_user(client, group_id, sender_id, event.get_self_id())

            except Exception as e:
                logger.error(f"Failed to handle spam message: {e}")

    @command_group("anti_spam")
    def anti_spam(self):
        pass

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("enable")
    async def enable_anti_spam_command(self, event: AstrMessageEvent):
        """开启自动禁言功能"""
        self.enable_anti_spam = True
        yield event.plain_result("自动禁言功能已开启")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("disable")
    async def disable_anti_spam_command(self, event: AstrMessageEvent):
        """关闭自动禁言功能"""
        self.enable_anti_spam = False
        yield event.plain_result("自动禁言功能已关闭")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("set_remind_group")
    async def set_remind_group(self, event: AstrMessageEvent, group_id: str):
        """设置提醒群聊的群组 ID"""
        if group_id not in self.remind_group_ids:
            self.remind_group_ids.append(group_id)
            yield event.plain_result(f"已将群 {group_id} 添加到提醒群聊列表")
        else:
            yield event.plain_result(f"群 {group_id} 已在提醒群聊列表中")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("remove_remind_group")
    async def remove_remind_group(self, event: AstrMessageEvent, group_id: str):
        """从提醒群聊列表中移除群组 ID"""
        if group_id in self.remind_group_ids:
            self.remind_group_ids.remove(group_id)
            yield event.plain_result(f"已将群 {group_id} 从提醒群聊列表中移除")
        else:
            yield event.plain_result(f"群 {group_id} 不在提醒群聊列表中")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("set_warning_group")
    async def set_warning_group(self, event: AstrMessageEvent, group_id: str):
        """设置警告群聊的群组 ID"""
        if group_id not in self.warning_group_ids:
            self.warning_group_ids.append(group_id)
            yield event.plain_result(f"已将群 {group_id} 添加到警告群聊列表")
        else:
            yield event.plain_result(f"群 {group_id} 已在警告群聊列表中")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("remove_warning_group")
    async def remove_warning_group(self, event: AstrMessageEvent, group_id: str):
        """从警告群聊列表中移除群组 ID"""
        if group_id in self.warning_group_ids:
            self.warning_group_ids.remove(group_id)
            yield event.plain_result(f"已将群 {group_id} 从警告群聊列表中移除")
        else:
            yield event.plain_result(f"群 {group_id} 不在警告群聊列表中")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("set_time_window")
    async def set_time_window(self, event: AstrMessageEvent, time_window: float):
        """设置高频无意义信息检测窗口时间"""
        self.time_window = time_window
        yield event.plain_result(f"已将高频无意义信息检测窗口时间设置为 {time_window} 秒")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("set_repeat_threshold")
    async def set_repeat_threshold(self, event: AstrMessageEvent, repeat_threshold: int):
        """设置消息重复次数阈值"""
        self.repeat_threshold = repeat_threshold
        yield event.plain_result(f"已将消息重复次数阈值设置为 {repeat_threshold} 次")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("set_remind_message")
    async def set_remind_message(self, event: AstrMessageEvent, remind_message: str):
        """设置提醒信息内容"""
        self.remind_message = remind_message
        yield event.plain_result(f"已将提醒信息内容设置为: {remind_message}")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("set_warning_message")
    async def set_warning_message(self, event: AstrMessageEvent, warning_message: str):
        """设置警告信息内容"""
        self.warning_message = warning_message
        yield event.plain_result(f"已将警告信息内容设置为: {warning_message}")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("enable_remind")
    async def enable_remind_command(self, event: AstrMessageEvent):
        """开启向提醒群聊发送消息功能"""
        self.enable_remind = True
        yield event.plain_result("已开启向提醒群聊发送消息功能")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("disable_remind")
    async def disable_remind_command(self, event: AstrMessageEvent):
        """关闭向提醒群聊发送消息功能"""
        self.enable_remind = False
        yield event.plain_result("已关闭向提醒群聊发送消息功能")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("enable_warning")
    async def enable_warning_command(self, event: AstrMessageEvent):
        """开启向警告群聊发送消息功能"""
        self.enable_warning = True
        yield event.plain_result("已开启向警告群聊发送消息功能")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("disable_warning")
    async def disable_warning_command(self, event: AstrMessageEvent):
        """关闭向警告群聊发送消息功能"""
        self.enable_warning = False
        yield event.plain_result("已关闭向警告群聊发送消息功能")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("set_anti_spam_group")
    async def set_anti_spam_group(self, event: AstrMessageEvent, group_id: str):
        """设置自动禁言功能生效的群组 ID"""
        if group_id not in self.anti_spam_group_ids:
            self.anti_spam_group_ids.append(group_id)
            yield event.plain_result(f"已将群 {group_id} 添加到自动禁言功能生效群聊列表")
        else:
            yield event.plain_result(f"群 {group_id} 已在自动禁言功能生效群聊列表中")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("remove_anti_spam_group")
    async def remove_anti_spam_group(self, event: AstrMessageEvent, group_id: str):
        """从自动禁言功能生效群聊列表中移除群组 ID"""
        if group_id in self.anti_spam_group_ids:
            self.anti_spam_group_ids.remove(group_id)
            yield event.plain_result(f"已将群 {group_id} 从自动禁言功能生效群聊列表中移除")
        else:
            yield event.plain_result(f"群 {group_id} 不在自动禁言功能生效群聊列表中")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("set_detection_group")
    async def set_detection_group(self, event: AstrMessageEvent, group_id: str):
        """设置高频无意义消息检测和撤回生效的群组 ID"""
        if group_id not in self.detection_group_ids:
            self.detection_group_ids.append(group_id)
            yield event.plain_result(f"已将群 {group_id} 添加到高频无意义消息检测和撤回生效群聊列表")
        else:
            yield event.plain_result(f"群 {group_id} 已在高频无意义消息检测和撤回生效群聊列表中")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("remove_detection_group")
    async def remove_detection_group(self, event: AstrMessageEvent, group_id: str):
        """从高频无意义消息检测和撤回生效群聊列表中移除群组 ID"""
        if group_id in self.detection_group_ids:
            self.detection_group_ids.remove(group_id)
            yield event.plain_result(f"已将群 {group_id} 从高频无意义消息检测和撤回生效群聊列表中移除")
        else:
            yield event.plain_result(f"群 {group_id} 不在高频无意义消息检测和撤回生效群聊列表中")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("enable_kick")
    async def enable_kick_command(self, event: AstrMessageEvent):
        """开启自动移除群聊功能"""
        self.enable_kick = True
        yield event.plain_result("自动移除群聊功能已开启")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("disable_kick")
    async def disable_kick_command(self, event: AstrMessageEvent):
        """关闭自动移除群聊功能"""
        self.enable_kick = False
        yield event.plain_result("自动移除群聊功能已关闭")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("set_kick_group")
    async def set_kick_group(self, event: AstrMessageEvent, group_id: str):
        """设置自动移除群聊功能生效的群组 ID"""
        if group_id not in self.kick_group_ids:
            self.kick_group_ids.append(group_id)
            yield event.plain_result(f"已将群 {group_id} 添加到自动移除群聊功能生效群聊列表")
        else:
            yield event.plain_result(f"群 {group_id} 已在自动移除群聊功能生效群聊列表中")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("remove_kick_group")
    async def remove_kick_group(self, event: AstrMessageEvent, group_id: str):
        """从自动移除群聊功能生效群聊列表中移除群组 ID"""
        if group_id in self.kick_group_ids:
            self.kick_group_ids.remove(group_id)
            yield event.plain_result(f"已将群 {group_id} 从自动移除群聊功能生效群聊列表中移除")
        else:
            yield event.plain_result(f"群 {group_id} 不在自动移除群聊功能生效群聊列表中")

    @permission_type(PermissionType.ADMIN)
    @anti_spam.command("set_ban_duration")
    async def set_ban_duration(self, event: AstrMessageEvent, ban_duration: int):
        """设置自动禁言的时长"""
        if ban_duration > 0:
            self.ban_duration = ban_duration
            yield event.plain_result(f"已将自动禁言时长设置为 {ban_duration} 秒")
        else:
            yield event.plain_result("禁言时长必须大于 0 秒，请重新输入。")

    async def terminate(self):
        '''当插件被卸载/停用时会调用。'''
        pass
