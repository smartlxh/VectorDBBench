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

    def index_param(self) -> dict:
        return {}

    def search_param(self) -> dict:
        return {}

    def parse_metric_func(self) -> str:
        if self.metric_type == MetricType.L2:
            return "approx_l2_distance"
        if self.metric_type == MetricType.IP:
            return "approx_inner_product"
        return "approx_cosine_similarity"

    def parse_order(self) -> str:
        if self.metric_type == MetricType.L2:
            return "ASC"
        return "DESC"
