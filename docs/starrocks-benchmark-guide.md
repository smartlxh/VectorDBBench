# StarRocks 向量搜索基准测试指南

本文档描述如何使用 VectorDBBench 对 StarRocks 向量搜索能力进行完整的基准测试，包括环境准备、数据导入、测试执行和结果分析。

---

## 1. 环境要求

| 组件 | 版本要求 | 说明 |
|---|---|---|
| StarRocks | >= 3.3.x | 支持 `ARRAY<FLOAT>` 和 `approx_cosine_similarity` |
| Python | >= 3.11 | VectorDBBench 运行环境 |
| PyMySQL | 最新版 | StarRocks MySQL 协议驱动 |
| 磁盘空间 | >= 20GB | 用于下载和缓存数据集（Parquet 文件） |

## 2. 安装

```bash
# 克隆项目
git clone https://github.com/zilliztech/VectorDBBench.git
cd VectorDBBench

# 安装（含 StarRocks 依赖）
pip install -e '.[starrocks]'

# 验证安装
vectordbbench starrocks --help
```

## 3. StarRocks 端准备

### 3.1 建表

根据要测试的 case-type 选择对应维度建表。以 Cohere 768D 100万条数据为例：

```sql
CREATE DATABASE IF NOT EXISTS benchmark;
USE benchmark;

CREATE TABLE benchmark_cohere_768d1m (
    id BIGINT,
    embedding ARRAY<FLOAT>
)
ENGINE = OLAP
DUPLICATE KEY(id)
DISTRIBUTED BY HASH(id) BUCKETS 16
PROPERTIES (
    "replication_num" = "1"
);
```

**不同 case-type 的建表维度参考：**

| case-type | 数据集 | 维度 | 数据量 | 建表建议 |
|---|---|---|---|---|
| Performance768D1M | Cohere | 768 | 1,000,000 | BUCKETS 16 |
| Performance768D10M | Cohere | 768 | 10,000,000 | BUCKETS 32 |
| Performance1536D500K | OpenAI | 1536 | 500,000 | BUCKETS 16 |
| Performance1536D5M | OpenAI | 1536 | 5,000,000 | BUCKETS 32 |
| Performance1024D1M | Bioasq | 1024 | 1,000,000 | BUCKETS 16 |

### 3.2 导入数据

VectorDBBench 的数据集会在首次运行时自动下载到 `/tmp/vectordb_bench/dataset/` 目录（可通过环境变量 `DATASET_LOCAL_DIR` 修改）。

数据文件为 Parquet 格式，包含两个字段：
- `id`：整数 ID
- `emb`：浮点数向量数组

**方法一：先用 VectorDBBench 下载数据，再用 Stream Load 导入**

```bash
# 先运行一次让框架下载数据（会因连接不上而失败，但数据已下载）
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 127.0.0.1 --port 9030 \
  --database benchmark --table-name benchmark_cohere_768d1m \
  --case-type Performance768D1M \
  --search-serial --skip-search-concurrent \
  --dry-run

# 数据位置（Cohere 768D 1M）
ls /tmp/vectordb_bench/dataset/cohere_medium_1000000/
# 文件: shuffle_train-1-of-1.parquet, test.parquet, neighbors.parquet
```

**方法二：用 Python 脚本读取 Parquet 并通过 INSERT 导入**

```python
import pandas as pd
import pymysql

# 读取训练数据
df = pd.read_parquet("/tmp/vectordb_bench/dataset/cohere_medium_1000000/shuffle_train-1-of-1.parquet")

conn = pymysql.connect(host="127.0.0.1", port=9030, user="root", password="", database="benchmark")
cursor = conn.cursor()

batch_size = 500
for start in range(0, len(df), batch_size):
    batch = df.iloc[start:start+batch_size]
    values = []
    for _, row in batch.iterrows():
        vec_str = "[" + ",".join(str(v) for v in row["emb"]) + "]"
        values.append(f"({row['id']}, {vec_str})")
    sql = f"INSERT INTO benchmark_cohere_768d1m VALUES {','.join(values)}"
    cursor.execute(sql)
    conn.commit()
    print(f"Inserted {start + len(batch)}/{len(df)}")

cursor.close()
conn.close()
```

**方法三：使用 StarRocks Broker Load（适合大数据量）**

```sql
-- 将 Parquet 文件上传到 HDFS 或 S3 后
LOAD LABEL benchmark.load_cohere_768d1m
(
    DATA INFILE("s3://your-bucket/cohere_medium_1000000/shuffle_train-1-of-1.parquet")
    INTO TABLE benchmark_cohere_768d1m
    FORMAT AS "parquet"
    (id, emb)
    SET (embedding = emb)
)
WITH S3 (...)
PROPERTIES ("timeout" = "3600");
```

