"""
工作流编辑器测试辅助函数。
提供节点创建、交互等通用操作。
所有节点操作通过 JS 直接调用全局函数，避免 placing 机制导致的 visibility 问题。
"""
import logging

logger = logging.getLogger(__name__)


def navigate_to_editor(page, base_url, workflow_id, auth_token=None, user_id=None):
    """导航到工作流编辑器并等待加载完成。

    通过 page.route() 拦截 /api/user/computing_power 请求，返回成功响应，
    防止 workflow.js 的 fetchComputingPower() 因认证失败而重定向到登录页。
    """
    import json as _json

    def handle_computing_power(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_json.dumps({
                "success": True,
                "data": {"computing_power": 9999}
            }),
        )

    page.route("**/api/user/computing_power", handle_computing_power)

    url = f"{base_url}/video-workflow?id={workflow_id}"
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    page.locator("#addBtn").wait_for(state="attached", timeout=15000)


def create_node_via_js(page, node_type: str, data: dict = None, x: int = 200, y: int = 200):
    """通过 JS 全局函数创建节点，绕过 placing 机制。

    Args:
        page: Playwright page
        node_type: 节点类型 ("image", "script", "video", "shot_group", "camera_control" 等)
        data: 节点初始数据
        x, y: 节点位置
    Returns:
        节点 ID
    """
    func_name = f"create{node_type.replace('_', ' ').title().replace(' ', '')}NodeWithData"
    # 尝试带 Data 后缀的函数
    result = page.evaluate(f"""(x, y, data) => {{
        if (typeof {func_name} === 'function') {{
            return {func_name}({{ x, y, ...data, checkCollision: false }});
        }}
        // 回退：尝试不带 Data 的函数
        const funcName2 = '{func_name}'.replace('WithData', '');
        if (typeof window[funcName2] === 'function') {{
            return window[funcName2]({{ x, y, checkCollision: false }});
        }}
        return null;
    }}""", x, y, data or {})
    page.wait_for_timeout(500)
    return result


def make_all_nodes_visible(page):
    """强制使所有节点可见（绕过 placing 机制）。"""
    page.evaluate("""() => {
        document.querySelectorAll('.node').forEach(n => {
            if (n.style.visibility === 'hidden') n.style.visibility = '';
        });
        const container = document.querySelector('.canvas-container');
        if (container) container.classList.remove('placing');
    }""")
    page.wait_for_timeout(200)


def add_node(page, menu_id: str, timeout=1000):
    """点击添加按钮并选择菜单项，返回新创建的节点 locator。"""
    page.evaluate("() => document.getElementById('addMenu').classList.add('show')")
    page.wait_for_timeout(300)
    page.locator(f"#{menu_id}").click(force=True)
    page.wait_for_timeout(timeout)
    page.evaluate("() => document.getElementById('addMenu').classList.remove('show')")
    page.wait_for_timeout(500)

    # 模拟鼠标移动触发放置
    canvas = page.locator("#canvas")
    if canvas.count() > 0:
        box = canvas.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] * 0.4, box["y"] + box["height"] * 0.4)
            page.wait_for_timeout(300)

    make_all_nodes_visible(page)
    return page.locator(".node.selected").first


def get_selected_node(page):
    """获取当前选中的节点"""
    return page.locator(".node.selected").first


def add_script_node(page, text: str = "", timeout=1000):
    """创建剧本节点并输入文本"""
    node = add_node(page, "menuAddScript", timeout)
    if text:
        # 等待事件监听器 attached
        page.wait_for_timeout(1500)

        # 聚焦 textarea 并使用键盘输入（确保触发 input 事件监听器）
        textarea = node.locator(".script-textarea")
        textarea.wait_for(state="attached", timeout=5000)
        textarea.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        textarea.click(force=True)
        page.wait_for_timeout(200)
        textarea.type(text, delay=10)
        page.wait_for_timeout(500)

        # 确保分割按钮被启用
        page.evaluate("""() => {
            const nodeEl = document.querySelector('.node.selected');
            if (!nodeEl) return;
            const splitBtn = nodeEl.querySelector('.script-split-btn');
            if (splitBtn) splitBtn.disabled = false;
            const gridBtn = nodeEl.querySelector('.script-split-grid-btn');
            if (gridBtn) gridBtn.disabled = false;
        }""")
        page.wait_for_timeout(200)
    return node


def add_image_node(page, timeout=1000):
    """创建图片节点"""
    return add_node(page, "menuAddImage", timeout)


def add_image_to_video_node(page, timeout=1000):
    """创建图生视频节点"""
    return add_node(page, "menuAddVideo", timeout)


def add_shot_group_node(page, timeout=1000):
    """创建分镜组节点"""
    return add_node(page, "menuAddShotGroup", timeout)


