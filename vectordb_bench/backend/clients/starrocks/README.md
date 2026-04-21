# StarRocks Vector Search Benchmark

VectorDBBench StarRocks 客户端，支持对已有 StarRocks 集群执行向量搜索基准测试（查询模式）。

## 前提条件

- StarRocks 3.3.x 及以上版本
- 表已创建，数据已导入，向量索引已建好
- 表结构要求：`id (BIGINT)` + `embedding (ARRAY<FLOAT>)`

## 安装

```bash
pip install -e '.[starrocks]'
```

## 表结构示例

```sql
CREATE TABLE test.benchmark_768d1m (
    id BIGINT,
    embedding ARRAY<FLOAT>
) ENGINE=OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(id) BUCKETS 16;

-- 创建向量索引（以 COSINE 为例）
ALTER TABLE test.benchmark_768d1m
ADD INDEX vec_idx (embedding) USING VECTOR (
    "index_type" = "ivfpq",
    "dim" = "768",
    "metric_type" = "cosine",
    "is_vector_normed" = "false",
    "nbits" = "8",
    "nlist" = "16384"
);
```

## 数据导入

需要将 VectorDBBench 提供的数据集导入到 StarRocks 表中。数据集会在首次运行时自动下载到本地 `~/.vectordb_bench/dataset/` 目录（Parquet 格式）。

你可以用 StarRocks 的 Broker Load、Stream Load 或 INSERT INTO 等方式将 Parquet 数据导入表中。

## 基本用法

```bash
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host <starrocks_host> \
  --port 9030 \
  --user root \
  --password '' \
  --database test \
  --table-name benchmark_768d1m \
  --case-type Performance768D1M \
  --search-serial \
  --skip-search-concurrent \
  --k 100
```

### 参数说明

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--host` | 127.0.0.1 | StarRocks FE 地址 |
| `--port` | 9030 | StarRocks MySQL 协议端口 |
| `--user` | root | 用户名 |
| `--password` | (空) | 密码，也可通过环境变量 `STARROCKS_PASSWORD` 设置 |
| `--database` | test | 数据库名 |
| `--table-name` | (必填) | 表名，支持 `catalog.db.table` 全限定格式 |
| `--sql-hint` | (空) | SQL hint，如 `/*+set_var(top_index_local_rows=1000)*/` |
| `--case-type` | (必填) | 测试用例类型，见下方说明 |
| `--skip-drop-old` | - | 跳过删表重建（必须加） |
| `--skip-load` | - | 跳过数据导入（必须加） |
| `--search-serial` | - | 执行串行搜索测试（recall + latency） |
| `--search-concurrent` | - | 执行并发搜索测试（QPS） |
| `--skip-search-serial` | - | 跳过串行搜索 |
| `--skip-search-concurrent` | - | 跳过并发搜索 |
| `--k` | 100 | TopK 返回数量 |
| `--db-label` | (空) | 自定义标签，用于区分不同测试结果 |

## case-type 与数据集对照表

选择 `--case-type` 时，需确保你的 StarRocks 表中导入的数据与该 case 对应的数据集一致。

### COSINE 度量（approx_cosine_similarity）

| case-type | 数据集 | 维度 | 数据量 | 说明 |
|---|---|---|---|---|
| `Performance768D1M` | Cohere | 768 | 100万 | 基础搜索 |
| `Performance768D10M` | Cohere | 768 | 1000万 | 基础搜索 |
| `Performance768D1M1P` | Cohere | 768 | 100万 | 过滤1%（WHERE id >= N） |
| `Performance768D1M99P` | Cohere | 768 | 100万 | 过滤99% |
| `Performance768D10M1P` | Cohere | 768 | 1000万 | 过滤1% |
| `Performance768D10M99P` | Cohere | 768 | 1000万 | 过滤99% |
| `Performance1536D50K` | OpenAI | 1536 | 5万 | 基础搜索 |
| `Performance1536D500K` | OpenAI | 1536 | 50万 | 基础搜索 |
| `Performance1536D5M` | OpenAI | 1536 | 500万 | 基础搜索 |
| `Performance1024D1M` | Bioasq | 1024 | 100万 | 基础搜索 |
| `Performance1024D10M` | Bioasq | 1024 | 1000万 | 基础搜索 |

### L2 度量（approx_l2_distance）

| case-type | 数据集 | 维度 | 数据量 | 说明 |
|---|---|---|---|---|
| `Performance768D100M` | LAION | 768 | 1亿 | 基础搜索 |

metric_type 会根据 case-type 自动匹配，无需手动指定。

## 支持的度量类型

| metric_type | StarRocks 函数 | 排序 | 说明 |
|---|---|---|---|
| COSINE | `approx_cosine_similarity` | DESC | 余弦相似度，值越大越相似 |
| L2 | `approx_l2_distance` | ASC | 欧氏距离，值越小越近 |
| IP | `approx_inner_product` | DESC | 内积，值越大越相似 |

## 执行的查询 SQL

框架会对每个测试向量执行如下 SQL：

```sql
-- COSINE 度量（相似度越大越好）
SELECT id FROM {table_name}
ORDER BY approx_cosine_similarity(embedding, [0.12,0.34,...]) DESC
LIMIT 100