### 3.3 创建向量索引

```sql
-- COSINE 度量索引（适用于 Cohere/OpenAI/Bioasq 数据集）
ALTER TABLE benchmark_cohere_768d1m
ADD INDEX vec_idx (embedding) USING VECTOR (
    "index_type" = "ivfpq",
    "dim" = "768",
    "metric_type" = "cosine",
    "is_vector_normed" = "false",
    "nbits" = "8",
    "nlist" = "16384"
);

-- 查看索引创建进度
SHOW ALTER TABLE COLUMN FROM benchmark;
```

### 3.4 验证数据和索引

```sql
-- 确认数据量
SELECT COUNT(*) FROM benchmark_cohere_768d1m;
-- 预期: 1000000

-- 测试向量查询是否正常
SELECT id
FROM benchmark_cohere_768d1m
ORDER BY approx_cosine_similarity(embedding, [0.1, 0.2, ...])  -- 用任意768维向量
DESC LIMIT 10;
```

## 4. 运行基准测试

### 4.1 基础命令格式

```bash
vectordbbench starrocks \
  --skip-drop-old \            # 必须：不删表重建
  --skip-load \                # 必须：不导入数据
  --host <FE_HOST> \           # StarRocks FE 地址
  --port 9030 \                # MySQL 协议端口
  --user root \                # 用户名
  --password '' \              # 密码
  --database benchmark \       # 数据库名
  --table-name <TABLE> \       # 表名（支持 catalog.db.table 格式）
  --case-type <CASE> \         # 测试用例
  --k 100                      # TopK
```

**表结构要求**：表必须包含 `id (BIGINT)` 和 `embedding (ARRAY<FLOAT>)` 两列。

### 4.2 测试场景

#### 场景一：Recall + Latency 测试（串行搜索）

逐条执行所有测试向量查询，与 ground truth 对比计算召回率。

```bash
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 10.0.0.1 --port 9030 \
  --database benchmark --table-name benchmark_cohere_768d1m \
  --case-type Performance768D1M \
  --search-serial --skip-search-concurrent \
  --k 100
```

**输出指标：**
- `recall`：召回率（与 ground truth 对比）
- `ndcg`：归一化折损累积增益
- `serial_latency_p99`：P99 延迟（秒）
- `serial_latency_p95`：P95 延迟（秒）

#### 场景二：QPS 测试（并发搜索）

多进程并发发送查询，测量吞吐量。

```bash
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 10.0.0.1 --port 9030 \
  --database benchmark --table-name benchmark_cohere_768d1m \
  --case-type Performance768D1M \
  --skip-search-serial --search-concurrent \
  --num-concurrency 1,5,10,20,50 \
  --concurrency-duration 30 \
  --k 100
```

**输出指标：**
- `max_qps`：所有并发级别中的最大 QPS
- `conc_num_list`：并发数列表
- `conc_qps_list`：每个并发级别的 QPS
- `conc_latency_p99_list`：每个并发级别的 P99 延迟

#### 场景三：完整测试（Recall + QPS）

```bash
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 10.0.0.1 --port 9030 \
  --database benchmark --table-name benchmark_cohere_768d1m \
  --case-type Performance768D1M \
  --search-serial --search-concurrent \
  --k 100
```

#### 场景四：带过滤条件的测试

测试带 `WHERE id >= N` 过滤条件的向量搜索性能。

```bash
# 过滤 1%（查询 99% 的数据）
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 10.0.0.1 --port 9030 \
  --database benchmark --table-name benchmark_cohere_768d1m \
  --case-type Performance768D1M1P \
  --search-serial --skip-search-concurrent

# 过滤 99%（查询 1% 的数据）
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 10.0.0.1 --port 9030 \
  --database benchmark --table-name benchmark_cohere_768d1m \
  --case-type Performance768D1M99P \
  --search-serial --skip-search-concurrent
```

#### 场景五：多数据集对比测试

```bash
# OpenAI 1536D 500K
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 10.0.0.1 --port 9030 \
  --database benchmark --table-name benchmark_openai_1536d500k \
  --case-type Performance1536D500K \
  --search-serial --skip-search-concurrent

# Bioasq 1024D 1M
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 10.0.0.1 --port 9030 \
  --database benchmark --table-name benchmark_bioasq_1024d1m \
  --case-type Performance1024D1M \
  --search-serial --skip-search-concurrent
```

#### 场景六：Paimon 外表测试

