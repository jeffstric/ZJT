"""
AnnouncementService 本站公告服务 - 公告发布/已读等业务逻辑

数据流：管理员在 /admin 后台创建公告（草稿 -> 发布）-> 用户端首页铃铛轮询未读数 ->
       展开通知面板拉取公告列表（带 per-user 已读标记）-> 点击标记已读。
与 services/notification_service.py（远程拉取的全局公告）相互独立。
"""
from datetime import datetime
from typing import Dict, Any, List, Optional
import logging

from config.constant import AnnouncementConstants
from model.announcements import (
    AnnouncementsModel,
    AnnouncementStatus,
    VALID_LEVELS,
)
from model.announcement_reads import AnnouncementReadsModel

logger = logging.getLogger(__name__)


class AnnouncementService:
    """本站公告服务"""

    # ============ 用户侧 ============

    @staticmethod
    def list_for_user(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """用户侧公告列表（仅 published 且在有效期内，带已读标记）"""
        items = AnnouncementsModel.list_for_user(user_id, limit=limit)
        return [item.to_dict() for item in items]

    @staticmethod
    def get_unread_count(user_id: int) -> int:
        """用户未读公告数（铃铛徽标轮询）"""
        return AnnouncementsModel.get_unread_count_for_user(user_id)

    @staticmethod
    def mark_read(user_id: int, announcement_id: int) -> Dict[str, Any]:
        """标记单条公告已读"""
        announcement = AnnouncementsModel.get_by_id(announcement_id)
        if not announcement:
            return {'success': False, 'message': '公告不存在'}
        AnnouncementReadsModel.mark_read(announcement_id, user_id)
        return {'success': True}

    @staticmethod
    def mark_all_read(user_id: int) -> int:
        """标记全部有效公告已读，返回新标记条数"""
        return AnnouncementReadsModel.mark_all_read(user_id)

    # ============ 管理侧 ============

    @staticmethod
    def _normalize_datetime_str(value: Optional[str]) -> Optional[str]:
        """datetime-local 前端值 'YYYY-MM-DDTHH:MM' 归一化为 MySQL datetime 格式"""
        if not value:
            return None
        return value.strip().replace('T', ' ') or None

    @staticmethod
    def _validate_datetime_str(value: Optional[str], field_label: str) -> Optional[str]:
        """校验归一化后的时间字符串格式，返回错误信息或 None。

        不合法值直接在服务层拒绝（而非落库时让 SQL 报错原文透出客户端）。
        naive datetime 语义：与 MySQL NOW() 同以部署时区为准，要求应用与
        数据库时区保持一致（见 docs/backend/announcements.md）。
        """
        if not value:
            return None
        for fmt in AnnouncementConstants.DATETIME_FORMATS:
            try:
                datetime.strptime(value, fmt)
                return None
            except ValueError:
                continue
        return f"{field_label} 格式无效: {value}，应为 YYYY-MM-DD HH:MM(:SS)"

    @staticmethod
    def _validate_payload(
        title: str,
        level: str,
        link_url: Optional[str],
        images: Optional[List[str]],
        publish_at: Optional[str] = None,
        expire_at: Optional[str] = None,
    ) -> Optional[str]:
        """创建/编辑公共字段校验，返回错误信息或 None"""
        if not title or not title.strip():
            return '公告标题不能为空'
        if level not in VALID_LEVELS:
            return f"无效的公告级别: {level}，可选 {VALID_LEVELS}"
        if link_url and not link_url.startswith(('http://', 'https://')):
            return '链接必须以 http:// 或 https:// 开头'
        for url in (images or []):
            if not isinstance(url, str) or not url.startswith(('/', 'http://', 'https://')):
                return '图片地址无效'
        for value, label in ((publish_at, '定时发布时间'), (expire_at, '失效时间')):
            error = AnnouncementService._validate_datetime_str(value, label)
            if error:
                return error
        return None

    @staticmethod
    def create(admin_user_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """管理员创建公告（status: draft 或直接 published）"""
        title = (payload.get('title') or '').strip()
        level = payload.get('level') or 'info'
        link_url = (payload.get('link_url') or '').strip() or None
        images = payload.get('images') or []
        publish_at = AnnouncementService._normalize_datetime_str(payload.get('publish_at'))
        expire_at = AnnouncementService._normalize_datetime_str(payload.get('expire_at'))

        error = AnnouncementService._validate_payload(
            title, level, link_url, images, publish_at, expire_at
        )
        if error:
            return {'success': False, 'message': error}

        status = payload.get('status') or AnnouncementStatus.DRAFT
        if status not in (AnnouncementStatus.DRAFT, AnnouncementStatus.PUBLISHED):
            return {'success': False, 'message': f'创建时状态仅支持 draft/published，收到: {status}'}

        announcement_id = AnnouncementsModel.create(
            title=title,
            content=payload.get('content') or '',
            link_url=link_url,
            link_text=(payload.get('link_text') or '').strip() or None,
            images=images,
            level=level,
            status=status,
            publish_at=publish_at,
            expire_at=expire_at,
            created_by=admin_user_id,
        )
        return {'success': True, 'id': announcement_id}

    @staticmethod
    def update(announcement_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """管理员编辑公告（不改状态）"""
        announcement = AnnouncementsModel.get_by_id(announcement_id)
        if not announcement:
            return {'success': False, 'message': '公告不存在'}

        title = (payload.get('title') or '').strip()
        level = payload.get('level') or announcement.level
        link_url = (payload.get('link_url') or '').strip() or None
        images = payload.get('images') if payload.get('images') is not None else announcement.images
        publish_at = AnnouncementService._normalize_datetime_str(payload.get('publish_at'))
        expire_at = AnnouncementService._normalize_datetime_str(payload.get('expire_at'))

        error = AnnouncementService._validate_payload(
            title, level, link_url, images, publish_at, expire_at
        )
        if error:
            return {'success': False, 'message': error}

        AnnouncementsModel.update(
            announcement_id,
            title=title,
            content=payload.get('content') if payload.get('content') is not None else announcement.content,
            link_url=link_url,
            link_text=(payload.get('link_text') or '').strip() or None,
            images=images,
            level=level,
            publish_at=publish_at,
            expire_at=expire_at,
        )
        # 不以 affected>0 判定成功：pymysql 默认只计"值变化"的行，同值保存
        # 会 affected=0 被误报失败。入口已确认公告存在，UPDATE 未抛异常即成功；
        # 极小概率的并发删除由二次确认兜底。
        if not AnnouncementsModel.get_by_id(announcement_id):
            return {'success': False, 'message': '公告不存在'}
        return {'success': True}

    @staticmethod
    def update_status(announcement_id: int, status: str) -> Dict[str, Any]:
        """发布/下线状态机：draft -> published -> offline，offline/draft 可重新发布"""
        if status not in (AnnouncementStatus.DRAFT, AnnouncementStatus.PUBLISHED, AnnouncementStatus.OFFLINE):
            return {'success': False, 'message': f'无效的公告状态: {status}'}

        announcement = AnnouncementsModel.get_by_id(announcement_id)
        if not announcement:
            return {'success': False, 'message': '公告不存在'}

        AnnouncementsModel.update_status(announcement_id, status)
        # 同上：同值状态保存（如对已发布公告再点发布）不以 affected>0 误报失败
        if not AnnouncementsModel.get_by_id(announcement_id):
            return {'success': False, 'message': '公告不存在'}
        return {'success': True}

    @staticmethod
    def delete(admin_user_id: int, announcement_id: int) -> Dict[str, Any]:
        """管理员删除公告，事务内级联清理已读记录（不留孤儿）"""
        announcement = AnnouncementsModel.get_by_id(announcement_id)
        if not announcement:
            return {'success': False, 'message': '公告不存在'}

        AnnouncementsModel.delete_with_reads(announcement_id)
        logger.info(f"Admin {admin_user_id} deleted announcement {announcement_id}")
        return {'success': True}
