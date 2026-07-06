# MiniMax endpoint 兼容性记录 2026-07-06

## 背景

澄清：MiniMax `.io` 是国际版 endpoint，当前项目使用 `.com` 国内版 key。

国际版 endpoint：

- `https://api.minimax.io/v1/t2a_v2`

国际版低 TTFA endpoint：

- `https://api-uw.minimax.io/v1/t2a_v2`

当前项目实际使用：

- `https://api.minimaxi.com/v1/t2a_v2`

结论：这不是要兼容的问题，而是国内/国际版 key 与 endpoint 不通用；日常使用 `.com` 即可。

## 处理

`tts/出音频.py` 当前默认使用 `.com` endpoint：

- `https://api.minimaxi.com/v1/t2a_v2`

仍保留 `MINIMAX_ENDPOINT` / `MINIMAX_ENDPOINTS` 显式配置能力，方便未来换国际版 key 时手动指定 `.io`。

最终成功的 endpoint 和候选列表会写入 `.minimax-request.json`：

- `endpoint`
- `endpoint_candidates`

## 验证命令

```powershell
$env:HEYTODAY_TTS_BACKEND = "minimax"
D:/project-script/VoxCPM/.venv/Scripts/python.exe tts/出音频.py 稿子/_MiniMax_endpoint兼容短测.md
```

## 验证结果

脚本使用 `.com` endpoint 并成功生成音频。

## 产物

- 短测稿：`稿子/_MiniMax_endpoint兼容短测.md`
- 音频：`音频/_MiniMax_endpoint兼容短测.minimax.mp3`
- request：`音频/_MiniMax_endpoint兼容短测.minimax.minimax-request.json`

request JSON 中记录：

```json
{
  "endpoint": "https://api.minimaxi.com/v1/t2a_v2",
  "endpoint_candidates": [
    "https://api.minimaxi.com/v1/t2a_v2"
  ]
}
```

## 后续

继续使用 `.com`，不再把 `.io` 鉴权失败视为待解决问题。

如果以后切换国际版 key，再重新验证 `.io` endpoint。