支持通过 `--table-name` 指定全限定 catalog 表名，通过 `--sql-hint` 添加查询优化提示。

```bash
vectordbbench starrocks \
  --skip-drop-old --skip-load \
  --host 10.0.0.1 --port 9030 \
  --database test \
  --table-name paimon_catalog.db_name.table_name \
  --sql-hint "/*+set_var(top_index_local_rows = 1000)*/" \
  --case-type Performance768D1M \
  --search-serial --skip-search-concurrent \
  --k 100
```

生成的 SQL：
```sql
SELECT /*+set_var(top_index_local_rows = 1000)*/ id
FROM paimon_catalog.db_name.table_name
ORDER BY approx_cosine_similarity(embedding, [0.12,0.34,...]) DESC
LIMIT 100
```

### 4.3 高级参数

```bash
# SQL 优化提示
--sql-hint "/*+set_var(top_index_local_rows=1000)*/"

# 自定义并发参数
--num-concurrency 1,5,10,20,50,100    # 并发数序列
--concurrency-duration 60              # 每个并发级别持续时间（秒）
--concurrency-timeout 3600             # 并发等待超时（秒）

# 标记测试
--db-label "sr33-3node-ivfpq-16384"   # 自定义标签
--task-label "standard_2025"           # 任务标签（打榜用）

# 调试
--dry-run                              # 只打印配置不执行

# 中国区加速下载数据集
export DATASET_SOURCE=AliyunOSS
```

### 4.4 完整参数列表

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--host` | 127.0.0.1 | StarRocks FE 地址 |
| `--port` | 9030 | MySQL 协议端口 |
| `--user` | root | 用户名 |
| `--password` | (空) | 密码，也可通过环境变量 `STARROCKS_PASSWORD` 设置 |
| `--database` | test | 数据库名 |
| `--table-name` | (必填) | 表名，支持 `catalog.db.table` 全限定格式 |
| `--sql-hint` | (空) | SQL hint，如 `/*+set_var(...)*/` |
| `--case-type` | (必填) | 测试用例类型 |
| `--skip-drop-old` | - | 跳过删表重建（查询模式必须加） |
| `--skip-load` | - | 跳过数据导入（查询模式必须加） |
| `--search-serial` | - | 执行串行搜索（recall + latency） |
| `--search-concurrent` | - | 执行并发搜索（QPS） |
| `--skip-search-serial` | - | 跳过串行搜索 |
| `--skip-search-concurrent` | - | 跳过并发搜索 |
| `--k` | 100 | TopK 返回数量 |
| `--num-concurrency` | 1,10,20 | 并发数序列（逗号分隔） |
| `--concurrency-duration` | 30 | 每个并发级别持续时间（秒） |
| `--db-label` | (空) | 自定义标签 |
| `--task-label` | (空) | 任务标签（打榜用 `standard_2025`） |
| `--dry-run` | - | 只打印配置不执行 |

## 5. 查看结果

### 5.1 结果文件位置

测试结果自动保存在项目的 `vectordb_bench/results/` 目录下，JSON 格式。

```bash
# 查看最新结果
ls -lt vectordb_bench/results/StarRocks/
```

### 5.2 结果 JSON 结构

```json
{
  "run_id": "xxxxx",
  "task_label": "standard_2025",
  "results": [
    {
      "metrics": {
        "recall": 0.95,
        "ndcg": 0.96,
        "serial_latency_p99": 0.015,
        "serial_latency_p95": 0.012,
        "qps": 5000.0,
        "conc_num_list": [1, 5, 10, 20],
        "conc_qps_list": [500, 2000, 3800, 5000],
        "conc_latency_p99_list": [0.002, 0.003, 0.005, 0.008],
        "load_duration": 0
      },
      "task_config": {
        "db": "StarRocks",
        "case_config": { "case_id": "Performance768D1M" }
      }
    }
  ]
}
```

### 5.3 关键指标解读

| 指标 | 含义 | 参考范围 |
|---|---|---|
| recall | 召回率，与 ground truth 前100名的重合度 | 0.90+ 为优秀 |
| ndcg | 排序质量，考虑结果排名 | 0.90+ 为优秀 |
| serial_latency_p99 | 99% 查询的延迟上限 | 越小越好 |
| serial_latency_p95 | 95% 查询的延迟上限 | 越小越好 |
| qps (max) | 最大并发吞吐量 | 越大越好 |

## 6. 完整测试矩阵

以下是标准打榜需要执行的完整测试列表：

```bash
#!/bin/bash
# starrocks_benchmark.sh — StarRocks 完整基准测试脚本

