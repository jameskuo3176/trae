"""Core 核心逻辑模块

提供应用初始化、数据库配置、安全检查、错误处理等核心功能。
"""
from .db_routing import (
    setup_binds,
    switch_to_project,
    get_active_project_id,
    project_query,
    project_add,
    project_commit,
    project_rollback,
    PROJECT_BIND,
)

__all__ = [
    'setup_binds',
    'switch_to_project',
    'get_active_project_id',
    'project_query',
    'project_add',
    'project_commit',
    'project_rollback',
    'PROJECT_BIND',
]
