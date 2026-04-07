# 2026-04-07 状态更新

## 本次完成的主线

今天围绕两条主线做了收口和验证：

- Chat 与 Know-how 权限链路重新梳理并补强
- 会话列表与会话访问权限统一收口为“仅本人可见”

## Chat 与 Know-how 权限现状

当前 Chat 链路已经不是“默认把规则库当成全库公共资源注入”。

实际生效的可见范围是：

- 自己的个人规则
- 自己所在用户组的共享规则
- 显式授权给自己的规则
- 显式授权给自己所在用户组的规则
- `public` 规则
- 管理员可见全部规则

这条链路已经从 `chat` 入口一直打通到 Know-how 存储层：

- `backend/routers/chat.py`
- `backend/services/context_assembler.py`
- `backend/services/knowhow_service.py`
- `backend/services/storage.py`
- `backend/services/access_control.py`

同时，Chat 下 Know-how 已经补齐了几个关键闭环：

- 命中规则会回写 `hit_count`
- 规则库问答与规则应用召回已经分流
- 规则库摘要按当前用户可见范围实时生成
- Know-how 引用会携带分类、命中方式、置信度和命中原因

## Know-how 管理权限现状

管理员仍然拥有全量管理权限。

组内 `can_manage_group_knowhow=1` 的用户现在具备“本组 Know-how manager”能力，但作用域已经被收紧到本组，不再是泛化的库管理员。

当前口径：

- 组内 manager 可以创建自己的个人规则
- 组内 manager 可以创建共享给本组的 baseline 规则
- 组内 manager 只能管理本组共享规则
- 组内 manager 只能管理本组共享规则正在使用的分类
- 组内 manager 只能追加导入、导出本组规则
- 导入去重按其可管理范围计算

## 会话隐私现状

会话现在统一按“仅本人可见 / 可操作”处理。

当前口径：

- 管理员只看自己的会话
- 组内 manager 只看自己的会话
- 普通用户只看自己的会话

已经收口的关键点：

- `GET /api/chat/state` 只返回当前用户自己的会话
- 会话详情、消息列表、消息读写都不再给管理员开全量直通

## 本次验证

- `pytest backend/tests -q` -> `120 passed`

这次补充覆盖了：

- Chat 下 Know-how 权限作用域
- 规则库统计问法的可见范围
- 组内 manager 的规则 / 分类 / 导入导出作用域
- 管理员仅可见自己的会话
- 管理员不能访问其他用户的会话消息