SR_HOST="10.0.0.1"
SR_PORT=9030
SR_USER="root"
SR_PASS=""
SR_DB="benchmark"
LABEL="standard_2025"

COMMON="--skip-drop-old --skip-load \
  --host $SR_HOST --port $SR_PORT \
  --user $SR_USER --password $SR_PASS \
  --database $SR_DB \
  --search-serial --search-concurrent \
  --task-label $LABEL \
  --db-label starrocks-v3.3-3node \
  --k 100"

# === Cohere 768D ===
echo "=== Performance768D1M ==="
vectordbbench starrocks $COMMON \
  --table-name benchmark_cohere_768d1m \
  --case-type Performance768D1M

echo "=== Performance768D10M ==="
vectordbbench starrocks $COMMON \
  --table-name benchmark_cohere_768d10m \
  --case-type Performance768D10M

echo "=== Performance768D1M1P (Filter 1%) ==="
vectordbbench starrocks $COMMON \
  --table-name benchmark_cohere_768d1m \
  --case-type Performance768D1M1P 

echo "=== Performance768D1M99P (Filter 99%) ==="
vectordbbench starrocks $COMMON \
  --table-name benchmark_cohere_768d1m \
  --case-type Performance768D1M99P

# === OpenAI 1536D ===
echo "=== Performance1536D500K ==="
vectordbbench starrocks $COMMON \
  --table-name benchmark_openai_1536d500k \
  --case-type Performance1536D500K

echo "=== Performance1536D5M ==="
vectordbbench starrocks $COMMON \
  --table-name benchmark_openai_1536d5m \
  --case-type Performance1536D5M

# === Bioasq 1024D ===
echo "=== Performance1024D1M ==="
vectordbbench starrocks $COMMON \
  --table-name benchmark_bioasq_1024d1m \
  --case-type Performance1024D1M
```

## 7. 数据集与度量对照表

| 数据集 | 维度 | metric_type | StarRocks 函数 | 排序 |
|---|---|---|---|---|
| Cohere | 768 | COSINE | `approx_cosine_similarity` | DESC |
| OpenAI | 1536 | COSINE | `approx_cosine_similarity` | DESC |
| Bioasq | 1024 | COSINE | `approx_cosine_similarity` | DESC |
| LAION | 768 | L2 | `approx_l2_distance` | ASC |
| SIFT | 128 | L2 | `approx_l2_distance` | ASC |
| GIST | 960 | L2 | `approx_l2_distance` | ASC |

支持的度量类型：

| metric_type | StarRocks 函数 | 排序 | 说明 |
|---|---|---|---|
| COSINE | `approx_cosine_similarity` | DESC | 余弦相似度，值越大越相似 |
| L2 | `approx_l2_distance` | ASC | 欧氏距离，值越小越近 |
| IP | `approx_inner_product` | DESC | 内积，值越大越相似 |

metric_type 由框架根据 case-type 的数据集自动匹配，无需手动指定。

## 8. 常见问题

### Q: 首次运行很慢？
A: 框架需要从 S3 下载数据集（test.parquet + neighbors.parquet），Cohere 1M 约 3GB。中国区可设置 `export DATASET_SOURCE=AliyunOSS` 加速。

### Q: 报错 "Cursor is not initialized"？
A: 检查 StarRocks FE 地址和端口是否正确，确认网络连通性。

### Q: Recall 为 0？
A: 检查 case-type 对应的数据集是否正确导入到表中。数据的 id 和向量必须与数据集文件一致。

### Q: 如何只测单条查询延迟？
A: 使用 `--search-serial --skip-search-concurrent`，串行模式会逐条查询并报告延迟分布。

### Q: 如何调整并发测试的参数？
A: 使用 `--num-concurrency` 指定并发数序列（逗号分隔），`--concurrency-duration` 指定每个级别的持续时间。

### Q: 如何提交结果到 Leaderboard？
A: 将结果 JSON 文件放到 `vectordb_bench/results/StarRocks/` 目录，向 [VectorDBBench](https://github.com/zilliztech/VectorDBBench) 提交 PR。PR 需包含测试环境说明和复现步骤。

## 9. 性能调优建议

### StarRocks 端
- 调整 `vector_search_type`：尝试不同的搜索模式
- 调整索引参数：`nlist` 越大构建越慢但查询可能更准确
- 增加 BE 节点数和内存：提升并发查询吞吐
- 确保数据均匀分布在各 BUCKET 中

### VectorDBBench 端
- 使用 `--num-concurrency` 找到 QPS 拐点
- 对比不同索引类型（IVFPQ vs HNSW）的 recall 和 latency
- 使用 `--db-label` 区分不同配置的测试结果
