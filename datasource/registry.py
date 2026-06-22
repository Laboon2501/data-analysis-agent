"""数据源注册表，保存可安全返回给前端的数据源元数据。"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

from pydantic import Field
from sqlalchemy.engine import make_url

from app.config import AppConfig
from datasource.factory import datasource_url_to_sqlalchemy_url
from datasource.file_datasource import (
    file_kind_for_path,
    import_file_to_sqlite,
    validate_supported_file_path,
)
from datasource.sqlalchemy_datasource import SQLAlchemyDataSource
from schemas._base import StrictBaseModel, utc_now

DEMO_DATASOURCE_ID = "ecommerce-demo-sqlite"
DEMO_DATASOURCE_NAME = "Ecommerce demo SQLite"
DEMO_DB_PATH = Path(__file__).resolve().parents[1] / "demo" / "ecommerce_demo.sqlite"
DATASOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class DataSourceKind(StrEnum):
    """支持注册的数据源类型。"""

    SQLITE = "sqlite"
    SQLALCHEMY = "sqlalchemy"
    FILE_CSV = "file_csv"
    FILE_EXCEL = "file_excel"
    FILE_PARQUET = "file_parquet"


class DataSourceStatus(StrEnum):
    """数据源在 registry 中的轻量状态。"""

    AVAILABLE = "available"
    ERROR = "error"
    PROFILED = "profiled"


class DataSourceRecord(StrictBaseModel):
    """可返回给 API/Web UI 的数据源元数据，不包含明文密码。"""

    datasource_id: str
    name: str
    kind: DataSourceKind
    url: str | None = None
    db_path: str | None = None
    status: DataSourceStatus = DataSourceStatus.AVAILABLE
    created_at: str
    last_profiled_at: str | None = None
    schema_hash: str | None = None
    error_message: str | None = None
    original_filename: str | None = None
    source_type: str | None = None
    file_size: int | None = None
    table_name: str | None = None
    uploaded_at: str | None = None
    row_count: int | None = None
    columns: list[str] = Field(default_factory=list)


class DataSourceRegistry:
    """进程内数据源注册表，负责元数据、会话选择和 datasource 构造。"""

    def __init__(
        self,
        *,
        records: list[DataSourceRecord] | None = None,
        raw_urls: dict[str, str] | None = None,
    ) -> None:
        self._records: dict[str, DataSourceRecord] = {
            record.datasource_id: record for record in records or []
        }
        self._raw_urls: dict[str, str] = dict(raw_urls or {})
        self._sources: dict[str, SQLAlchemyDataSource] = {}

    @classmethod
    def from_config(
        cls,
        config: AppConfig | None = None,
        *,
        auto_register_demo: bool = True,
    ) -> DataSourceRegistry:
        """根据环境配置和本地 demo 文件创建默认 registry。"""

        active_config = config or AppConfig.from_env()
        registry = cls()
        if active_config.datasource_url:
            registry.register(
                datasource_id=active_config.datasource_id,
                name=active_config.datasource_id,
                kind=_kind_from_url(active_config.datasource_url),
                url=active_config.datasource_url,
            )
        if auto_register_demo and DEMO_DB_PATH.exists() and not registry.has(DEMO_DATASOURCE_ID):
            registry.register(
                datasource_id=DEMO_DATASOURCE_ID,
                name=DEMO_DATASOURCE_NAME,
                kind=DataSourceKind.SQLITE,
                db_path=str(DEMO_DB_PATH),
            )
        return registry

    def register(
        self,
        *,
        datasource_id: str,
        name: str,
        kind: DataSourceKind | str,
        url: str | None = None,
        db_path: str | None = None,
    ) -> DataSourceRecord:
        """注册一个 sqlite 或 SQLAlchemy 数据源，并返回安全元数据。"""

        normalized_kind = kind if isinstance(kind, DataSourceKind) else DataSourceKind(kind)
        datasource_id = _validate_datasource_id(datasource_id)
        raw_url = _source_url_for_record(normalized_kind, url=url, db_path=db_path)
        record = DataSourceRecord(
            datasource_id=datasource_id,
            name=name.strip() or datasource_id,
            kind=normalized_kind,
            url=_masked_url(raw_url) if normalized_kind is DataSourceKind.SQLALCHEMY else None,
            db_path=_safe_db_path(raw_url) if normalized_kind is DataSourceKind.SQLITE else None,
            status=DataSourceStatus.AVAILABLE,
            created_at=utc_now().isoformat(),
        )
        self._records[datasource_id] = record
        self._raw_urls[datasource_id] = raw_url
        self._sources.pop(datasource_id, None)
        return record

    def register_file_from_path(
        self,
        *,
        datasource_id: str,
        name: str | None,
        file_path: str | Path,
        upload_dir: str | Path,
        source_type: str,
        table_name: str | None = None,
        original_filename: str | None = None,
        max_bytes: int | None = None,
    ) -> DataSourceRecord:
        """注册文件数据源，内部转换为 SQLite 表以复用现有分析链路。"""

        datasource_id = _validate_datasource_id(datasource_id)
        source_path = validate_supported_file_path(Path(file_path), max_bytes=max_bytes)
        file_kind = DataSourceKind(file_kind_for_path(source_path))
        imported = import_file_to_sqlite(
            source_path=source_path,
            datasource_id=datasource_id,
            output_dir=Path(upload_dir),
            table_name=table_name,
            original_filename=original_filename or source_path.name,
            source_type=source_type,
            max_bytes=max_bytes,
        )
        raw_url = datasource_url_to_sqlalchemy_url(imported.sqlite_path)
        record = DataSourceRecord(
            datasource_id=datasource_id,
            name=(name or Path(imported.original_filename).stem or datasource_id).strip(),
            kind=file_kind,
            status=DataSourceStatus.AVAILABLE,
            created_at=utc_now().isoformat(),
            original_filename=Path(imported.original_filename).name,
            source_type=imported.source_type,
            file_size=imported.file_size,
            table_name=imported.table_name,
            uploaded_at=imported.uploaded_at,
            row_count=imported.row_count,
            columns=imported.columns,
        )
        self._records[datasource_id] = record
        self._raw_urls[datasource_id] = raw_url
        self._sources.pop(datasource_id, None)
        return record

    def has(self, datasource_id: str) -> bool:
        """返回 datasource_id 是否已注册。"""

        return datasource_id in self._records

    def list_records(self) -> list[DataSourceRecord]:
        """按 datasource_id 返回所有数据源元数据。"""

        return [self._records[key] for key in sorted(self._records)]

    def get_record(self, datasource_id: str) -> DataSourceRecord | None:
        """读取一个数据源元数据。"""

        return self._records.get(datasource_id)

    def only_datasource_id(self) -> str | None:
        """当且仅当 registry 中只有一个数据源时返回其 ID。"""

        if len(self._records) != 1:
            return None
        return next(iter(self._records))

    def get_data_source(self, datasource_id: str) -> SQLAlchemyDataSource:
        """构造或读取一个 SQLAlchemyDataSource。"""

        record = self._records.get(datasource_id)
        if record is None:
            raise KeyError(f"Unknown datasource_id: {datasource_id}")
        if datasource_id not in self._sources:
            raw_url = self._raw_urls[datasource_id]
            try:
                self._sources[datasource_id] = SQLAlchemyDataSource(
                    datasource_id=datasource_id,
                    url=raw_url,
                )
            except Exception as exc:
                self._records[datasource_id] = record.model_copy(
                    update={
                        "status": DataSourceStatus.ERROR,
                        "error_message": _safe_error_message(exc),
                    }
                )
                raise
        return self._sources[datasource_id]

    def mark_profiled(self, datasource_id: str, schema_hash: str | None) -> None:
        """在 Context Manager 成功后记录 profile 时间和 schema hash。"""

        record = self._records.get(datasource_id)
        if record is None:
            return
        self._records[datasource_id] = record.model_copy(
            update={
                "status": DataSourceStatus.PROFILED,
                "last_profiled_at": utc_now().isoformat(),
                "schema_hash": schema_hash,
                "error_message": None,
            }
        )

    def to_snapshot(self) -> dict[str, object]:
        """导出 registry 内部快照，供 API/worker 共享 datasource 状态。"""

        return {
            "records": [
                record.model_dump(mode="json")
                for record in sorted(self._records.values(), key=lambda item: item.datasource_id)
            ],
            "raw_urls": dict(self._raw_urls),
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, object]) -> DataSourceRegistry:
        """从内部快照恢复 registry；该快照不应直接返回给前端。"""

        raw_records = snapshot.get("records") or []
        if not isinstance(raw_records, list):
            raise ValueError("Datasource registry snapshot records must be a list.")
        raw_urls = snapshot.get("raw_urls") or {}
        if not isinstance(raw_urls, dict):
            raise ValueError("Datasource registry snapshot raw_urls must be an object.")
        records = [DataSourceRecord.model_validate(record) for record in raw_records]
        return cls(
            records=records,
            raw_urls={str(key): str(value) for key, value in raw_urls.items()},
        )


def _validate_datasource_id(datasource_id: str) -> str:
    """校验 datasource_id，避免路径或命令片段进入 ID。"""

    value = datasource_id.strip()
    if not value:
        raise ValueError("datasource_id cannot be blank.")
    if not DATASOURCE_ID_PATTERN.fullmatch(value):
        raise ValueError("datasource_id may only contain letters, numbers, '.', '_' and '-'.")
    return value


def _source_url_for_record(
    kind: DataSourceKind,
    *,
    url: str | None,
    db_path: str | None,
) -> str:
    """把 API 输入规范化为 SQLAlchemy 可用 URL。"""

    if kind is DataSourceKind.SQLITE:
        source_value = db_path or url
        if not source_value:
            raise ValueError("sqlite datasource requires db_path or url.")
        return datasource_url_to_sqlalchemy_url(source_value)
    if kind is DataSourceKind.SQLALCHEMY:
        if not url:
            raise ValueError("sqlalchemy datasource requires url.")
        return datasource_url_to_sqlalchemy_url(url)
    if kind in {DataSourceKind.FILE_CSV, DataSourceKind.FILE_EXCEL, DataSourceKind.FILE_PARQUET}:
        raise ValueError("file datasources must be registered through file endpoints.")
    if not url:
        raise ValueError("sqlalchemy datasource requires url.")
    return datasource_url_to_sqlalchemy_url(url)


def _kind_from_url(value: str) -> DataSourceKind:
    """根据配置值推断 datasource kind。"""

    normalized = value.strip().lower()
    if normalized.startswith("sqlite") or "://" not in normalized:
        return DataSourceKind.SQLITE
    return DataSourceKind.SQLALCHEMY


def _masked_url(raw_url: str) -> str:
    """隐藏 URL 中的密码后再返回给前端。"""

    try:
        return make_url(raw_url).render_as_string(hide_password=True)
    except Exception:
        return raw_url


def _safe_db_path(raw_url: str) -> str | None:
    """从 SQLite URL 中提取本地路径。"""

    parsed_url = make_url(raw_url)
    return parsed_url.database


def _safe_error_message(exc: Exception) -> str:
    """返回不包含连接串密码的错误摘要。"""

    return _masked_url(str(exc))[:300]


__all__ = [
    "DEMO_DATASOURCE_ID",
    "DataSourceKind",
    "DataSourceRecord",
    "DataSourceRegistry",
    "DataSourceStatus",
]
