from typing import TypedDict

from pydantic import BaseModel, SecretStr

from ..api import DBCaseConfig, DBConfig, MetricType


class StarRocksConfigDict(TypedDict):
    user: str
    host: str
    port: int
    password: str
    database: str


class StarRocksConfig(DBConfig):
    user: SecretStr = SecretStr("root")
    password: SecretStr = SecretStr("")
    host: str = "127.0.0.1"
    port: int = 9030
    database: str = "test"
    collection_name: str = "items"

    def to_dict(self) -> dict:
        return {
            "user": self.user.get_secret_value(),
            "host": self.host,
            "port": self.port,
            "password": self.password.get_secret_value(),
            "database": self.database,
            "collection_name": self.collection_name,
        }


class StarRocksCaseConfig(BaseModel, DBCaseConfig):
    metric_type: MetricType = MetricType.COSINE
    sql_hint: str = ""
    vector_column: str = "embedding"
    metric_override: str = ""
    log_sql: bool = True

    def index_param(self) -> dict:
        return {}

    def search_param(self) -> dict:
        return {}

    def _effective_metric(self) -> MetricType:
        if self.metric_override:
            return MetricType[self.metric_override.upper()]
        return self.metric_type

    def parse_metric_func(self) -> str:
        m = self._effective_metric()
        if m == MetricType.L2:
            return "approx_l2_distance"
        if m == MetricType.IP:
            return "approx_inner_product"
        return "approx_cosine_similarity"

    def parse_order(self) -> str:
        if self._effective_metric() == MetricType.L2:
            return "ASC"
        return "DESC"