def js_click(page, selector: str):
    """通过 JS 点击元素，绕过 Playwright 的 actionability 检查。"""
    page.evaluate("""([sel]) => {
        const el = document.querySelector(sel);
        if (el) el.click();
    }""", [selector])


def js_click_in_node(page, node_selector: str, child_selector: str):
    """通过 JS 点击节点内的子元素。"""
    page.evaluate("""([nodeSel, childSel]) => {
        const node = document.querySelector(nodeSel);
        if (node) {
            const el = node.querySelector(childSel);
            if (el) el.click();
        }
    }""", [node_selector, child_selector])


def js_fill_in_node(page, node_selector: str, child_selector: str, value: str):
    """通过 JS 填写节点内的表单元素。"""
    page.evaluate("""([nodeSel, childSel, val]) => {
        const node = document.querySelector(nodeSel);
        if (node) {
            const el = node.querySelector(childSel);
            if (el) {
                el.value = val;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }
    }""", [node_selector, child_selector, value])


def click_split_button(page, node=None):
    """点击剧本分割按钮并自动确认弹窗（通过 JS 避免遮挡问题）。

    通过设置 state.defaultWorldId 绕过 showConfirmModal 确认弹窗，
    并拦截剧本拆分相关 API 返回 mock 数据（外部 LLM 不可用）。

    前端已迁移到增量拆分异步任务模式（见 web/js/script_split_task.js），
    完整流程为三步，本 mock 全部覆盖：
      1. POST /api/parse-script              → {code:0, data:{task_id}}
      2. GET  /api/script-split/tasks/{id}   → {code:0, data:{status:'completed', ...}}
      3. GET  /api/script-split/tasks/{id}/result → {code:0, data:{shot_groups:[...]}}
    """
    import json as _json

    # 任意稳定的 mock task_id（前端会带到后续两个端点的 URL 中）
    mock_task_id = "9000001"

    def _build_shot_groups(content):
        # 按换行分割场景
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        if not lines:
            lines = [content or "场景一"]
        shot_groups = []
        for i, line in enumerate(lines):
            shot_groups.append({
                "group_name": f"分镜组{i+1}",
                "group_index": i,
                "shots": [{
                    "shot_number": i + 1,
                    "description": line,
                    "duration": 5,
                    "camera_movement": "固定",
                    "prompt": line,
                }]
            })
        return shot_groups

    # 1) 拦截提交端点：返回 task_id，记录剧本内容供后续 result 使用
    captured = {"content": ""}

    def handle_parse_script(route):
        try:
            body = _json.loads(route.request.post_data or "{}")
            captured["content"] = body.get("script_content", "")
        except Exception:
            captured["content"] = ""
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_json.dumps({
                "code": 0,
                "data": {
                    "task_id": mock_task_id,
                    "status": "queued",
                    "status_url": f"/api/script-split/tasks/{mock_task_id}",
                },
            }),
        )

    # 2) 拦截轮询端点：直接返回 completed（前端收到即停止轮询并拉取 result）
    def handle_task_status(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_json.dumps({
                "code": 0,
                "data": {
                    "task_id": mock_task_id,
                    "status": "completed",
                    "phase": "done",
                    "progress": 100,
                    "message": "解析完成",
                    "poll_after_ms": 500,
                },
            }),
        )

    # 3) 拦截结果端点：返回与剧本内容对应的 shot_groups（前端据此物化节点）
    def handle_task_result(route):
        shot_groups = _build_shot_groups(captured["content"])
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_json.dumps({
                "code": 0,
                "data": {
                    "shot_groups": shot_groups,
                    "max_group_duration": 15,
                },
            }),
        )

    page.route("**/api/parse-script", handle_parse_script)
    page.route(f"**/api/script-split/tasks/{mock_task_id}", handle_task_status)
    page.route(f"**/api/script-split/tasks/{mock_task_id}/result", handle_task_result)
    # 兜底：若前端用其他 task_id 轮询（理论上不会），用通配也返回 completed
    page.route("**/api/script-split/tasks/*/result", handle_task_result)

    # 设置 defaultWorldId 绕过 confirm modal（state 是全局 const 变量）
    page.evaluate("() => { if (typeof state !== 'undefined') state.defaultWorldId = 1; }")
    page.wait_for_timeout(200)

    # 点击 split 按钮
    page.evaluate("""() => {
        const btn = document.querySelector('.node.selected .script-split-btn');
        if (btn) btn.click();
    }""")

    # 等待 API mock 响应、轮询、结果物化完成
    page.wait_for_timeout(8000)

    # 取消路由拦截
    page.unroute("**/api/parse-script")
    page.unroute(f"**/api/script-split/tasks/{mock_task_id}")
    page.unroute(f"**/api/script-split/tasks/{mock_task_id}/result")
    page.unroute("**/api/script-split/tasks/*/result")
