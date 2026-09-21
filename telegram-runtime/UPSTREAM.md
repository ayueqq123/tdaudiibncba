# Upstream: telemirror

- 上游仓库: https://github.com/khoben/telemirror
- 基线提交: `19cf3acee1003191b7a30e337ee6cab95e59c2f9`
- 引入方式: `git subtree add --prefix=telegram-runtime telemirror-upstream 19cf3ace... --squash`
- 许可证: GPL-3.0(见本目录 `LICENSE`)。本子树整体为 GPL 派生作品。

## 升级上游

```bash
git subtree pull --prefix=telegram-runtime telemirror-upstream <new-commit-sha> --squash \
  -m "Merge telemirror upstream <sha>"
```

升级 Telethon 版本时,必须回归 `_patch`、话题映射、实体格式、相册聚合与发送返回值
(架构文档 §3、§4)。

## 已知上游问题(静态阅读,批次 2 前回归确认)

| 位置 | 问题 |
| --- | --- |
| `telemirror/mirroring.py` `delete_message()` | 删除异常仍清理映射;循环变量 `message_ids` 覆盖输入参数,源/目标 ID 混用 |
| `telemirror/mirroring.py` `EventProcessor` | 遍历目标直接发送,异常只记日志;单目标结果不可持久化 |
| `main.py` 健康端点 | 恒返回 204,与账号连接状态无关 |
| `config.py` | 导入时读环境变量/YAML,配置类型有导入副作用 |

## 平台补丁登记

| 日期 | 补丁 | 说明 |
| --- | --- | --- |
| (暂无) | | |
