# 解密集成指南 — 亿赛通 (EsafeNet) 加密文件

## 概述

系统支持双路径文件摄取：
- **普通路径**：文件直接进入解析管道。
- **加密路径**：文件先经过解密 Hook，再进入解析管道。

流程如下：

```
加密文件 → decrypt_esafenet_file() → 解密字节 → 标准解析管道 (PDF/DOCX/PPT...)
```

解密在内存中完成，不写入磁盘临时文件，防止明文泄漏。

## 步骤 1：定位解密 Hook

文件位置：`backend/utils/decryption_handler.py`

当前为占位实现（直接返回原始字节）：

```python
def decrypt_esafenet_file(file_bytes: bytes, filename: str) -> bytes:
    # TODO: 替换为真实的亿赛通解密逻辑
    return file_bytes
```

## 步骤 2：替换为真实解密逻辑

根据你的亿赛通 SDK 类型选择对应方案：

### 方案 A：调用远程解密服务器

```python
import requests

def decrypt_esafenet_file(file_bytes: bytes, filename: str) -> bytes:
    resp = requests.post(
        "http://your-esafenet-server:port/api/decrypt",
        files={"file": (filename, file_bytes)},
        timeout=30,
    )
    if resp.status_code != 200:
        raise ValueError(f"解密失败: HTTP {resp.status_code}")
    return resp.content
```

### 方案 B：使用本地 SDK (DLL/SO)

```python
import ctypes

_sdk = ctypes.CDLL("/path/to/esafenet_sdk.so")

def decrypt_esafenet_file(file_bytes: bytes, filename: str) -> bytes:
    buf = ctypes.create_string_buffer(file_bytes)
    out_len = ctypes.c_int(0)
    result = _sdk.DecryptBuffer(buf, len(file_bytes), ctypes.byref(out_len))
    if result != 0:
        raise ValueError(f"SDK 解密错误码: {result}")
    return buf.raw[:out_len.value]
```

## 步骤 3：测试

### 测试加密路径

1. 在前端知识库面板中勾选 **"加密"** 复选框（默认已勾选）。
2. 上传一个加密的 PDF/DOCX/PPT 文件。
3. 确认文件被正确解密并入库。

### 测试普通路径

1. 取消勾选 **"加密"** 复选框。
2. 上传一个普通文件。
3. 确认文件正常入库（不经过解密 Hook）。

## 技术细节

| 组件 | 文件 | 说明 |
|------|------|------|
| 解密 Hook | `backend/utils/decryption_handler.py` | 占位函数，替换为真实逻辑 |
| 服务层 | `backend/services/knowledge_service.py` | `ingest_file(is_encrypted=...)` |
| 路由层 | `backend/routers/knowledge.py` | `Form(True)` 接收前端标志 |
| 前端 API | `src/services/api.ts` | `uploadFiles(files, isEncrypted)` |
| 前端 UI | `src/components/layout/ContextPanel.tsx` | "加密" 复选框，默认勾选 |

## 注意事项

- 解密后文件扩展名保持不变，系统据此选择解析器（PDF/DOCX/PPT 等）。
- `owner_id` 等 RBAC 字段在加密/普通路径中均正常传递。
- 若解密失败，请在 `decrypt_esafenet_file` 中抛出 `ValueError`，前端会显示错误信息。

