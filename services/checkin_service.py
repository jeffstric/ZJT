"""
CheckinService 签到服务 - 每日签到业务逻辑
"""
from datetime import date, timedelta
from typing import Dict, Any
import json
import logging

from model.daily_checkin import DailyCheckinModel
from perseids_server.services.computing_power_service import ComputingPowerService
from config.config_util import get_dynamic_config_value

logger = logging.getLogger(__name__)


class CheckinService:
    """签到服务"""

    @staticmethod
    def checkin(user_id: int) -> Dict[str, Any]:
        """
        执行每日签到

        Args:
            user_id: 用户ID

        Returns:
            签到结果
        """
        # 1. 检查功能是否启用
        enabled = get_dynamic_config_value('checkin', 'enabled', default=True)
        if not enabled:
            return {
                'success': False,
                'message': '签到功能暂未开启'
            }

        # 2. 检查是否已签到
        today = date.today()
        existing = DailyCheckinModel.get_by_user_and_date(user_id, today)
        if existing:
            return {
                'success': False,
                'message': '今日已签到',
                'data': {
                    'checked_in_today': True,
                    'streak_days': existing.streak_days,
                    'reward_amount': existing.reward_amount
                }
            }

        # 3. 计算连续签到天数
        streak_days = 1
        latest = DailyCheckinModel.get_latest_by_user(user_id)
        if latest and latest.checkin_date == today - timedelta(days=1):
            streak_days = latest.streak_days + 1

        # 4. 计算奖励
        base_reward = int(get_dynamic_config_value('checkin', 'base_reward', default=10))
        bonus_reward = 0

        streak_bonus_enabled = get_dynamic_config_value('checkin', 'streak_bonus_enabled', default=True)
        if streak_bonus_enabled:
            streak_config = get_dynamic_config_value('checkin', 'streak_bonus_config', default={})
            if isinstance(streak_config, str):
                try:
                    streak_config = json.loads(streak_config)
                except (json.JSONDecodeError, TypeError):
                    streak_config = {}

            if streak_config:
                # 找到 <= 当前连续天数的最大匹配奖励
                for threshold in sorted(streak_config.keys(), key=lambda k: int(k)):
                    if streak_days >= int(threshold):
                        bonus_reward = int(streak_config[threshold])

        reward_amount = base_reward + bonus_reward

        # 5. 创建签到记录（捕获并发冲突）
        transaction_id = f"checkin_{user_id}_{today.strftime('%Y%m%d')}"
        try:
            DailyCheckinModel.create(
                user_id=user_id,
                checkin_date=today,
                streak_days=streak_days,
                base_reward=base_reward,
                bonus_reward=bonus_reward,
                reward_amount=reward_amount,
                transaction_id=transaction_id
            )
        except Exception as create_err:
            err_msg = str(create_err).lower()
            if 'duplicate' in err_msg or 'unique' in err_msg or '1062' in err_msg:
                return {
                    'success': False,
                    'message': '今日已签到',
                    'data': {
                        'checked_in_today': True,
                        'streak_days': streak_days,
                        'reward_amount': reward_amount
                    }
                }
            logger.error(f"创建签到记录失败 user_id={user_id}: {create_err}")
            return {
                'success': False,
                'message': '签到失败，请稍后重试'
            }

        # 6. 发放算力
        try:
            cp_result = ComputingPowerService.calculate_computing_power(
                user_id=user_id,
                computing_power=reward_amount,
                behavior='increase',
                transaction_id=transaction_id,
                message='每日签到奖励',
                note=f'连续签到{streak_days}天' if streak_days > 1 else '每日签到'
            )
            if not cp_result.get('success'):
                if cp_result.get('message') == '该交易已处理':
                    return {
                        'success': False,
                        'message': '今日已签到（算力已发放）',
                        'data': {
                            'checked_in_today': True,
                            'streak_days': streak_days,
                            'reward_amount': reward_amount
                        }
                    }
                logger.error(f"签到发放算力失败 user_id={user_id}: {cp_result}")
                return {
                    'success': False,
                    'message': '签到成功但算力发放失败，请联系管理员'
                }
        except Exception as e:
            logger.error(f"签到发放算力失败 user_id={user_id}: {e}")
            return {
                'success': False,
                'message': '签到成功但算力发放失败，请联系管理员'
            }

        return {
            'success': True,
            'message': '签到成功',
            'data': {
                'checked_in_today': True,
                'streak_days': streak_days,
                'base_reward': base_reward,
                'bonus_reward': bonus_reward,
                'reward_amount': reward_amount
            }
        }

    @staticmethod
    def get_checkin_status(user_id: int) -> Dict[str, Any]:
        """
        获取用户签到状态

        Args:
            user_id: 用户ID

        Returns:
            签到状态信息
        """
        enabled = get_dynamic_config_value('checkin', 'enabled', default=True)

        today = date.today()
        today_checkin = DailyCheckinModel.get_by_user_and_date(user_id, today)

        # 获取连续天数
        streak_days = 0
        if today_checkin:
            streak_days = today_checkin.streak_days
        else:
            latest = DailyCheckinModel.get_latest_by_user(user_id)
            if latest and latest.checkin_date == today - timedelta(days=1):
                streak_days = latest.streak_days

        # 计算明天签到可获得的额外奖励预览
        next_bonus = 0
        base_reward = int(get_dynamic_config_value('checkin', 'base_reward', default=10))
        streak_bonus_enabled = get_dynamic_config_value('checkin', 'streak_bonus_enabled', default=True)
        streak_config = {}
        if streak_bonus_enabled:
            raw_config = get_dynamic_config_value('checkin', 'streak_bonus_config', default={})
            if isinstance(raw_config, str):
                try:
                    streak_config = json.loads(raw_config)
                except (json.JSONDecodeError, TypeError):
                    streak_config = {}
            else:
                streak_config = raw_config
            if streak_config:
                next_streak = streak_days + 1
                for threshold in sorted(streak_config.keys(), key=lambda k: int(k)):
                    if next_streak >= int(threshold):
                        next_bonus = int(streak_config[threshold])

        # 计算距离下一个奖励阶梯还有多久
        days_to_next_reward = None
        next_reward_amount = None
        if streak_config:
            next_streak = streak_days + 1
            sorted_thresholds = sorted(streak_config.keys(), key=lambda k: int(k))
            # 找到下一个能获得更高奖励的阈值
            for threshold in sorted_thresholds:
                t = int(threshold)
                if t > next_streak and int(streak_config[threshold]) > next_bonus:
                    days_to_next_reward = t - next_streak
                    next_reward_amount = int(streak_config[threshold])
                    break

        return {
            'success': True,
            'data': {
                'checkin_enabled': bool(enabled),
                'checked_in_today': today_checkin is not None,
                'streak_days': streak_days,
                'base_reward': base_reward,
                'next_bonus': next_bonus,
                'days_to_next_reward': days_to_next_reward,
                'next_reward_amount': next_reward_amount
            }
        }
