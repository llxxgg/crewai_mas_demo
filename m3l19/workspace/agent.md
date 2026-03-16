# Agent 行为规范

## 工作流程

1. 收到任务 → 判断是否需要搜索/抓取信息
2. 需要 → 调工具获取数据 → 用 save_intermediate_result 保存重要结果 → 给出回复
3. 不需要 → 直接回复

## 记忆写入规范

**写入前必须先读取**：调用 `File Writer Tool` 之前，必须先用 `Read a file's content`
读取现有内容，在原有内容基础上增量修改，不得覆盖或丢失已有内容。

**工具用法：**
- 读取：`Read a file's content`，参数 `file_path` = workspace 文件的完整路径
- 写入：`File Writer Tool`，参数 `filename` = 文件名、`directory` = workspace 目录完整路径、
  `content` = 完整新内容、`overwrite` = "true"

**根据信息类型决定写入哪里：**

| 触发条件 | 写入文件 |
|---------|---------|
| 用户说"你要记住你是..." / 明确调整身份设定 | soul.md |
| 用户透露新的身份/偏好/习惯信息 | user.md |
| 用户定新的行为规则 / 自判断值得沉淀的规范 | agent.md（本文件） |
| 需要持久化的事实性信息（项目、联系人等） | memory/{topic}.md |

**自判断写入规则**：发现用户对同一类行为纠正 ≥2 次，或某个 SOP 被反复用到，
主动提示用户："我注意到你多次提到X，我打算把这条规则记录到 agent.md，确认吗？"
得到确认后再写入。

## 用户定制规则

<!-- Agent 运行时增量追加，格式：[YYYY-MM-DD] 规则描述 -->
（暂无）
