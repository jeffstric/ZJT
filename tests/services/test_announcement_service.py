"""
AnnouncementService 单元测试

测试公告服务的字段校验、状态机与级联删除逻辑（mock 数据层）。
"""
from unittest.mock import patch, MagicMock

import pytest

from model.announcements import AnnouncementStatus
from services.announcement_service import AnnouncementService


def _announcement(**overrides):
    base = dict(
        id=1, title="智剧通9月征稿", content="正文", link_url=None, link_text=None,
        images=[], level='info', status=AnnouncementStatus.PUBLISHED,
        publish_at=None, expire_at=None, created_by=1,
    )
    base.update(overrides)
    return MagicMock(**base)


class TestValidatePayload:
    def test_empty_title_rejected(self):
        error = AnnouncementService._validate_payload("  ", 'info', None, [])
        assert error and '标题' in error

    def test_invalid_level_rejected(self):
        error = AnnouncementService._validate_payload("标题", 'hot', None, [])
        assert error and '级别' in error

    def test_valid_levels_accepted(self):
        for level in ('info', 'success', 'warning', 'error'):
            assert AnnouncementService._validate_payload("标题", level, None, []) is None

    def test_link_must_be_http(self):
        assert AnnouncementService._validate_payload("标题", 'info', 'javascript:alert(1)', []) is not None
        assert AnnouncementService._validate_payload("标题", 'info', 'https://example.com', []) is None

    def test_image_urls_must_be_path_or_http(self):
        assert AnnouncementService._validate_payload("标题", 'info', None, ['/upload/a.png']) is None
        assert AnnouncementService._validate_payload("标题", 'info', None, ['https://cdn/a.png']) is None
        assert AnnouncementService._validate_payload("标题", 'info', None, ['ftp://x/a.png']) is not None


class TestNormalizeDatetime:
    def test_datetime_local_value(self):
        assert AnnouncementService._normalize_datetime_str('2026-09-06T10:30') == '2026-09-06 10:30'

    def test_empty_to_none(self):
        assert AnnouncementService._normalize_datetime_str('') is None
        assert AnnouncementService._normalize_datetime_str(None) is None


class TestCreate:
    def test_create_as_draft(self):
        with patch('services.announcement_service.AnnouncementsModel.create', return_value=7) as m:
            result = AnnouncementService.create(1, {'title': '  新功能上线  ', 'status': 'draft'})
        assert result == {'success': True, 'id': 7}
        kwargs = m.call_args.kwargs
        assert kwargs['title'] == '新功能上线'
        assert kwargs['status'] == AnnouncementStatus.DRAFT
        assert kwargs['created_by'] == 1

    def test_create_published_directly(self):
        with patch('services.announcement_service.AnnouncementsModel.create', return_value=8) as m:
            result = AnnouncementService.create(1, {'title': 'T', 'status': 'published'})
        assert result['success']
        assert m.call_args.kwargs['status'] == AnnouncementStatus.PUBLISHED

    def test_create_rejects_invalid_status(self):
        result = AnnouncementService.create(1, {'title': 'T', 'status': 'offline'})
        assert not result['success']

    def test_create_rejects_empty_title(self):
        result = AnnouncementService.create(1, {'title': '   '})
        assert not result['success'] and '标题' in result['message']


class TestUpdateStatus:
    def test_publish(self):
        with patch('services.announcement_service.AnnouncementsModel.get_by_id', return_value=_announcement(status='draft')):
            with patch('services.announcement_service.AnnouncementsModel.update_status', return_value=1) as m:
                result = AnnouncementService.update_status(1, AnnouncementStatus.PUBLISHED)
        assert result['success']
        assert m.call_args.args == (1, AnnouncementStatus.PUBLISHED)

    def test_not_found(self):
        with patch('services.announcement_service.AnnouncementsModel.get_by_id', return_value=None):
            result = AnnouncementService.update_status(999, AnnouncementStatus.PUBLISHED)
        assert not result['success'] and '不存在' in result['message']

    def test_invalid_status_value(self):
        result = AnnouncementService.update_status(1, 'archived')
        assert not result['success']


class TestUpdate:
    def test_update_keeps_status(self):
        existing = _announcement(id=3, status=AnnouncementStatus.PUBLISHED)
        with patch('services.announcement_service.AnnouncementsModel.get_by_id', return_value=existing):
            with patch('services.announcement_service.AnnouncementsModel.update', return_value=1) as m:
                result = AnnouncementService.update(3, {'title': '新标题'})
        assert result['success']
        kwargs = m.call_args.kwargs
        assert kwargs['title'] == '新标题'
        # update 不触碰 status
        assert 'status' not in kwargs

    def test_update_not_found(self):
        with patch('services.announcement_service.AnnouncementsModel.get_by_id', return_value=None):
            result = AnnouncementService.update(999, {'title': 'T'})
        assert not result['success']


class TestDelete:
    def test_delete_cascades_reads(self):
        with patch('services.announcement_service.AnnouncementsModel.get_by_id', return_value=_announcement()):
            with patch('services.announcement_service.AnnouncementsModel.delete_by_id', return_value=1) as m_del:
                with patch('services.announcement_service.AnnouncementReadsModel.delete_by_announcement', return_value=4) as m_reads:
                    result = AnnouncementService.delete(admin_user_id=1, announcement_id=1)
        assert result['success']
        m_del.assert_called_once_with(1)
        m_reads.assert_called_once_with(1)

    def test_delete_not_found(self):
        with patch('services.announcement_service.AnnouncementsModel.get_by_id', return_value=None):
            result = AnnouncementService.delete(1, 999)
        assert not result['success']


class TestUserSide:
    def test_mark_read_missing_announcement(self):
        with patch('services.announcement_service.AnnouncementsModel.get_by_id', return_value=None):
            result = AnnouncementService.mark_read(user_id=7, announcement_id=999)
        assert not result['success']

    def test_mark_read_ok(self):
        with patch('services.announcement_service.AnnouncementsModel.get_by_id', return_value=_announcement()):
            with patch('services.announcement_service.AnnouncementReadsModel.mark_read', return_value=1) as m:
                result = AnnouncementService.mark_read(user_id=7, announcement_id=1)
        assert result['success']
        m.assert_called_once_with(1, 7)

    def test_get_unread_count(self):
        with patch('services.announcement_service.AnnouncementsModel.get_unread_count_for_user', return_value=5) as m:
            assert AnnouncementService.get_unread_count(7) == 5
            m.assert_called_once_with(7)
