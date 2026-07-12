# 迁移目录

由 Alembic 管理 SQLite schema：

- `0001_initial.py`：以 `Base.metadata.create_all` 创建全部七张表（与 ORM 模型同源）。
- `0002_article_duplicate_basis.py`：给 `news_article` 增加可空列 `duplicate_basis`，
  保留去重判定依据（plan §10.3）；幂等，仅当列不存在时新增。

迁移通过 CLI 显式执行：

```bash
uv run news-ingestion db upgrade     # 升级到 head
uv run news-ingestion db status      # 查看当前 / head revision
```

其它命令启动时检查 revision；库未初始化或落后 `head` 时返回退出码 `6`，**不自动
迁移**。后续 schema 变更新增 revision，并使用 batch 模式（SQLite 已在 env.py 启用）。
