"""
管理员 API 路由
"""
from fastapi import APIRouter, HTTPException, Header, Query, Path
from pydantic import BaseModel
from typing import Optional, List, Union
import logging
import httpx

from model.users import UsersModel, User
from model.user_tokens import UserTokensModel
from model.computing_power import ComputingPowerModel
from model.video_workflow import VideoWorkflowModel
from model.system_config import SystemConfigModel
from model.system_config_history import SystemConfigHistoryModel
from config.config_util import get_current_env, invalidate_dynamic_cache
from config.default_configs import init_default_configs, get_default_config_by_key
from config.constant import GEMINI_URL_FORMATS, DRIVER_IMPLEMENTATION_MAPPING

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def require_admin(auth_token: str = Header(None, alias="Authorization")) -> User:
    """
    管理员权限校验中间件
    从 Authorization header 中获取 token，验证用户是否为管理员
    """
    if not auth_token:
        raise HTTPException(status_code=401, detail="需要登录")
    
    # 移除 "Bearer " 前缀
    if auth_token.startswith("Bearer "):
        auth_token = auth_token[7:]
    
    # 验证 token 并获取用户ID
    user_id = UserTokensModel.get_user_id_by_token(auth_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效或已过期的认证信息")
    
    # 获取用户信息
    user = UsersModel.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    
    # 检查管理员权限
    if user.role != 'admin':
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    return user


@router.get("/dashboard")
async def admin_dashboard(auth_token: str = Header(None, alias="Authorization")):
    """
    管理员仪表盘数据
    返回用户总数、最近3天活跃工作流数量
    """
    admin = await require_admin(auth_token)
    
    try:
        total_users = UsersModel.get_total_count()
        active_workflows_3d = VideoWorkflowModel.count_active_recent_days(days=3)
        
        return {
            "code": 0,
            "data": {
                "total_users": total_users,
                "active_workflows_3d": active_workflows_3d
            }
        }
    except Exception as e:
        logger.error(f"Failed to get admin dashboard data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users")
async def admin_list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None),
    status: Optional[int] = Query(None),
    role: Optional[str] = Query(None),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    管理员获取用户列表
    """
    admin = await require_admin(auth_token)
    
    try:
        result = UsersModel.list_all(
            page=page,
            page_size=page_size,
            keyword=keyword,
            status=status,
            role=role
        )
        
        # 为每个用户添加算力信息
        for user in result['data']:
            power = ComputingPowerModel.get_by_user_id(user['user_id'])
            user['computing_power'] = power.computing_power if power else 0
        
        return {
            "code": 0,
            "data": result
        }
    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}")
async def admin_get_user(
    user_id: int = Path(...),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    管理员获取用户详情
    """
    admin = await require_admin(auth_token)
    
    try:
        user = UsersModel.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        user_dict = user.to_dict()
        
        # 添加算力信息
        power = ComputingPowerModel.get_by_user_id(user_id)
        user_dict['computing_power'] = power.computing_power if power else 0
        
        return {
            "code": 0,
            "data": user_dict
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class UpdateUserStatusRequest(BaseModel):
    status: int


@router.put("/users/{user_id}/status")
async def admin_update_user_status(
    user_id: int = Path(...),
    request: UpdateUserStatusRequest = None,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    管理员更新用户状态（0-禁用, 1-正常）
    禁用用户时会自动删除其所有 token，强制登出
    """
    admin = await require_admin(auth_token)
    
    # 禁止管理员禁用自己
    if user_id == admin.id and request.status == 0:
        raise HTTPException(status_code=400, detail="不能禁用自己")
    
    try:
        user = UsersModel.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 更新用户状态
        UsersModel.update_status(user_id, request.status)
        
        # 如果是禁用操作，删除该用户的所有 token（强制登出）
        if request.status == 0:
            try:
                UserTokensModel.delete_by_user_id(user_id)
                logger.info(f"Deleted all tokens for disabled user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete tokens for user {user_id}: {e}")
                # 不影响主流程，继续执行
        
        return {
            "code": 0,
            "message": "状态更新成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update user {user_id} status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class UpdateUserRoleRequest(BaseModel):
    role: str


@router.put("/users/{user_id}/role")
async def admin_update_user_role(
    user_id: int = Path(...),
    request: UpdateUserRoleRequest = None,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    管理员更新用户角色（user/admin）
    """
    admin = await require_admin(auth_token)
    
    # 禁止管理员降级自己
    if user_id == admin.id and request.role != 'admin':
        raise HTTPException(status_code=400, detail="不能降级自己的权限")
    
    if request.role not in ('user', 'admin'):
        raise HTTPException(status_code=400, detail="无效的角色")
    
    try:
        user = UsersModel.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        UsersModel.update_role(user_id, request.role)
        
        return {
            "code": 0,
            "message": "角色更新成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update user {user_id} role: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class AdjustPowerRequest(BaseModel):
    amount: int
    reason: str


@router.post("/users/{user_id}/power")
async def admin_adjust_user_power(
    user_id: int = Path(...),
    request: AdjustPowerRequest = None,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    管理员调整用户算力
    amount: 正数增加，负数扣减
    """
    admin = await require_admin(auth_token)
    
    if not request.reason or not request.reason.strip():
        raise HTTPException(status_code=400, detail="请填写调整原因")
    
    try:
        user = UsersModel.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        old_power, new_power = ComputingPowerModel.admin_adjust(
            user_id=user_id,
            amount=request.amount,
            reason=f"管理员({admin.phone})调整: {request.reason}"
        )
        
        return {
            "code": 0,
            "message": "算力调整成功",
            "data": {
                "old_power": old_power,
                "new_power": new_power
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to adjust user {user_id} power: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 系统配置管理 API ====================


@router.get("/config")
async def admin_list_configs(
    keyword: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取系统配置列表
    """
    admin = await require_admin(auth_token)
    env = get_current_env()
    
    try:
        result = SystemConfigModel.search(
            env=env,
            keyword=keyword,
            page=page,
            page_size=page_size
        )
        
        # 敏感配置在列表中脱敏显示
        for config in result['data']:
            if config['is_sensitive']:
                config['config_value'] = SystemConfigModel.mask_sensitive_value(
                    str(config['config_value']) if config['config_value'] else ''
                )
        
        return {
            "code": 0,
            "data": result
        }
    except Exception as e:
        logger.error(f"Failed to list configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/raw")
async def admin_get_config_raw_value(
    key: str = Query(..., description="配置键"),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取配置的完整值（不脱敏），用于查看敏感配置
    """
    admin = await require_admin(auth_token)
    env = get_current_env()
    
    try:
        config = SystemConfigModel.get_by_key(env, key)
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        return {
            "code": 0,
            "data": {
                "config_key": config.config_key,
                "config_value": config.config_value
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get raw config {key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/quick-configs")
async def admin_get_quick_configs(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取快速配置项列表
    返回需要在快速配置弹窗中显示的配置项
    """
    await require_admin(auth_token)
    
    from config.default_configs import get_quick_configs
    configs = get_quick_configs()
    
    return {
        "code": 0,
        "message": "获取成功",
        "data": {
            "configs": configs
        }
    }


@router.get("/config/{config_key:path}")
async def admin_get_config(
    config_key: str = Path(...),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取单个配置详情（包含修改历史）
    """
    admin = await require_admin(auth_token)
    env = get_current_env()
    
    try:
        config = SystemConfigModel.get_by_key(env, config_key)
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        config_dict = config.to_dict()
        
        # 敏感配置脱敏显示
        if config.is_sensitive:
            config_dict['config_value'] = config.get_display_value()
        
        # 获取修改历史
        histories = SystemConfigHistoryModel.get_by_key(env, config_key, limit=10)
        config_dict['history'] = [h.to_dict() for h in histories]
        
        return {
            "code": 0,
            "data": config_dict
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get config {config_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class BatchConfigItem(BaseModel):
    key: str
    value: str


class BatchConfigRequest(BaseModel):
    configs: List[BatchConfigItem]


@router.put("/config/batch")
async def admin_batch_update_configs(
    request: BatchConfigRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    批量更新配置值
    用于快速配置功能，一次性更新多个配置项
    """
    admin = await require_admin(auth_token)
    env = get_current_env()
    
    if not request.configs:
        raise HTTPException(status_code=400, detail="配置列表不能为空")
    
    results = []
    errors = []
    
    for item in request.configs:
        try:
            config = SystemConfigModel.get_by_key(env, item.key)

            # 如果配置不存在，尝试从默认配置中获取定义并创建
            if not config:
                config_def = get_default_config_by_key(item.key)
                if not config_def:
                    errors.append(f"{item.key}: 配置不存在且无默认定义")
                    continue

                # 创建新配置
                config_id = SystemConfigModel.create(
                    env=env,
                    config_key=item.key,
                    config_value=item.value,
                    value_type=config_def['value_type'],
                    description=config_def['description'],
                    editable=1 if config_def['editable'] else 0,
                    is_sensitive=1 if config_def['is_sensitive'] else 0,
                    updated_by=admin.id
                )
                results.append({
                    "key": item.key,
                    "status": "created"
                })
                logger.info(f"Auto-created config {item.key} with id {config_id}")
                continue

            if not config.editable:
                errors.append(f"{item.key}: 该配置不允许修改")
                continue

            old_value = config.config_value
            new_value = item.value

            # 跳过未修改的配置
            if old_value == new_value:
                results.append({
                    "key": item.key,
                    "status": "unchanged"
                })
                continue

            # 更新配置
            SystemConfigModel.update_value(config.id, new_value, admin.id)

            results.append({
                "key": item.key,
                "status": "updated"
            })
        except Exception as e:
            logger.error(f"Failed to update config {item.key}: {e}")
            errors.append(f"{item.key}: {str(e)}")
    
    updated_count = len([r for r in results if r['status'] == 'updated'])
    created_count = len([r for r in results if r['status'] == 'created'])

    return {
        "code": 0,
        "message": f"批量更新完成，新建 {created_count} 条，更新 {updated_count} 条配置",
        "data": {
            "results": results,
            "errors": errors
        }
    }


class UpdateConfigRequest(BaseModel):
    value: Union[str, int, float, bool]
    value_type: Optional[str] = None


@router.put("/config/{config_key:path}")
async def admin_update_config(
    config_key: str = Path(...),
    request: UpdateConfigRequest = None,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    更新配置值
    """
    admin = await require_admin(auth_token)
    env = get_current_env()
    
    try:
        config = SystemConfigModel.get_by_key(env, config_key)
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        # 检查是否可编辑
        if not config.editable:
            raise HTTPException(status_code=403, detail="该配置不允许修改")
        
        old_value = config.config_value
        # 将值转换为字符串存储
        new_value = str(request.value) if request.value is not None else ''
        value_type = request.value_type or config.value_type
        
        # 更新配置
        SystemConfigModel.update_value(config.id, new_value, admin.id)
        
        # 记录修改历史
        if old_value != new_value:
            SystemConfigHistoryModel.create(
                config_id=config.id,
                env=env,
                config_key=config_key,
                old_value=old_value,
                new_value=new_value,
                value_type=value_type,
                is_sensitive=config.is_sensitive,
                updated_by=admin.id
            )
        
        # 清除缓存
        invalidate_dynamic_cache(config_key)
        
        return {
            "code": 0,
            "message": "配置更新成功",
            "data": {
                "old_value": SystemConfigModel.mask_sensitive_value(old_value) if config.is_sensitive else old_value,
                "new_value": SystemConfigModel.mask_sensitive_value(new_value) if config.is_sensitive else new_value
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update config {config_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/reload")
async def admin_reload_configs(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    重新加载所有配置（清除缓存）
    """
    admin = await require_admin(auth_token)
    
    try:
        invalidate_dynamic_cache()
        
        return {
            "code": 0,
            "message": "配置缓存已清除"
        }
    except Exception as e:
        logger.error(f"Failed to reload configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/init")
async def admin_init_configs(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    初始化默认配置（从 YAML 导入到数据库）
    仅插入数据库中不存在的配置
    """
    admin = await require_admin(auth_token)
    env = get_current_env()
    
    try:
        inserted_count = init_default_configs(env, admin.id)
        
        return {
            "code": 0,
            "message": f"初始化完成，新增 {inserted_count} 条配置",
            "data": {
                "inserted_count": inserted_count,
                "env": env
            }
        }
    except Exception as e:
        logger.error(f"Failed to init configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config-history")
async def admin_list_config_history(
    config_key: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取配置修改历史列表
    """
    admin = await require_admin(auth_token)
    env = get_current_env()
    
    try:
        result = SystemConfigHistoryModel.search(
            env=env,
            config_key=config_key,
            page=page,
            page_size=page_size
        )
        
        return {
            "code": 0,
            "data": result
        }
    except Exception as e:
        logger.error(f"Failed to list config history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class TestGoogleRequest(BaseModel):
    api_key: str
    base_url: Optional[str] = None


@router.post("/config/test-google")
async def admin_test_google_connection(
    request: TestGoogleRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    测试 Google/Gemini API 连接
    通过发送一个简单的请求验证 API Key 有效性
    支持两种 URL 格式自动尝试（第三方代理格式和 Google 官方格式）
    """
    admin = await require_admin(auth_token)
    
    if not request.api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")
    
    # 构建请求 URL
    base_url = request.base_url or "https://api.jiekou.ai"
    base_url = base_url.rstrip("/")
    
    # 移除 /openai 后缀（如果有）
    if base_url.endswith('/openai'):
        base_url = base_url[:-7]
    
    # 测试模型
    test_model = "gemini-3-flash-preview"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {request.api_key}"
    }
    
    # 构建最简单的测试请求
    test_payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Hi"}]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 10,
            "temperature": 0.1
        }
    }
    
    # 记录最后一次错误信息
    last_error = None
    last_error_message = None
    
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # 依次尝试两种 URL 格式
            for fmt_name, fmt_path in GEMINI_URL_FORMATS.items():
                url = f"{base_url}{fmt_path.format(model=test_model)}"
                
                try:
                    response = await client.post(url, headers=headers, json=test_payload)
                    
                    if response.status_code == 200:
                        # 验证响应体有效性
                        try:
                            resp_json = response.json()
                            # 检查是否有有效的 candidates 响应
                            if "candidates" in resp_json and resp_json["candidates"]:
                                return {
                                    "code": 0,
                                    "message": f"连接成功（格式: {fmt_name}）",
                                    "data": {
                                        "success": True,
                                        "model": test_model,
                                        "format": fmt_name
                                    }
                                }
                            else:
                                # 200 但无 candidates，可能是错误信息
                                error_info = resp_json.get("error", {})
                                error_msg = error_info.get("message", "响应无效")
                                last_error = f"{fmt_name}: {error_msg}"
                                last_error_message = f"API 返回错误: {error_msg}"
                                continue  # 尝试下一种格式
                        except Exception:
                            last_error = f"{fmt_name}: 响应解析失败"
                            continue
                    
                    elif response.status_code in [401, 403]:
                        # 认证错误，说明格式对了但 key 错了
                        error_type = "无效或未授权" if response.status_code == 401 else "权限不足或已被禁用"
                        return {
                            "code": 1,
                            "message": f"API Key {error_type}（格式: {fmt_name}）",
                            "data": {"success": False, "error": f"HTTP {response.status_code}", "format": fmt_name}
                        }
                    
                    # 404 或其他错误，继续尝试下一种格式
                    last_error = f"{fmt_name}: HTTP {response.status_code}"
                    
                except httpx.TimeoutException:
                    last_error = f"{fmt_name}: 连接超时"
                    continue
                except Exception as e:
                    last_error = f"{fmt_name}: {str(e)}"
                    continue
            
            # 所有格式都失败
            return {
                "code": 1,
                "message": last_error_message or f"连接失败: {last_error}",
                "data": {"success": False, "error": last_error}
            }
                
    except httpx.TimeoutException:
        return {
            "code": 1,
            "message": "连接超时，请检查网络或 Base URL",
            "data": {"success": False, "error": "Timeout"}
        }
    except Exception as e:
        logger.error(f"Failed to test Google connection: {e}")
        return {
            "code": 1,
            "message": f"连接失败: {str(e)}",
            "data": {"success": False, "error": str(e)}
        }


# ==================== 实现方算力配置 API ====================

from model.implementation_power import ImplementationPowerModel
from config.unified_config import UnifiedConfigRegistry


@router.get("/implementation-powers")
async def admin_get_implementation_powers(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取所有实现方的算力配置
    返回实现方列表及其算力配置（包含数据库配置和代码默认值）
    """
    await require_admin(auth_token)

    try:
        # 获取所有实现方配置
        all_implementations = UnifiedConfigRegistry.get_all_implementations()

        # 获取数据库中的算力配置
        db_powers = ImplementationPowerModel.get_all_powers()

        # 合并数据
        result = []
        for impl_name, impl_config in all_implementations.items():
            # 查找该实现方的数据库配置
            db_config = [p for p in db_powers if p['implementation_name'] == impl_name]

            # 构建返回数据
            impl_data = {
                'name': impl_name,
                'display_name': impl_config.display_name,
                'driver_class': impl_config.driver_class,
                'default_computing_power': impl_config.default_computing_power,
                'enabled': impl_config.enabled,
                'description': impl_config.description,
                'db_config': db_config,
                'source': 'database' if db_config else 'code_default'
            }
            result.append(impl_data)

        return {
            "code": 0,
            "data": result
        }
    except Exception as e:
        logger.error(f"Failed to get implementation powers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SetImplementationPowerRequest(BaseModel):
    implementation_name: str
    driver_key: str  # 必填，用于复合唯一键定位记录
    computing_power: int
    duration: Optional[int] = None  # None表示固定算力，否则为特定时长的算力


@router.post("/implementation-power")
async def admin_set_implementation_power(
    request: SetImplementationPowerRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    设置实现方算力（管理员操作，立即生效，无需重启）

    Args:
        implementation_name: 实现方名称（如 gemini_duomi_v1）
        computing_power: 算力值
        duration: 时长（秒），不传表示固定算力
    """
    admin = await require_admin(auth_token)

    # 验证实现方存在
    impl_config = UnifiedConfigRegistry.get_implementation(request.implementation_name)
    if not impl_config:
        raise HTTPException(status_code=404, detail=f"实现方不存在: {request.implementation_name}")

    if request.computing_power < 0:
        raise HTTPException(status_code=400, detail="算力值不能为负数")

    try:
        ImplementationPowerModel.set_power(
            implementation_name=request.implementation_name,
            driver_key=request.driver_key,
            computing_power=request.computing_power,
            duration=request.duration,
            updated_by=admin.id
        )

        return {
            "code": 0,
            "message": f"算力配置已更新，立即生效",
            "data": {
                "implementation_name": request.implementation_name,
                "computing_power": request.computing_power,
                "duration": request.duration
            }
        }
    except Exception as e:
        logger.error(f"Failed to set implementation power: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class DeleteImplementationPowerRequest(BaseModel):
    implementation_name: str
    driver_key: str  # 必填，用于复合唯一键定位记录
    duration: Optional[int] = None


@router.delete("/implementation-power")
async def admin_delete_implementation_power(
    request: DeleteImplementationPowerRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    删除实现方算力配置（回退到代码默认值）

    Args:
        implementation_name: 实现方名称
        duration: 时长（秒），不传表示删除固定算力配置
    """
    await require_admin(auth_token)

    try:
        affected = ImplementationPowerModel.delete_power(
            implementation_name=request.implementation_name,
            driver_key=request.driver_key,
            duration=request.duration
        )

        if affected > 0:
            return {
                "code": 0,
                "message": "算力配置已删除，将使用代码默认值"
            }
        else:
            return {
                "code": 0,
                "message": "未找到对应的算力配置"
            }
    except Exception as e:
        logger.error(f"Failed to delete implementation power: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 实现方配置（启用/禁用）API ====================

class SetImplementationConfigRequest(BaseModel):
    implementation_name: str
    driver_key: str  # 必填，用于复合唯一键定位记录
    enabled: Optional[bool] = None
    sort_order: Optional[int] = None


@router.put("/implementation-config")
async def admin_set_implementation_config(
    request: SetImplementationConfigRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    设置实现方配置（启用/禁用、排序顺序等）

    管理员操作，立即生效，无需重启服务
    操作会记录审计日志

    注意：显示名称由系统自动管理，不支持手动设置。
    API聚合站点的显示名称从 api_aggregator.site_X.name 配置读取。

    Args:
        implementation_name: 实现方名称（如 gemini_duomi_v1）
        driver_key: DriverKey（必填）
        enabled: 是否启用（True/False）
        sort_order: 排序顺序（可选）
    """
    admin = await require_admin(auth_token)

    # 验证实现方存在
    impl_config = UnifiedConfigRegistry.get_implementation(request.implementation_name)
    if not impl_config:
        raise HTTPException(status_code=404, detail=f"实现方不存在: {request.implementation_name}")

    try:
        success = ImplementationPowerModel.set_config(
            implementation_name=request.implementation_name,
            driver_key=request.driver_key,
            enabled=request.enabled,
            sort_order=request.sort_order,
            updated_by=admin.id
        )

        if success:
            return {
                "code": 0,
                "message": "配置已更新，立即生效",
                "data": {
                    "implementation_name": request.implementation_name,
                    "driver_key": request.driver_key,
                    "enabled": request.enabled,
                    "sort_order": request.sort_order
                }
            }
        else:
            return {
                "code": 1,
                "message": "配置未变更（可能是相同的值）"
            }
    except Exception as e:
        logger.error(f"Failed to set implementation config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/implementation-configs")
async def admin_get_implementation_configs(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取所有实现方配置（包含启用状态），按模型任务（DriverKey）分组返回

    返回所有实现方，包括动态注册的 API 聚合器实现方
    """
    await require_admin(auth_token)

    try:
        # 构建反向映射：实现方 -> DriverKey 列表
        impl_to_driver_keys = {}
        for driver_key, impl_names in DRIVER_IMPLEMENTATION_MAPPING.items():
            # 支持单个实现方（字符串）和多个实现方（列表）
            if isinstance(impl_names, str):
                impl_names = [impl_names]
            
            for impl_name in impl_names:
                if impl_name not in impl_to_driver_keys:
                    impl_to_driver_keys[impl_name] = []
                impl_to_driver_keys[impl_name].append(driver_key)

        # 获取所有实现方（包括动态注册的 API 聚合器实现方）
        all_implementations = UnifiedConfigRegistry.get_all_implementations()

        # 获取数据库中的配置
        db_configs = ImplementationPowerModel.get_all_configs()
        # 使用 (implementation_name, driver_key) 作为复合键
        db_config_map = {(c['implementation_name'], c.get('driver_key')): c for c in db_configs}

        # 获取所有任务配置，提取实现方支持的时长
        impl_durations = {}
        for task_config in UnifiedConfigRegistry.get_all():
            # 兼容单数和复数形式的 implementation 属性
            impl_names = []
            if hasattr(task_config, 'implementations') and task_config.implementations:
                impl_names = task_config.implementations if isinstance(task_config.implementations, list) else [task_config.implementations]
            elif hasattr(task_config, 'implementation') and task_config.implementation:
                impl_names = [task_config.implementation] if not isinstance(task_config.implementation, list) else task_config.implementation

            for impl_name in impl_names:
                if impl_name not in impl_durations:
                    impl_durations[impl_name] = set()
                if hasattr(task_config, 'supported_durations'):
                    impl_durations[impl_name].update(task_config.supported_durations)

        # 按 DriverKey 分组
        driver_key_groups = {}

        # 处理所有实现方（包括动态注册的 API 聚合器实现方）
        for impl_name, impl_config in all_implementations.items():
            print(f"Processing implementation: {impl_name}")
            # 只对 API 聚合器实现方进行配置检查
            display_name = impl_config.display_name
            site_name = None

            print(f"Checking if {impl_name} is an API aggregator...")
            if impl_name.startswith('gemini_image_preview_site') and impl_name.endswith('_v1'):
                # 检查API聚合器配置是否存在
                try:
                    from utils.config_checker import check_api_aggregator_config_exists
                    from config.config_util import get_dynamic_config_value
                    # 提取站点ID，如 gemini_image_preview_site1_v1 -> site_1
                    site_num = impl_name.replace('gemini_image_preview_site', '').replace('_v1', '')
                    site_id = f"site_{site_num}"
                    
                    if not check_api_aggregator_config_exists(site_id):
                        print(f"API聚合站实现方 {impl_name} 配置不存在，跳过显示")
                        logger.info(f"API聚合站实现方 {impl_name} 配置不存在，跳过显示")
                        continue
                    
                    # 获取站点配置的名称
                    site_name = get_dynamic_config_value("api_aggregator", site_id, "name", default=site_id)
                    print(f"API聚合站实现方 {impl_name} 的站点名称: {site_name}")
                    display_name = site_name
                    
                except ImportError:
                    logger.warning("无法导入配置检查工具，显示所有API聚合站实现方")
            
            print(f"Final display name for {impl_name}: {display_name}")
                
            # 确定该实现方属于哪些 DriverKey 组
            driver_keys = impl_to_driver_keys.get(impl_name, [])

            # 对于 API 聚合器实现方，创建特殊的分组
            if not driver_keys and impl_name.startswith('gemini_common_'):
                driver_keys = ["API_AGGREGATOR_GEMINI"]

            # 为每个 driver_key 获取对应的数据库配置
            for driver_key in driver_keys:
                # 使用复合键 (implementation_name, driver_key) 获取配置
                db_config = db_config_map.get((impl_name, driver_key), {})

                # 获取该实现方支持的时长列表
                supported_durations = sorted(list(impl_durations.get(impl_name, [])))

                # 获取该实现方的算力配置（按时长分组）
                power_configs = ImplementationPowerModel.get_all_powers_for_implementation(impl_name, driver_key)

                # 构建时长-算力映射
                duration_powers = []
                for duration in supported_durations:
                    power = power_configs.get(duration)

                    # 如果数据库没有配置，尝试从代码默认值获取
                    if power is None:
                        default_power = impl_config.default_computing_power
                        if isinstance(default_power, dict) and duration in default_power:
                            power = default_power[duration]
                        elif isinstance(default_power, dict) and default_power:
                            # 如果是字典但没有对应时长，使用第一个值
                            power = list(default_power.values())[0]
                        else:
                            power = default_power

                    duration_powers.append({
                        'duration': duration,
                        'computing_power': power
                    })

                impl_data = {
                    'name': impl_name,
                    'display_name': display_name if impl_config.site_number is not None else (db_config.get('display_name') if db_config else None) or display_name,  # 聚合站点始终使用系统配置名称，其他实现方优先使用数据库值
                    'enabled': db_config.get('enabled') if db_config and db_config.get('enabled') is not None else impl_config.enabled,
                    'sort_order': db_config.get('sort_order') if db_config else impl_config.sort_order,  # 优先使用数据库排序，否则使用配置文件默认值
                    'driver_key': db_config.get('driver_key') if db_config else impl_config.driver_class,  # 使用 driver_key 字段
                    'default_computing_power': impl_config.default_computing_power,
                    'description': impl_config.description,
                    'driver_class': impl_config.driver_class,
                    'supported_durations': supported_durations,
                    'duration_powers': duration_powers,
                }

                # 调试日志：输出实现方数据
                logger.debug(f"Implementation data: {impl_name}, driver_key={driver_key}, enabled={impl_data['enabled']}, db_config={db_config}")

                # 为没有时长配置的实现方添加当前默认算力值
                if not duration_powers:
                    # 获取固定算力配置（duration = None）
                    fixed_power = power_configs.get(None)
                    if fixed_power is not None:
                        impl_data['current_default_power'] = fixed_power
                    else:
                        # 使用代码默认值
                        default_power = impl_config.default_computing_power
                        if isinstance(default_power, dict) and default_power:
                            impl_data['current_default_power'] = list(default_power.values())[0]
                        else:
                            impl_data['current_default_power'] = default_power or 0
                else:
                    # 为有时长配置的实现方添加每个时长的默认值
                    impl_data['default_duration_powers'] = {}
                    for duration in supported_durations:
                        default_power = impl_config.default_computing_power
                        if isinstance(default_power, dict) and duration in default_power:
                            impl_data['default_duration_powers'][duration] = default_power[duration]
                        elif isinstance(default_power, dict) and default_power:
                            impl_data['default_duration_powers'][duration] = list(default_power.values())[0]
                        else:
                            impl_data['default_duration_powers'][duration] = default_power or 0

                # 将实现方添加到对应的 DriverKey 组
                if driver_key not in driver_key_groups:
                    driver_key_groups[driver_key] = []
                driver_key_groups[driver_key].append(impl_data)

        # 对每组内的实现方按 sort_order 排序
        for driver_key in driver_key_groups:
            driver_key_groups[driver_key].sort(key=lambda x: (x['sort_order'] or 0, x['name']))

        # 转换为列表格式，按 DriverKey 排序
        result = [
            {
                'driver_key': driver_key,
                'implementations': impls
            }
            for driver_key, impls in sorted(driver_key_groups.items())
        ]

        return {
            "code": 0,
            "data": result
        }
    except Exception as e:
        logger.error(f"Failed to get implementation configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class UpdateSortOrderRequest(BaseModel):
    updates: List[dict]  # [{'implementation_name': str, 'driver_key': str, 'sort_order': int}]


@router.post("/implementation-configs/sort-order")
async def admin_update_sort_orders(
    request: UpdateSortOrderRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    批量更新实现方的排序顺序

    用于拖拽排序后保存新的顺序
    """
    admin = await require_admin(auth_token)

    if not request.updates:
        raise HTTPException(status_code=400, detail="更新列表不能为空")

    try:
        success_count = 0
        for update in request.updates:
            impl_name = update.get('implementation_name')
            driver_key = update.get('driver_key')
            sort_order = update.get('sort_order')

            if impl_name is None or driver_key is None or sort_order is None:
                logger.warning(f"Invalid update parameters: {update}")
                continue

            # 使用复合键 (implementation_name, driver_key) 查询和更新配置
            existing_config = ImplementationPowerModel.get_config(impl_name, driver_key)

            ImplementationPowerModel.set_config(
                implementation_name=impl_name,
                driver_key=driver_key,
                sort_order=sort_order,
                updated_by=admin.id
            )
            success_count += 1
            logger.info(f"Updated sort order for {impl_name} (driver_key: {driver_key}) to {sort_order}")

        return {
            "code": 0,
            "message": f"成功更新 {success_count} 个实现方的排序",
            "data": {"updated_count": success_count}
        }
    except Exception as e:
        logger.error(f"Failed to update sort orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))
