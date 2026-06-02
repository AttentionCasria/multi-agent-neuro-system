"""
Agents模块共享常量
用于解耦不同agent模块之间的依赖关系

注意：这些常量已迁移到配置文件中（limits_config.yaml）
为了向后兼容，这里保留默认值，但建议使用配置管理器
"""

from app.config.config_loader import get_limits_manager

# 获取配置管理器单例
_limits_manager = None

def get_limits_config():
    """获取参数限制配置管理器"""
    global _limits_manager
    if _limits_manager is None:
        _limits_manager = get_limits_manager()
    return _limits_manager

# 检索相关上限（默认值，实际使用时建议从配置读取）
MAX_SUB_QUESTIONS = 3
MAX_EVIDENCE_CHARS = 2000
MAX_EVIDENCE_PER_QUESTION = 600
MAX_PROPOSAL_CHARS = 3000
MAX_CRITIQUE_CHARS = 3000

def get_max_sub_questions():
    """获取最大子问题数量（从配置读取）"""
    return get_limits_config().get_max_sub_questions() or MAX_SUB_QUESTIONS

def get_max_evidence_chars():
    """获取最大证据字符数（从配置读取）"""
    return get_limits_config().get_max_evidence_chars() or MAX_EVIDENCE_CHARS

def get_max_evidence_per_question():
    """获取每个问题的最大证据字符数（从配置读取）"""
    return get_limits_config().get_max_evidence_per_question() or MAX_EVIDENCE_PER_QUESTION

def get_max_proposal_chars():
    """获取最大提案字符数（从配置读取）"""
    return get_limits_config().get_max_proposal_chars() or MAX_PROPOSAL_CHARS

def get_max_critique_chars():
    """获取最大批判字符数（从配置读取）"""
    return get_limits_config().get_max_critique_chars() or MAX_CRITIQUE_CHARS

def get_diagnostic_keywords():
    """获取诊断相关关键词（从配置读取）"""
    return get_limits_config().get_diagnostic_keywords()

def get_treatment_keywords():
    """获取治疗相关关键词（从配置读取）"""
    return get_limits_config().get_treatment_keywords()

def get_prognosis_keywords():
    """获取预后相关关键词（从配置读取）"""
    return get_limits_config().get_prognosis_keywords()