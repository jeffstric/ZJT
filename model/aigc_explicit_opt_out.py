"""
AigcExplicitOptOutLog Model - AIGC 显式标识关闭申请留痕（aigc_explicit_opt_out_log 表）

法规依据：《人工智能生成合成内容标识办法》第 9 条——用户申请不添加显式标识的，
服务提供者可在通过用户协议明确用户的标识义务和使用责任后提供，并依法留存
提供对象信息等相关日志不少于 6 个月。

合规要点：
- 本表只增不改（append-only），禁止删除/更新既有留痕记录（删除=隐匿留痕，违反第 10 条）
- 保存期 >= 6 个月（建议 1 年）；由运维归档策略处理过期数据，业务代码不清理
- 写入入口：POST /api/aigc/explicit-optout（前端确认弹窗含协议义务提示后调用）
"""
import logging
from typing import Optional, Dict, Any, List

from .database import execute_query, execute_insert

logger = logging.getLogger(__name__)

# 申请来源
OPT_OUT_SOURCE_CHAT_CARD = 'chat_result_card'    # 聊天流结果卡（数字人/TTS 卡申请关闭）
OPT_OUT_SOURCE_API = 'api'                        # 开放 API 调用


class AigcExplicitOptOutModel:
    """aigc_explicit_opt_out_log 数据库操作（append-only）"""

    @staticmethod
    def create(
        user_id: Optional[int],
        ai_tool_id: Optional[int] = None,
        produce_id: Optional[str] = None,
        content_type: Optional[str] = None,
        request_source: str = OPT_OUT_SOURCE_API,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> int:
        """
        记录一条显式标识关闭申请（法规留痕，只增）

        Args:
            user_id: 申请用户 ID
            ai_tool_id: 关联任务 ID（ai_tools.id）
            produce_id: 内容编号（隐式标识 ProduceID）
            content_type: 内容类型（video/image/audio）
            request_source: 申请来源
            ip: 客户端 IP
            user_agent: User-Agent
            detail: 扩展信息 JSON 字符串

        Returns:
            插入记录 ID
        """
        sql = """
            INSERT INTO aigc_explicit_opt_out_log
            (user_id, ai_tool_id, produce_id, content_type, request_source, ip, user_agent, detail, create_at, update_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """
        params = (user_id, ai_tool_id, produce_id, content_type,
                  request_source, ip, (user_agent or '')[:512], detail)
        try:
            record_id = execute_insert(sql, params)
            logger.info(
                f"[aigc-optout] 留痕记录 id={record_id} user={user_id} "
                f"ai_tool={ai_tool_id} produce={produce_id} source={request_source}")
            return record_id
        except Exception as e:
            logger.error(f"[aigc-optout] 留痕写入失败 user={user_id} ai_tool={ai_tool_id}: {e}")
            raise

    @staticmethod
    def get_by_ai_tool(ai_tool_id: int) -> List[Dict[str, Any]]:
        """查询某任务已存在的关闭申请（用于跳过烧录的幂等判断）"""
        sql = """
            SELECT * FROM aigc_explicit_opt_out_log
            WHERE ai_tool_id = %s
            ORDER BY create_at DESC
        """
        try:
            return execute_query(sql, (ai_tool_id,), fetch_all=True) or []
        except Exception as e:
            logger.error(f"[aigc-optout] 查询失败 ai_tool={ai_tool_id}: {e}")
            return []

    @staticmethod
    def has_opt_out(ai_tool_id: int) -> bool:
        """该任务是否已申请关闭显式标识（L1 烧录挂点跳过依据）"""
        sql = "SELECT COUNT(*) AS cnt FROM aigc_explicit_opt_out_log WHERE ai_tool_id = %s"
        try:
            row = execute_query(sql, (ai_tool_id,), fetch_one=True)
            return bool(row and row.get('cnt'))
        except Exception as e:
            # 查询失败时保守返回 False（烧录继续）——宁可多标识不可漏标识
            logger.warning(f"[aigc-optout] has_opt_out 查询异常按未申请处理 ai_tool={ai_tool_id}: {e}")
            return False

    @staticmethod
    def has_opt_out_user(user_id: Optional[int]) -> bool:
        """该用户是否已申请关闭显式标识（TTS 等用户级 L1 场景：一次申请对其后续合成生效）"""
        if not user_id:
            return False
        sql = "SELECT COUNT(*) AS cnt FROM aigc_explicit_opt_out_log WHERE user_id = %s"
        try:
            row = execute_query(sql, (user_id,), fetch_one=True)
            return bool(row and row.get('cnt'))
        except Exception as e:
            logger.warning(f"[aigc-optout] has_opt_out_user 查询异常按未申请处理 user={user_id}: {e}")
            return False

    @staticmethod
    def list_recent(page: int = 1, page_size: int = 50, user_id: Optional[int] = None) -> Dict[str, Any]:
        """管理侧分页查询留痕记录"""
        where = ""
        params: list = []
        if user_id is not None:
            where = "WHERE user_id = %s"
            params.append(user_id)
        count_sql = f"SELECT COUNT(*) AS total FROM aigc_explicit_opt_out_log {where}"
        count_row = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_row['total'] if count_row else 0
        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM aigc_explicit_opt_out_log {where}
            ORDER BY create_at DESC LIMIT %s OFFSET %s
        """
        params.extend([page_size, offset])
        rows = execute_query(data_sql, tuple(params), fetch_all=True) or []
        return {'total': total, 'page': page, 'page_size': page_size, 'data': rows}


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `aigc_explicit_opt_out_log` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键',
  `user_id` int DEFAULT NULL COMMENT '申请用户ID（第9条：提供对象信息留痕）',
  `ai_tool_id` bigint DEFAULT NULL COMMENT '关联任务ID（ai_tools.id）',
  `produce_id` varchar(128) DEFAULT NULL COMMENT '内容编号（隐式标识 ProduceID）',
  `content_type` varchar(32) DEFAULT NULL COMMENT '内容类型 video/image/audio',
  `request_source` varchar(64) DEFAULT NULL COMMENT '申请来源（chat_result_card/compose_default/api）',
  `ip` varchar(64) DEFAULT NULL COMMENT '申请时客户端IP',
  `user_agent` varchar(512) DEFAULT NULL COMMENT '申请时 User-Agent',
  `detail` text COMMENT '扩展信息 JSON',
  `create_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_aigc_optout_user` (`user_id`),
  KEY `idx_aigc_optout_ai_tool` (`ai_tool_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AIGC显式标识关闭申请留痕（标识办法第9条，留存>=6个月）';
"""