-- L2 度量（距离越小越好）
SELECT id FROM {table_name}
ORDER BY approx_l2_distance(embedding, [0.12,0.34,...]) ASC
LIMIT 100

-- IP 度量（内积越大越好）
SELECT id FROM {table_name}
ORDER BY approx_inner_product(embedding, [0.12,0.34,...]) DESC
LIMIT 100

-- 带 SQL hint 时
SELECT /*+set_var(top_index_local_rows=1000)*/ id FROM {table_name}
ORDER BY approx_cosine_similarity(embedding, [0.12,0.34,...]) DESC
LIMIT 100

-- 带过滤条件时
SELECT id FROM {table_name}
WHERE id >= {filter_value}
ORDER BY approx_cosine_similarity(embedding, [0.12,0.34,...]) DESC
LIMIT 100
```

## 测试模式

### 串行搜索（--search-serial）

逐个执行所有测试向量的查询，计算：
- **Recall**: 与 ground truth 对比的召回率
- **NDCG**: 归一化折损累积增益
- **P99 Latency**: 99分位延迟
- **P95 Latency**: 95分位延迟

### 并发搜索（--search-concurrent）

多进程并发执行查询，默认并发数 [1, 5, 10, 15, 20, 25, 30, 35]，每个并发级别持续30秒，计算：
- **Max QPS**: 最大吞吐量
- **P99/P95/Avg Latency**: 各并发级别的延迟

## 使用示例

### 只测 Recall

```bash
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 10.0.0.1 --port 9030 \
  --database test --table-name vec_768d1m \
  --case-type Performance768D1M \
  --search-serial --skip-search-concurrent
```

### 只测 QPS

```bash
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 10.0.0.1 --port 9030 \
  --database test --table-name vec_768d1m \
  --case-type Performance768D1M \
  --skip-search-serial --search-concurrent
```

### 同时测 Recall 和 QPS

```bash
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 10.0.0.1 --port 9030 \
  --database test --table-name vec_768d1m \
  --case-type Performance768D1M \
  --search-serial --search-concurrent
```

### 带过滤条件的测试

```bash
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 10.0.0.1 --port 9030 \
  --database test --table-name vec_768d1m \
  --case-type Performance768D1M1P \
  --search-serial --skip-search-concurrent
```

### Paimon 外表测试

```bash
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 10.0.0.1 --port 9030 \
  --database test \
  --table-name paimon_catalog.db_name.table_name \
  --sql-hint "/*+set_var(top_index_local_rows = 1000)*/" \
  --case-type Performance768D1M \
  --search-serial --skip-search-concurrent
```

### 自定义标签区分多次测试

```bash
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 10.0.0.1 --port 9030 \
  --database test --table-name vec_768d1m \
  --case-type Performance768D1M \
  --search-serial --skip-search-concurrent \
  --db-label "starrocks-3nodes-ivfpq"
```

## 查看结果

测试结果保存在 `~/.vectordb_bench/results/` 目录下，JSON 格式。
