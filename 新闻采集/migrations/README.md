# 迁移目录

由 Alembic 管理 Supabase Postgres 生产 schema；SQLite 只用于离线测试迁移：

- `0001_initial.py`：以 `Base.metadata.create_all` 创建全部七张表（与 ORM 模型同源）。
- `0002_article_duplicate_basis.py`：给 `news_article` 增加可空列 `duplicate_basis`，
  保留去重判定依据（plan §10.3）；幂等，仅当列不存在时新增。
- `0003_supabase_runtime.py`：增加稳定 URL 身份、数据库唯一约束与禁止重聚关系表，
  并为运行表启用 RLS 和服务端角色权限。
- `0004_supabase_security.py`：补齐禁止客户端访问策略、外键索引和 Alembic 版本表保护。

迁移通过 CLI 显式执行：

```bash
uv run news-ingestion db upgrade     # 升级到 head
uv run news-ingestion db status      # 查看当前 / head revision
```

其它命令启动时检查 revision；库未初始化或落后 `head` 时返回退出码 `6`，**不自动
迁移**。后续 schema 变更新增 revision；只有 SQLite 测试路径启用 batch 模式。
