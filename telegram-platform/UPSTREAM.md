# Upstream: fastapi-best-architecture (FBA) + fba-ui

- 后端上游: https://github.com/fastapi-practices/fastapi-best-architecture
- 后端基线: `123a44aed02daf5ea60d2a7469625c933d3bb759`
- 前端上游: https://github.com/fastapi-practices/fastapi-best-architecture-ui
- 前端基线: `9f4040ce6b86ef414d9b47a243661049f0dd945f`(vendor 在 `web/` 子目录)
- 引入方式: `git subtree add --squash`(两个 remote 分别对应 `fba-upstream` / `fba-ui-upstream`)
- 许可证: MIT(见 `LICENSE` 与 `web/LICENSE`)。

## 升级上游

```bash
git subtree pull --prefix=telegram-platform fba-upstream <new-commit-sha> --squash \
  -m "Merge FBA upstream <sha>"
git subtree pull --prefix=telegram-platform/web fba-ui-upstream <new-commit-sha> --squash \
  -m "Merge fba-ui upstream <sha>"
```

注意:`web/` 是嵌套子树,单独跟踪 fba-ui;拉 FBA 上游不会动它。

## 平台补丁登记

| 日期 | 补丁 | 说明 |
| --- | --- | --- |
| (暂无) | | |
