import os
from typing import Annotated, Unpack

import click
from pydantic import SecretStr

from vectordb_bench.backend.clients import DB
from vectordb_bench.cli.cli import (
    CommonTypedDict,
    cli,
    click_parameter_decorators_from_typed_dict,
    run,
)


class StarRocksTypedDict(CommonTypedDict):
    host: Annotated[str, click.option("--host", type=str, help="StarRocks host", default="127.0.0.1")]
    port: Annotated[int, click.option("--port", type=int, help="StarRocks query port", default=9030)]
    user: Annotated[str, click.option("--user", type=str, help="StarRocks username", default="root")]
    password: Annotated[
        str,
        click.option(
            "--password",
            type=str,
            help="StarRocks password",
            default=lambda: os.environ.get("STARROCKS_PASSWORD", ""),
        ),
    ]
    database: Annotated[str, click.option("--database", type=str, help="Database name", default="test")]
    table_name: Annotated[str, click.option("--table-name", type=str, help="Table name (supports catalog.db.table)", required=True)]
    sql_hint: Annotated[str, click.option("--sql-hint", type=str, help="SQL hint, e.g. /*+set_var(top_index_local_rows=1000)*/", default="")]
    vector_column: Annotated[str, click.option("--vector-column", type=str, help="Name of the vector column in the table", default="embedding")]
    metric_override: Annotated[str, click.option("--metric-override", type=click.Choice(["", "COSINE", "L2", "IP"], case_sensitive=False), help="Override metric inferred from case-type (use when index metric differs from dataset). Recall will be meaningless if used.", default="")]
    no_log_sql: Annotated[bool, click.option("--no-log-sql", is_flag=True, help="Suppress SQL logging (useful for benchmark runs, enable for debug)")]


@cli.command()
@click_parameter_decorators_from_typed_dict(StarRocksTypedDict)
def StarRocks(**parameters: Unpack[StarRocksTypedDict]):
    from .config import StarRocksCaseConfig, StarRocksConfig

    run(
        db=DB.StarRocks,
        db_config=StarRocksConfig(
            db_label=parameters["db_label"],
            user=SecretStr(parameters["user"]),
            password=SecretStr(parameters["password"]),
            host=parameters["host"],
            port=parameters["port"],
            database=parameters["database"],
            collection_name=parameters["table_name"],
        ),
        db_case_config=StarRocksCaseConfig(
            sql_hint=parameters["sql_hint"],
            vector_column=parameters["vector_column"],
            metric_override=parameters["metric_override"],
            log_sql=not parameters["no_log_sql"],
        ),
        **parameters,
    )
