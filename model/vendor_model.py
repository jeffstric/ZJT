"""
VendorModel Model - 供应商模型配置表
对应Go的models/vendor_model.go
"""
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from model.database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)

_SELECT_COLS = """id, vendor_id, model_id, created_at,
               input_token_threshold, out_token_threshold as output_token_threshold,
               cache_read_threshold, raw_token_threshold, commission_rate, time_period"""


def _to_float_rate(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _row_to_vendor_model(row: dict) -> "VendorModel":
    return VendorModel(
        id=row['id'],
        vendor_id=row['vendor_id'],
        model_id=row['model_id'],
        created_at=row.get('created_at'),
        input_token_threshold=row.get('input_token_threshold'),
        output_token_threshold=row.get('output_token_threshold'),
        cache_read_threshold=row.get('cache_read_threshold'),
        raw_token_threshold=row.get('raw_token_threshold'),
        commission_rate=_to_float_rate(row.get('commission_rate')),
        time_period=row.get('time_period') or 'normal',
    )


class VendorModel:
    """供应商模型配置实体"""

    def __init__(
        self,
        id: int = 0,
        vendor_id: Optional[int] = None,
        model_id: Optional[int] = None,
        created_at: Optional[datetime] = None,
        input_token_threshold: Optional[int] = None,
        output_token_threshold: Optional[int] = None,
        cache_read_threshold: Optional[int] = None,
        raw_token_threshold: Optional[int] = None,
        commission_rate: float = 0.0,
        time_period: str = 'normal',
    ):
        self.id = id
        self.vendor_id = vendor_id
        self.model_id = model_id
        self.created_at = created_at
        self.input_token_threshold = input_token_threshold
        # ⚠️ 命名陷阱：数据库列名为 out_token_threshold，Python 属性名为 output_token_threshold
        self.output_token_threshold = output_token_threshold
        self.cache_read_threshold = cache_read_threshold
        self.raw_token_threshold = raw_token_threshold
        self.commission_rate = float(commission_rate or 0.0)
        # 计费时段：normal=不分峰谷(向后兼容), peak=高峰, off_peak=空闲
        self.time_period = time_period or 'normal'


class VendorModelModel:
    """供应商模型配置数据库操作"""

    @staticmethod
    def create(
        vendor_id: Optional[int] = None,
        model_id: Optional[int] = None,
        input_threshold: Optional[int] = None,
        output_threshold: Optional[int] = None,
        cache_read_threshold: Optional[int] = None,
        raw_token_threshold: Optional[int] = None,
        commission_rate: float = 0.0,
        time_period: str = 'normal',
    ) -> int:
        """创建供应商模型配置"""
        sql = """INSERT INTO vendor_model
               (vendor_id, model_id, input_token_threshold, out_token_threshold,
                cache_read_threshold, raw_token_threshold, commission_rate, time_period)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""
        try:
            rate = float(commission_rate or 0.0)
            period = time_period or 'normal'
            return execute_insert(sql, (
                vendor_id, model_id, input_threshold, output_threshold,
                cache_read_threshold, raw_token_threshold, rate, period,
            ))
        except Exception as e:
            logger.error(f"Failed to create vendor model: {e}")
            raise

    @staticmethod
    def get_by_vendor_model(vendor_id: int, model_id: int) -> Optional[VendorModel]:
        """根据vendor_id和model_id获取配置（不推荐用于计费，请使用get_by_vendor_model_for_billing）"""
        sql = f"""SELECT {_SELECT_COLS}
               FROM vendor_model WHERE vendor_id = %s AND model_id = %s LIMIT 1"""
        try:
            row = execute_query(sql, (vendor_id, model_id), fetch_one=True)
            return _row_to_vendor_model(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get vendor model (vendor:{vendor_id}, model:{model_id}): {e}")
            raise

    @staticmethod
    def get_all(limit: int = 0, offset: int = 0) -> List[VendorModel]:
        """获取所有供应商模型配置"""
        sql = f"""SELECT {_SELECT_COLS}
               FROM vendor_model ORDER BY created_at DESC"""
        params = []
        if limit > 0:
            sql += " LIMIT %s"
            params.append(limit)
            if offset > 0:
                sql += " OFFSET %s"
                params.append(offset)

        try:
            rows = execute_query(sql, tuple(params) if params else None, fetch_all=True)
            return [_row_to_vendor_model(row) for row in rows] if rows else []
        except Exception as e:
            logger.error(f"Failed to get all vendor models: {e}")
            raise

    @staticmethod
    def update_thresholds(
        id: int,
        input_threshold: Optional[int] = None,
        output_threshold: Optional[int] = None,
        cache_read_threshold: Optional[int] = None,
        raw_token_threshold: Optional[int] = None,
        commission_rate: Optional[float] = None,
        time_period: str = 'normal',
    ) -> bool:
        """更新阈值、抽成与时段配置"""
        sql = """UPDATE vendor_model
               SET input_token_threshold = %s, out_token_threshold = %s,
                   cache_read_threshold = %s, raw_token_threshold = %s,
                   commission_rate = %s, time_period = %s
               WHERE id = %s"""
        try:
            rate = 0.0 if commission_rate is None else float(commission_rate)
            period = time_period or 'normal'
            rows = execute_update(sql, (
                input_threshold, output_threshold, cache_read_threshold,
                raw_token_threshold, rate, period, id,
            ))
            return rows > 0
        except Exception as e:
            logger.error(f"Failed to update vendor model thresholds: {e}")
            raise

    @staticmethod
    def get_by_vendor_model_for_billing(
        vendor_id: int,
        model_id: int,
        raw_input_token: int,
        time_period: str = 'normal',
    ) -> Optional[VendorModel]:
        """
        根据 raw_input_token + 计费时段 获取合适的计费配置（分段 + 峰谷计费）

        选择规则：
        1. 候选集：raw_token_threshold >= raw_input_token 的记录，或 raw_token_threshold 为 NULL 的兜底档
        2. 时段优先级（三级兜底，确保总能选到档，绝不漏扣）：
           a. 与传入 time_period 完全一致的档位（peak/off_peak 精确匹配）
           b. time_period='normal' 的档位（不分峰谷，向后兼容）
           c. 其余时段档位（最终兜底，避免配错时漏扣）
        3. 同一时段优先级内，raw_token_threshold 升序，有界档优先于无上限(NULL)档
        """
        period = time_period or 'normal'
        sql = f"""SELECT {_SELECT_COLS}
               FROM vendor_model
               WHERE vendor_id = %s AND model_id = %s
                 AND (raw_token_threshold >= %s OR raw_token_threshold IS NULL)
               ORDER BY
                 CASE time_period
                   WHEN %s THEN 0      /* 传入时段最优先 */
                   WHEN 'normal' THEN 1 /* normal 次之（向后兼容） */
                   ELSE 2               /* 其余时段兜底 */
                 END,
                 raw_token_threshold IS NULL,
                 raw_token_threshold ASC
               LIMIT 1"""
        try:
            row = execute_query(
                sql, (vendor_id, model_id, raw_input_token, period), fetch_one=True
            )
            return _row_to_vendor_model(row) if row else None
        except Exception as e:
            logger.error(
                f"Failed to get vendor model for billing "
                f"(vendor:{vendor_id}, model:{model_id}, raw_input:{raw_input_token}, "
                f"period:{period}): {e}"
            )
            raise

    @staticmethod
    def get_by_vendor_id(vendor_id: int) -> List[VendorModel]:
        """根据 vendor_id 获取所有供应商模型配置"""
        sql = f"""SELECT {_SELECT_COLS}
               FROM vendor_model WHERE vendor_id = %s ORDER BY created_at DESC"""
        try:
            rows = execute_query(sql, (vendor_id,), fetch_all=True)
            return [_row_to_vendor_model(row) for row in rows] if rows else []
        except Exception as e:
            logger.error(f"Failed to get vendor models by vendor_id {vendor_id}: {e}")
            raise

    @staticmethod
    def get_vendor_id_by_model_id(model_id: int) -> Optional[int]:
        """根据 model_id 获取 vendor_id（假设每个 model_id 只关联一个供应商）"""
        sql = "SELECT vendor_id FROM vendor_model WHERE model_id = %s LIMIT 1"
        try:
            row = execute_query(sql, (model_id,), fetch_one=True)
            return row['vendor_id'] if row else None
        except Exception as e:
            logger.error(f"Failed to get vendor_id for model {model_id}: {e}")
            return None

    @staticmethod
    def get_by_id(id: int) -> Optional[VendorModel]:
        """根据主键 id 获取供应商模型配置"""
        sql = f"""SELECT {_SELECT_COLS} FROM vendor_model WHERE id = %s"""
        try:
            row = execute_query(sql, (id,), fetch_one=True)
            return _row_to_vendor_model(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get vendor model by id {id}: {e}")
            raise

    @staticmethod
    def list_by_model_id(model_id: int) -> List[dict]:
        """
        按 model_id 列出所有计费档位（含供应商名称）。

        排序：vendor_id ASC, time_period ASC(normal/off_peak/peak),
             raw_token_threshold ASC（NULL 最后）
        """
        sql = """SELECT vm.id, vm.vendor_id, v.vendor_name, vm.model_id, vm.created_at,
               vm.input_token_threshold, vm.out_token_threshold, vm.cache_read_threshold,
               vm.raw_token_threshold, vm.commission_rate, vm.time_period
               FROM vendor_model vm
               LEFT JOIN vendor v ON v.id = vm.vendor_id
               WHERE vm.model_id = %s
               ORDER BY vm.vendor_id ASC,
                        vm.time_period ASC,
                        (vm.raw_token_threshold IS NULL) ASC,
                        vm.raw_token_threshold ASC"""
        try:
            rows = execute_query(sql, (model_id,), fetch_all=True)
            result = []
            for row in (rows or []):
                item = dict(row)
                item['commission_rate'] = _to_float_rate(item.get('commission_rate'))
                item['time_period'] = item.get('time_period') or 'normal'
                result.append(item)
            return result
        except Exception as e:
            logger.error(f"Failed to list vendor models by model_id {model_id}: {e}")
            raise

    @staticmethod
    def get_billing_summaries() -> dict:
        """批量统计每个 model 的供应商数与档位数。"""
        sql = """SELECT model_id,
                        COUNT(*) AS tier_count,
                        COUNT(DISTINCT vendor_id) AS vendor_count
                 FROM vendor_model
                 GROUP BY model_id"""
        try:
            rows = execute_query(sql, fetch_all=True)
            result = {}
            for row in (rows or []):
                result[row['model_id']] = {
                    'vendor_count': int(row['vendor_count'] or 0),
                    'tier_count': int(row['tier_count'] or 0),
                }
            return result
        except Exception as e:
            logger.error(f"Failed to get billing summaries: {e}")
            raise

    @staticmethod
    def list_vendors_by_models() -> dict:
        """
        批量查询每个 model 关联的供应商（去重）。

        Returns:
            { model_id: [ {vendor_id, vendor_name}, ... ] }
        """
        sql = """SELECT DISTINCT vm.model_id, vm.vendor_id, v.vendor_name
                 FROM vendor_model vm
                 LEFT JOIN vendor v ON v.id = vm.vendor_id
                 ORDER BY vm.model_id ASC, v.vendor_name ASC, vm.vendor_id ASC"""
        try:
            rows = execute_query(sql, fetch_all=True)
            result: dict = {}
            for row in (rows or []):
                mid = row['model_id']
                if mid not in result:
                    result[mid] = []
                result[mid].append({
                    'vendor_id': row['vendor_id'],
                    'vendor_name': row.get('vendor_name') or f"vendor#{row['vendor_id']}",
                })
            return result
        except Exception as e:
            logger.error(f"Failed to list vendors by models: {e}")
            raise

    @staticmethod
    def exists_tier(
        vendor_id: int,
        model_id: int,
        raw_token_threshold: Optional[int],
        exclude_id: Optional[int] = None,
        time_period: str = 'normal',
    ) -> bool:
        """检查同一 (vendor, model, raw_token_threshold, time_period) 下是否已存在档位。"""
        period = time_period or 'normal'
        if raw_token_threshold is None:
            sql = """SELECT id FROM vendor_model
                     WHERE vendor_id = %s AND model_id = %s
                       AND raw_token_threshold IS NULL
                       AND time_period = %s"""
            params: list = [vendor_id, model_id, period]
        else:
            sql = """SELECT id FROM vendor_model
                     WHERE vendor_id = %s AND model_id = %s
                       AND raw_token_threshold = %s
                       AND time_period = %s"""
            params = [vendor_id, model_id, raw_token_threshold, period]
        if exclude_id is not None:
            sql += " AND id <> %s"
            params.append(exclude_id)
        sql += " LIMIT 1"
        try:
            row = execute_query(sql, tuple(params), fetch_one=True)
            return row is not None
        except Exception as e:
            logger.error(
                f"Failed to check tier existence (vendor:{vendor_id}, model:{model_id}, "
                f"raw:{raw_token_threshold}, period:{period}): {e}"
            )
            raise

    @staticmethod
    def delete(id: int) -> bool:
        """删除供应商模型配置"""
        sql = "DELETE FROM vendor_model WHERE id = %s"
        try:
            rows = execute_update(sql, (id,))
            return rows > 0
        except Exception as e:
            logger.error(f"Failed to delete vendor model: {e}")
            raise

    @staticmethod
    def delete_by_vendor_and_model(vendor_id: int, model_id: int) -> int:
        """删除指定供应商-模型下全部计费档位，返回删除行数。"""
        sql = "DELETE FROM vendor_model WHERE vendor_id = %s AND model_id = %s"
        try:
            return int(execute_update(sql, (vendor_id, model_id)) or 0)
        except Exception as e:
            logger.error(
                f"Failed to delete vendor_model by vendor={vendor_id} model={model_id}: {e}"
            )
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `vendor_model` (
  `id` int NOT NULL AUTO_INCREMENT,
  `vendor_id` int DEFAULT NULL COMMENT '供应商id',
  `model_id` int DEFAULT NULL COMMENT '模型id',
  `created_at` datetime DEFAULT NULL,
  `input_token_threshold` int DEFAULT NULL COMMENT '输入token计费率：多少个input_token消耗1点算力', -- 1算力=0.04元
  `out_token_threshold` int DEFAULT NULL COMMENT '输出token计费率：多少个output_token消耗1点算力', -- 1算力=0.04元
  `cache_read_threshold` int DEFAULT NULL COMMENT '缓存读取计费率：多少个cache_read消耗1点算力', -- 1算力=0.04元
  `raw_token_threshold` int DEFAULT NULL COMMENT '分段边界：当raw_input_token<=此值时使用本档计费率，NULL表示无上限',
  `commission_rate` decimal(5,4) NOT NULL DEFAULT 0 COMMENT '抽成比例 0~1，计费时算力乘以 (1+commission_rate)',
  `time_period` ENUM('normal','peak','off_peak') NOT NULL DEFAULT 'normal' COMMENT '计费时段：normal=不分峰谷, peak=高峰, off_peak=空闲',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `vendor_id_model_id` (`vendor_id`,`model_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;
"""
