import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pymysql

from vectordb_bench.backend.filter import Filter, FilterOp

from ..api import VectorDB
from .config import StarRocksCaseConfig, StarRocksConfigDict

log = logging.getLogger(__name__)


class StarRocks(VectorDB):
    thread_safe = False
    supported_filter_types: list[FilterOp] = [
        FilterOp.NonFilter,
        FilterOp.NumGE,
    ]

    def __init__(
        self,
        dim: int,
        db_config: StarRocksConfigDict,
        db_case_config: StarRocksCaseConfig,
        collection_name: str = "items",
        drop_old: bool = False,
        **kwargs,
    ):
        self.dim = dim
        self.db_config = db_config
        self.db_case_config = db_case_config
        self.table_name = collection_name

        self._conn = None
        self._cursor = None
        self.expr = ""
        self._sql_hint = db_case_config.sql_hint

        log.info(f"StarRocks initialized, table={self.table_name}, drop_old={drop_old}")

    def _connect(self):
        self._conn = pymysql.connect(
            host=self.db_config["host"],
            user=self.db_config["user"],
            port=self.db_config["port"],
            password=self.db_config["password"],
            database=self.db_config["database"],
        )
        self._cursor = self._conn.cursor()

    def _disconnect(self):
        if self._cursor:
            self._cursor.close()
            self._cursor = None
        if self._conn:
            self._conn.close()
            self._conn = None

    @contextmanager
    def init(self) -> Generator[None, None, None]:
        try:
            self._connect()
            yield
        finally:
            self._disconnect()

    def insert_embeddings(
        self,
        embeddings: list[list[float]],
        metadata: list[int],
        **kwargs: Any,
    ) -> tuple[int, Exception | None]:
        return 0, None

    def optimize(self, data_size: int | None = None):
        pass

    def prepare_filter(self, filters: Filter):
        if filters.type == FilterOp.NonFilter:
            self.expr = ""
        elif filters.type == FilterOp.NumGE:
            self.expr = f"WHERE id >= {filters.int_value}"
        else:
            msg = f"Unsupported filter for StarRocks: {filters}"
            raise ValueError(msg)

    def search_embedding(
        self,
        query: list[float],
        k: int = 100,
    ) -> list[int]:
        if not self._cursor:
            raise ValueError("Cursor is not initialized")

        vec_str = "[" + ",".join(str(v) for v in query) + "]"
        metric_func = self.db_case_config.parse_metric_func()
        order = self.db_case_config.parse_order()
        hint = f" {self._sql_hint}" if self._sql_hint else ""

        sql = (
            f"SELECT{hint} id FROM {self.table_name} "
            f"{self.expr} "
            f"ORDER BY {metric_func}(embedding, {vec_str}) {order} "
            f"LIMIT {k}"
        )

        self._cursor.execute(sql)
        return [row[0] for row in self._cursor.fetchall()]
