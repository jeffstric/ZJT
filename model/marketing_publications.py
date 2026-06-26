"""Model helpers for public marketing inspiration publications."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .database import execute_insert, execute_query, execute_update


class PublicationStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    HIDDEN = "hidden"
    CANCELLED = "cancelled"

    REVIEWABLE = {PENDING}
    PUBLIC = {APPROVED}
    ACTIVE_BY_AI_TOOL = {PENDING, APPROVED, HIDDEN}


class MarketingPublication:
    """Public marketing publication row."""

    def __init__(self, **kwargs):
        self.id = kwargs.get("id")
        self.ai_tool_id = kwargs.get("ai_tool_id")
        self.owner_user_id = kwargs.get("owner_user_id")
        self.media_type = kwargs.get("media_type")
        self.title = kwargs.get("title")
        self.description = kwargs.get("description")
        self.tags_json = kwargs.get("tags_json")
        self.result_url = kwargs.get("result_url")
        self.cover_url = kwargs.get("cover_url")
        self.prompt_snapshot = kwargs.get("prompt_snapshot")
        self.params_snapshot_json = kwargs.get("params_snapshot_json")
        self.status = kwargs.get("status")
        self.reviewer_user_id = kwargs.get("reviewer_user_id")
        self.review_note = kwargs.get("review_note")
        self.submitted_at = kwargs.get("submitted_at")
        self.reviewed_at = kwargs.get("reviewed_at")
        self.published_at = kwargs.get("published_at")
        self.like_count = kwargs.get("like_count", 0)
        self.remix_count = kwargs.get("remix_count", 0)
        self.sort_weight = kwargs.get("sort_weight", 0)
        self.created_at = kwargs.get("created_at")
        self.updated_at = kwargs.get("updated_at")
        self.owner_phone = kwargs.get("owner_phone")
        self.owner_email = kwargs.get("owner_email")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "ai_tool_id": self.ai_tool_id,
            "owner_user_id": self.owner_user_id,
            "owner_phone": self.owner_phone,
            "owner_email": self.owner_email,
            "media_type": self.media_type,
            "title": self.title,
            "description": self.description,
            "tags": self._decode_json(self.tags_json, []),
            "result_url": self.result_url,
            "cover_url": self.cover_url,
            "prompt_snapshot": self.prompt_snapshot,
            "params_snapshot": self._decode_json(self.params_snapshot_json, {}),
            "status": self.status,
            "reviewer_user_id": self.reviewer_user_id,
            "review_note": self.review_note,
            "submitted_at": self._dt(self.submitted_at),
            "reviewed_at": self._dt(self.reviewed_at),
            "published_at": self._dt(self.published_at),
            "like_count": self.like_count or 0,
            "remix_count": self.remix_count or 0,
            "sort_weight": self.sort_weight or 0,
            "created_at": self._dt(self.created_at),
            "updated_at": self._dt(self.updated_at),
        }

    @staticmethod
    def _decode_json(value: Any, default: Any) -> Any:
        if value in (None, ""):
            return default
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _dt(value: Any) -> Optional[str]:
        return value.isoformat() if hasattr(value, "isoformat") else value


class MarketingPublicationModel:
    """Database operations for marketing_publications."""

    @staticmethod
    def create_pending(
        ai_tool_id: int,
        owner_user_id: int,
        media_type: str,
        title: str,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        result_url: Optional[str] = None,
        cover_url: Optional[str] = None,
        prompt_snapshot: Optional[str] = None,
        params_snapshot: Optional[Dict[str, Any]] = None,
    ) -> int:
        sql = """
            INSERT INTO marketing_publications
            (ai_tool_id, owner_user_id, media_type, title, description, tags_json,
             result_url, cover_url, prompt_snapshot, params_snapshot_json, status,
             submitted_at, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), NOW())
        """
        params = (
            ai_tool_id,
            owner_user_id,
            media_type,
            title,
            description,
            json.dumps(tags or [], ensure_ascii=False),
            result_url,
            cover_url,
            prompt_snapshot,
            json.dumps(params_snapshot or {}, ensure_ascii=False),
            PublicationStatus.PENDING,
        )
        return execute_insert(sql, params)

    @staticmethod
    def update_assets(
        publication_id: int,
        result_url: str,
        cover_url: str,
        params_snapshot: Dict[str, Any],
    ) -> int:
        sql = """
            UPDATE marketing_publications
            SET result_url = %s,
                cover_url = %s,
                params_snapshot_json = %s,
                updated_at = NOW()
            WHERE id = %s
        """
        return execute_update(
            sql,
            (
                result_url,
                cover_url,
                json.dumps(params_snapshot or {}, ensure_ascii=False),
                publication_id,
            ),
        )

    @staticmethod
    def get_by_id(publication_id: int) -> Optional[MarketingPublication]:
        sql = "SELECT * FROM marketing_publications WHERE id = %s"
        row = execute_query(sql, (publication_id,), fetch_one=True)
        return MarketingPublication(**row) if row else None

    @staticmethod
    def get_active_by_ai_tool_id(ai_tool_id: int) -> Optional[MarketingPublication]:
        statuses = list(PublicationStatus.ACTIVE_BY_AI_TOOL)
        placeholders = ",".join(["%s"] * len(statuses))
        sql = f"""
            SELECT * FROM marketing_publications
            WHERE ai_tool_id = %s AND status IN ({placeholders})
            ORDER BY created_at DESC
            LIMIT 1
        """
        row = execute_query(sql, tuple([ai_tool_id] + statuses), fetch_one=True)
        return MarketingPublication(**row) if row else None

    @staticmethod
    def list_by_owner(owner_user_id: int, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        return MarketingPublicationModel._list(
            where_conditions=["owner_user_id = %s"],
            params=[owner_user_id],
            page=page,
            page_size=page_size,
            order_clause="created_at DESC",
        )

    @staticmethod
    def list_public(
        page: int = 1,
        page_size: int = 20,
        media_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        conditions = ["status = %s", "result_url IS NOT NULL", "result_url != ''"]
        params: List[Any] = [PublicationStatus.APPROVED]
        if media_type in ("image", "video"):
            conditions.append("media_type = %s")
            params.append(media_type)
        return MarketingPublicationModel._list(
            where_conditions=conditions,
            params=params,
            page=page,
            page_size=page_size,
            order_clause="sort_weight DESC, published_at DESC, id DESC",
        )

    @staticmethod
    def list_admin(
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        conditions = ["1 = 1"]
        params: List[Any] = []
        if status:
            conditions.append("p.status = %s")
            params.append(status)
        if media_type in ("image", "video"):
            conditions.append("p.media_type = %s")
            params.append(media_type)

        where_clause = " AND ".join(conditions)
        count_sql = f"SELECT COUNT(*) as total FROM marketing_publications p WHERE {where_clause}"
        total_row = execute_query(count_sql, tuple(params), fetch_one=True)
        total = total_row["total"] if total_row else 0
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT p.*, u.phone as owner_phone, u.email as owner_email
            FROM marketing_publications p
            LEFT JOIN users u ON u.id = p.owner_user_id
            WHERE {where_clause}
            ORDER BY p.submitted_at DESC, p.id DESC
            LIMIT %s OFFSET %s
        """
        rows = execute_query(data_sql, tuple(params + [page_size, offset]), fetch_all=True) or []
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "data": [MarketingPublication(**row).to_dict() for row in rows],
        }

    @staticmethod
    def update_review_status(
        publication_id: int,
        status: str,
        reviewer_user_id: int,
        review_note: Optional[str] = None,
    ) -> int:
        published_expr = "NOW()" if status == PublicationStatus.APPROVED else "published_at"
        sql = f"""
            UPDATE marketing_publications
            SET status = %s,
                reviewer_user_id = %s,
                review_note = %s,
                reviewed_at = NOW(),
                published_at = {published_expr},
                updated_at = NOW()
            WHERE id = %s
        """
        return execute_update(sql, (status, reviewer_user_id, review_note, publication_id))

    @staticmethod
    def cancel(publication_id: int, owner_user_id: int) -> int:
        sql = """
            UPDATE marketing_publications
            SET status = %s, updated_at = NOW()
            WHERE id = %s AND owner_user_id = %s AND status = %s
        """
        return execute_update(
            sql,
            (PublicationStatus.CANCELLED, publication_id, owner_user_id, PublicationStatus.PENDING),
        )

    @staticmethod
    def increment_remix_count(publication_id: int) -> int:
        sql = """
            UPDATE marketing_publications
            SET remix_count = remix_count + 1, updated_at = NOW()
            WHERE id = %s AND status = %s
        """
        return execute_update(sql, (publication_id, PublicationStatus.APPROVED))

    @staticmethod
    def _list(
        where_conditions: List[str],
        params: List[Any],
        page: int,
        page_size: int,
        order_clause: str,
    ) -> Dict[str, Any]:
        where_clause = " AND ".join(where_conditions)
        count_sql = f"SELECT COUNT(*) as total FROM marketing_publications WHERE {where_clause}"
        total_row = execute_query(count_sql, tuple(params), fetch_one=True)
        total = total_row["total"] if total_row else 0
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM marketing_publications
            WHERE {where_clause}
            ORDER BY {order_clause}
            LIMIT %s OFFSET %s
        """
        rows = execute_query(data_sql, tuple(params + [page_size, offset]), fetch_all=True) or []
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "data": [MarketingPublication(**row).to_dict() for row in rows],
        }


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `marketing_publications` (
  `id` int NOT NULL AUTO_INCREMENT,
  `ai_tool_id` int NOT NULL COMMENT '关联 ai_tools.id',
  `owner_user_id` int NOT NULL COMMENT '发布用户ID',
  `media_type` varchar(20) NOT NULL COMMENT 'image/video',
  `title` varchar(255) NOT NULL COMMENT '公开标题',
  `description` text DEFAULT NULL COMMENT '公开描述',
  `tags_json` text DEFAULT NULL COMMENT '标签 JSON',
  `result_url` text DEFAULT NULL COMMENT '长期结果文件 URL',
  `cover_url` text DEFAULT NULL COMMENT '长期封面 URL',
  `prompt_snapshot` text DEFAULT NULL COMMENT '发布时提示词快照',
  `params_snapshot_json` mediumtext DEFAULT NULL COMMENT '做同款参数快照 JSON',
  `status` varchar(20) NOT NULL DEFAULT 'pending' COMMENT 'pending/approved/rejected/hidden/cancelled',
  `reviewer_user_id` int DEFAULT NULL COMMENT '审核管理员ID',
  `review_note` text DEFAULT NULL COMMENT '审核备注',
  `submitted_at` datetime DEFAULT NULL,
  `reviewed_at` datetime DEFAULT NULL,
  `published_at` datetime DEFAULT NULL,
  `like_count` int NOT NULL DEFAULT 0,
  `remix_count` int NOT NULL DEFAULT 0,
  `sort_weight` int NOT NULL DEFAULT 0,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_ai_tool_id` (`ai_tool_id`),
  KEY `idx_owner_status` (`owner_user_id`,`status`,`created_at`),
  KEY `idx_public_feed` (`status`,`media_type`,`sort_weight`,`published_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""
