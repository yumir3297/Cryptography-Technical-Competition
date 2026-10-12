# 仓库内容与整理记录

整理开始于 2026-10-11，收尾验证于 2026-10-12。GitHub 当前目录面向比赛软件开发：`competition/` 保存安全核心、固定场景、签名模拟工具、回归、交接及模拟证据；`system_dev/v26/` 保存运行所需消息契约、Schema、开发校验清单与公开编码向量；`.github/workflows/` 只运行比赛检查。

论文正文、完整研究代码、局部研究模型、正式研究实验/结果、研究 ZIP、研究工作流及研究分支快照已经归档到项目本地的 `local-research-archive/20261011-repository-cleanup/`。该目录位于 Git 工作区之外。归档包括完整 Git bundle、四个线上分支 ZIP、含未提交材料的工作区快照和逐文件 SHA-256 清单。使用普通提交整理当前目录，不重写历史；旧提交仍可追溯。

比赛代码曾依赖研究目录。实际需要的 16 个基础模块迁入 [support/](competition/support/README.md)，模块来源和迁移摘要见 [provenance.json](competition/support/provenance.json)。迁移只调整导入路径、职责说明和仓库根路径的获取；比赛核心守卫与状态行为不因此重新设计。

既有证据文件及 W manifest 保留原字节和原构建身份。源码摘要因路径迁移而改变；历史证据通过记录的 Git 提交核对，不改成当前构建结果。新的比赛回归、目录检查和演示证据独立记录于 `competition/evidence/repository-cleanup-20261011/`。

两个线上研究分支归档后移除；`main` 和比赛开发分支发布整理后的同一内容。本地归档保留原研究 refs。GitHub 历史提交及既往 Actions 记录保留来源身份，此次目录整理不抹除历史。

## 整理验证

- [归档核对](competition/evidence/repository-cleanup-20261011/archive-check.json)：2,429 个原工作区文件及四分支快照、完整 Git bundle 保留并核对摘要。
- [迁移语义核对](competition/evidence/repository-cleanup-20261011/migration-behavior-check.json)：16 个支持模块与 44 个比赛运行/测试模块，去除导入路径和文档字符串差异后 Python AST 一致。
- [比赛回归](competition/evidence/repository-cleanup-20261011/regression-report.json)：全部 124 个收集到的测试得到唯一通过记录；中断前 115 项，续跑剩余 9 项，分别保存日志。
- [当前目录与材料](competition/evidence/repository-cleanup-20261011/materials-check.json)：当前依赖、文档链接、11 份本地交接副本和原 W 证据文件核对。
- [消息与编码检查](system_dev/v26/verification_report.json)：371 项 Python 检查、70 项 Node 字节/密码交叉核对。
- [既有 W 历史核验](competition/evidence/cleanup-protocol-final-20261011-w-verification.json)和[同 ID 历史核验](competition/evidence/cleanup-protocol-final-20261011-same-oid-verification.json)：外部 manifest pin、原签名与账对应通过；原源码按记录提交及被摘要精确确认的 Windows CRLF 检出字节核对。

- [整理后三场景正常路径](competition/evidence/repository-cleanup-20261011/three-profile-normal/report.json)：工业、付款、医疗各自一次接受/attempt/发送/模拟效果/结算，查询再认证及重复结算不增效果；[独立核验](competition/evidence/repository-cleanup-20261011/three-profile-normal/verification.json) 724 项通过。源码构建 a034821，外部 manifest pin 为 `9782b1a4ac5eba26edb984afb63edb508c5964f7df90d0021d0cab9c3533fcf0`。
