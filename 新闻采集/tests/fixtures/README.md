# 测试夹具目录

离线测试（默认）的输入内联在各 `test_*.py` 中（畸形 RSS、空 Feed、HTML 异常、LLM 非法
JSON、断网/429/超时等），不依赖真实网站或真实 Kimi。

本目录用于存放**未来 live smoke 捕获的真实样本**：当操作者对某来源完成 robots/条款
核验并实跑 live smoke 后，可把抓到的真实 Feed / 正文 HTML / Kimi 响应（脱敏后）放
到这里作为回归夹具。`tests/conftest.py` 的 `FIXTURES_DIR` 指向本目录。

> 不要把含 API Key、Authorization 头或个人隐私的真实响应直接提交；提交前脱敏。
