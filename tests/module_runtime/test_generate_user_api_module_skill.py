import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]  # 主仓根（develop_f1214 起 skill 迁入主仓）
SKILL = ROOT / "script_writer_core" / "skills" / "generate-user-api-module" / "SKILL.md"
AGENTS_CONFIG = ROOT / "script_writer_core" / "config" / "agents_config.json"
CONTRACT = ROOT / "script_writer_core" / "skills" / "generate-user-api-module" / "references" / "module-contract.md"


def test_generate_user_api_module_skill_defaults_to_polling():
    skill = SKILL.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")
    assert "completion_modes" in skill
    assert '["polling"]' in skill
    assert "webhook_url" in skill
    assert "禁止用 `ask_user` 询问回调 payload" in skill
    assert "不要声明 `webhook`" in skill
    assert "默认不使用 webhook" in contract
    assert "不要向管理员询问回调 payload" in contract


def test_generate_user_api_module_documents_local_comfyui_branch():
    skill = SKILL.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")
    assert "vendor/workflow.json" in skill
    assert "src/settings.py" in skill
    assert "module_runtime.comfyui" in skill
    assert "最多 15 问" in skill
    assert "禁止再问 ComfyUI" in skill
    assert "secret_names" in contract
    assert "COMFYUI_BASE_URL" in contract
    assert "module_runtime.comfyui" in contract
    assert "最多 15 次" in contract


def test_generate_user_api_module_max_iterations_raised():
    config = json.loads(AGENTS_CONFIG.read_text(encoding="utf-8"))
    assert config["expert_agents"]["generate-user-api-module"]["max_iterations"] >= 80


def test_generate_user_api_module_documents_optional_node_reset():
    """合同必须包含「可选输入节点显式置空」规则（RunningHub nodeInfoList 节点状态残留）。"""
    skill = SKILL.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")
    assert "可选输入节点必须显式置空" in contract
    assert "nodeInfoList" in contract
    assert 'or ""' in contract
    assert "置空" in skill


def test_generate_user_api_module_documents_platform_parameter_keys():
    """合同必须包含平台标准参数键与取参规则（先读标准键、前缀匹配、缺参 Rejected）。"""
    skill = SKILL.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")
    assert "平台标准参数键与取参规则" in contract
    assert "前缀 + 大小写不敏感匹配" in contract
    assert "禁止静默回落默认值" in contract
    assert "先读平台标准键" in skill
