# config/config_loader.py — 配置加载器（修复版：增强调试 + 容错）

import os
import yaml
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_yaml(filename: str) -> Dict[str, Any]:
    filepath = os.path.join(CONFIG_DIR, filename)
    logger.info(f"📂 尝试加载: {filepath}")

    if not os.path.exists(filepath):
        logger.error(f"❌ 配置文件不存在: {filepath}")
        # 列出目录内容帮助调试
        try:
            files = os.listdir(CONFIG_DIR)
            logger.info(f"   config/ 目录内容: {files}")
        except Exception:
            pass
        return {}

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()

        # 调试：打印文件大小
        logger.info(f"   文件大小: {len(raw)} 字节")

        data = yaml.safe_load(raw)

        if data and isinstance(data, dict):
            keys = list(data.keys())
            logger.info(f"✅ 已加载配置: {filename} ({len(keys)} 个 key)")
            logger.info(f"   所有 key: {keys}")

            # 检查每个 key 是否有有效值
            for k, v in data.items():
                if v is None or (isinstance(v, str) and not v.strip()):
                    logger.warning(f"   ⚠️ key '{k}' 的值为空!")
        else:
            logger.warning(f"⚠️ 配置文件为空或格式错误: {filename}")
            return {}

        return data

    except yaml.YAMLError as e:
        logger.error(f"❌ YAML 解析失败 {filename}: {e}")
        # 尝试定位出错位置
        if hasattr(e, 'problem_mark'):
            mark = e.problem_mark
            logger.error(
                f"   错误位置: 第{mark.line + 1}行, 第{mark.column + 1}列"
            )
        return {}
    except Exception as e:
        logger.error(f"❌ 配置文件读取失败: {e}")
        return {}


class PromptManager:
    def __init__(self, prompt_file: str = "prompts.yaml"):
        self._prompts = _load_yaml(prompt_file)
        if not self._prompts:
            logger.warning("⚠️ Prompt 配置为空，所有调用将使用内置 fallback")

    def get(self, key: str, **kwargs) -> Optional[str]:
        """
        获取 Prompt 并填充变量。
        返回 None 表示 key 不存在，调用方应使用 fallback。
        """
        template = self._prompts.get(key)

        if template is None:
            logger.warning(
                f"⚠️ Prompt key 不存在: '{key}'，"
                f"可用 keys: {list(self._prompts.keys())}"
            )
            return None

        if not isinstance(template, str) or not template.strip():
            logger.warning(f"⚠️ Prompt key '{key}' 的值为空")
            return None

        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.warning(f"⚠️ Prompt 变量缺失: {key} -> {e}")
            return template

    def has(self, key: str) -> bool:
        return (
            key in self._prompts
            and self._prompts[key] is not None
            and isinstance(self._prompts[key], str)
            and bool(self._prompts[key].strip())
        )

    def reload(self, prompt_file: str = "prompts.yaml"):
        self._prompts = _load_yaml(prompt_file)
        logger.info(f"🔄 Prompt 已热更新: {prompt_file}")


class ReportTemplateManager:
    def __init__(self, template_file: str = "report_templates.yaml"):
        self._data = _load_yaml(template_file)
        self._system_role = self._data.get("system_role", "")
        self._templates = {
            k: v for k, v in self._data.items()
            if k != "system_role" and isinstance(v, dict)
        }

    @property
    def system_role(self) -> str:
        if not self._system_role:
            return (
                "你是一位拥有20年经验的三甲医院神经内科主任医师。"
                "禁止确诊语气。禁止具体剂量。"
            )
        return self._system_role

    def get_template(self, mode: str = "emergency") -> str:
        entry = self._templates.get(mode, {})
        if not entry:
            logger.warning(f"⚠️ 报告模板不存在: {mode}，使用 emergency")
            entry = self._templates.get("emergency", {})
        return entry.get("template", "")

    def get_template_name(self, mode: str = "emergency") -> str:
        entry = self._templates.get(mode, {})
        return entry.get("name", mode)

    def list_modes(self) -> list:
        return list(self._templates.keys())

    def update_doc_list(self, doc_names: list) -> None:
        """用本地/OSS 实际文件名替换 system_role 中的硬编码文献列表。
        若正则未能定位列表区域（例如 YAML 格式改变），保持静态列表不变。
        """
        import re
        if not doc_names:
            logger.warning("[文献列表] 传入文件名为空，保持静态列表")
            return

        new_list_text = "\n".join(f"- {name}" for name in sorted(set(doc_names)))
        # 匹配"严禁自行创造..."到"如需引用"之间的所有 "- ..." 条目
        pattern = r"(严禁自行创造[^\n]*\n)((?:- [^\n]*\n)+)(如需引用)"
        new_role, n = re.subn(pattern, rf"\g<1>{new_list_text}\n\g<3>", self._system_role)
        if n:
            self._system_role = new_role
            logger.info(f"[文献列表] 动态更新成功，共 {len(doc_names)} 篇: {doc_names}")
        else:
            logger.warning("[文献列表] 未能定位静态列表区域，使用 YAML 默认值")

    def reload(self, template_file: str = "report_templates.yaml"):
        self._data = _load_yaml(template_file)
        self._system_role = self._data.get("system_role", "")
        self._templates = {
            k: v for k, v in self._data.items()
            if k != "system_role" and isinstance(v, dict)
        }
        logger.info(f"🔄 报告模板已热更新: {template_file}")


_prompt_manager: Optional[PromptManager] = None
_report_manager: Optional[ReportTemplateManager] = None


def get_prompt_manager() -> PromptManager:
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager


def get_report_manager() -> ReportTemplateManager:
    global _report_manager
    if _report_manager is None:
        _report_manager = ReportTemplateManager()
    return _report_manager