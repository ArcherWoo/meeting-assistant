# 2026-04-07 开发记录：Chat、Know-how 与会话隐私

## 目标

本次开发的目标有两个：

- 把 Chat 下 Know-how 的权限链路彻底校准
- 把会话可见性统一收口成“所有人只看自己的对话”

## 1. Chat 与 Know-how 权限链路

本次重新核查并验证了下面这条链路：

`backend/routers/chat.py`
-> `backend/services/context_assembler.py`
-> `backend/services/knowhow_service.py`
-> `backend/services/storage.py`
-> `backend/services/access_control.py`

当前 Chat 下 Know-how 的真实可见范围是：

- 个人规则
- 本组共享规则
- 显式授权给当前用户的规则
- 显式授权给当前用户组的规则
- `public` 规则
- 管理员全量

也就是说，Chat 侧已经与 Know-how 的权限模型对齐，不再是单独走一套“只按关键词全库扫”的旧行为。

## 2. Know-how 管理作用域

本次把“组内 Know-how manager”能力也收紧到了实际需要的作用域。

当前规则：

- 管理员可管理全量规则、全局分类、全量导入导出
- 组内 manager 可创建个人规则
- 组内 manager 可创建共享给本组的 baseline 规则
- 组内 manager 只能管理本组共享规则
- 组内 manager 只能管理本组共享规则正在使用的分类
- 组内 manager 只能追加导入、导出本组规则
- 导入去重按其可管理范围计算

## 3. Chat 命中闭环

这次还补齐了几个以前“调起来了但没闭环”的点：

- Chat 命中的 Know-how 规则现在会回写 `hit_count`
- 引用元数据增加了命中分类、命中方式、置信度和命中原因
- 规则库问答与规则应用召回已经分流
- 规则库摘要按当前用户可见范围实时生成

## 4. 会话隐私模型

会话列表、会话详情、消息列表和消息读写，现在统一按“仅本人可见 / 可操作”处理。

当前统一口径：

- 管理员只看自己的会话
- 组内 manager 只看自己的会话
- 普通用户只看自己的会话

对应实现已经落在：

- `backend/routers/conversations.py`

其中最关键的两点是：

- `GET /api/chat/state` 只返回当前用户自己的会话
- 会话访问校验不再给管理员开全量直通

## 5. 本次涉及的关键文件

- `backend/routers/chat.py`
- `backend/services/context_assembler.py`
- `backend/services/knowhow_service.py`
- `backend/services/knowhow_router.py`
- `backend/services/storage.py`
- `backend/services/access_control.py`
- `backend/routers/knowhow.py`
- `backend/routers/conversations.py`
- `backend/tests/test_auth_permissions.py`
- `backend/tests/test_conversations_router.py`

## 6. 验证结果

- `pytest backend/tests -q` -> `120 passed`

本次重点验证：

- Chat 下 Know-how 权限作用域
- 规则库统计问法的可见范围
- 组内 manager 的规则 / 分类 / 导入导出作用域
- 管理员仅可见自己的会话
- 管理员不能访问他人会话消息
