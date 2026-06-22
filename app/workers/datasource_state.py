"""Shared datasource registry state for API and worker processes."""

from __future__ import annotations

from app.config import AppConfig
from datasource import DataSourceRegistry
from persistence import CacheStore

DATASOURCE_REGISTRY_CACHE_KEY = "datasource_registry:v1"
SESSION_DATASOURCE_CACHE_PREFIX = "session_datasource:"


def load_datasource_registry(
    cache_store: CacheStore,
    app_config: AppConfig,
) -> DataSourceRegistry:
    """从共享 cache 读取 datasource registry；缺失时按配置创建默认 registry。"""

    snapshot = cache_store.get(DATASOURCE_REGISTRY_CACHE_KEY)
    if isinstance(snapshot, dict):
        return DataSourceRegistry.from_snapshot(snapshot)
    registry = DataSourceRegistry.from_config(app_config, auto_register_demo=True)
    save_datasource_registry(cache_store, registry)
    return registry


def save_datasource_registry(
    cache_store: CacheStore,
    registry: DataSourceRegistry,
) -> None:
    """把 datasource registry 快照写入共享 cache，不写入文件正文。"""

    cache_store.set(DATASOURCE_REGISTRY_CACHE_KEY, registry.to_snapshot())


def save_session_datasource(
    cache_store: CacheStore,
    session_id: str,
    datasource_id: str,
) -> None:
    """保存 session 当前 datasource 选择，供 Celery 提交和任务执行共享。"""

    cache_store.set(_session_datasource_key(session_id), datasource_id)


def load_session_datasource(cache_store: CacheStore, session_id: str) -> str | None:
    """读取 session 当前 datasource 选择。"""

    value = cache_store.get(_session_datasource_key(session_id))
    return value if isinstance(value, str) and value else None


def delete_session_datasource(cache_store: CacheStore, session_id: str) -> None:
    """删除 session 当前 datasource 选择。"""

    cache_store.delete(_session_datasource_key(session_id))


def _session_datasource_key(session_id: str) -> str:
    """返回 session datasource cache key。"""

    return f"{SESSION_DATASOURCE_CACHE_PREFIX}{session_id}"


__all__ = [
    "DATASOURCE_REGISTRY_CACHE_KEY",
    "SESSION_DATASOURCE_CACHE_PREFIX",
    "delete_session_datasource",
    "load_datasource_registry",
    "load_session_datasource",
    "save_datasource_registry",
    "save_session_datasource",
]
