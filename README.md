# Jarvis

Jarvis 是一套通用 Agent Skill 包：把可复用的工作方法放在扁平的 `<skill>/SKILL.md` 目录里，供 Cursor、Codex、Claude Code 等支持 [Agent Skills](https://agentskills.io/specification) 开放格式的本地宿主发现和使用。

本仓库只包含通用方法、脚本、模板和合成测试。个人笔记、健康记录、机器绝对路径和私人配置不属于这里；本地笔记库和敏感库仍由使用者自己保管。

## 包含的技能

默认安装 12 个有效技能。仓库里另外保留 2 个旧计划入口，仅在显式兼容时安装。

| 技能 | 作用 | 类别 |
| --- | --- | --- |
| `eli5` | 按读者背景解释复杂内容 | 指令 / 建议 lite |
| `brainstorming` | 把模糊想法收束为可讨论的设计 | 指令 / 建议 lite |
| `plan-plain` | 生成或解释可执行计划 | 指令 / 建议 lite |
| `grill-me` | 用户明确要求挑战想法时的入口 | 指令 / 建议 lite |
| `grilling` | 按决策依赖追问假设和风险 | 指令 / 建议 lite |
| `manual-qa-handoff` | 整理仍需人工检查的验收项 | 项目文件 / 按需 |
| `project-doc-organization` | 整理项目文档并减少重复 | 项目文件 / 按需 |
| `skill-writing` | 编写和审查 Skill 本身 | 项目文件 / 按需 |
| `knowledge-maintenance` | 维护项目知识索引（OKF-lite） | 本地工具 / 按需 |
| `life-knowledge` | 检查和维护本地个人知识库 | 本地工具 / 按需 |
| `memo-inbox` | 把明确要求记下的普通备忘写入本地笔记库 | 本地工具 / 按需 |
| `audio-transcribe` | 本地录音转写，必要时再翻译 | 本地工具 / 按需 |
| `make-dev-plan` | 旧名兼容，转到 `plan-plain` | 兼容，默认不装 |
| `plan-mode-plan-writer` | 旧名兼容，转到 `plan-plain` | 兼容，默认不装 |

新用户若只想先看指令型能力，可只安装上表中的 lite 5 项；当前安装器的默认集合是全部 12 个有效技能，而不是只装这 5 项。兼容别名不会因为源码存在就被默认安装。

本包不包含病程支持、情绪量表或其他健康追踪技能。

## 安装

先阅读你下载或克隆到的内容，再决定是否安装。不要默认执行从网络拿到的安装脚本，也不要在未审阅时改写 Agent 配置。

### 本地目录安装（Cursor / Codex / Claude Code）

在 Windows、macOS 或 Linux 上，安装器把本仓库中的技能目录链接到宿主扫描路径。Windows 使用 directory junction，macOS / Linux 使用符号链接。默认只写入用户级 `~/.agents/skills`（Cursor、Codex 等会扫描该目录）。Cursor 同时可能读取 Claude 目录，因此 Claude Code 入口需要显式打开，以免重复发现。

```powershell
# 预览默认 12 项（不改文件）
pwsh -File scripts/install-user.ps1 -Scope User -DryRun -Json

# 安装到 ~/.agents/skills
pwsh -File scripts/install-user.ps1 -Scope User

# 同时安装到 ~/.claude/skills（仅 User 作用域）
pwsh -File scripts/install-user.ps1 -Scope User -IncludeClaude

# 额外安装两个旧计划别名
pwsh -File scripts/install-user.ps1 -Scope User -IncludeCompat

# 安装到当前项目的 .agents/skills（不创建 .claude/skills）
pwsh -File scripts/install-user.ps1 -Scope Project -ProjectRoot <project>
```

安装器是幂等的：不会覆盖真实目录或指向其他 checkout 的链接；`-Remove` 只删除名单中名称且精确指向本 checkout 对应技能的有效链接；未知自建别名、冲突目标、真实目录和断链均保留，不按“目标在 checkout 内”推断所有权。普通安装不自动清理未知名称；冲突返回非零与 conflict 事件，不声称全部成功。若曾经用 `-IncludeCompat` 安装过别名，之后的默认安装不会剪掉这些仍指向本仓库的兼容链接。

默认集合和兼容名单见 `scripts/install-skills.json`。当前没有 lite / 工程 / 本地工具等额外命令开关；若只想装 lite 5 项，请审阅后手动链接对应目录，或等待后续安装配置。

安装后可用 `pwsh -File scripts/smoke.ps1 -Scope User` 检查链接。若安装时加了 `-IncludeCompat`，smoke 也要加同样的开关。

### 其他平台

- **ChatGPT 原生 Skills：** 符合资格的 Business / Enterprise / Edu / Healthcare 工作区可通过官方 Skills 界面上传或管理技能。这与 Codex 本地目录安装不是同一入口，也不能据此访问你的本机笔记库。上传前只打包需要的技能及其完整依赖，不要带入私人文件。
- **Qoder IDE / CLI：** 官方文档使用 `~/.qoder/skills` 与项目级 `.qoder/skills`。当前安装器没有 Qoder 目标；可先手工导入完整技能目录，并用无写入样例验证。IDE 与 CLI 对同名技能的优先级说明并不一致，首发请避免同名双装。
- **仅指令降级：** 如果宿主不能加载多文件技能，可以把单个 `SKILL.md` 作为说明使用，但脚本、kit 和 references 不会自动可用，也不能声称文件已写入本地。

官方说明（请以正文为准，本仓库未对所有平台做实测）：

- [Agent Skills 规范](https://agentskills.io/specification)
- [Skills in ChatGPT](https://help.openai.com/en/articles/20001066-skills-in-chatgpt)
- [Build skills（ChatGPT / Codex）](https://learn.chatgpt.com/docs/build-skills)
- [Cursor Agent Skills](https://cursor.com/docs/skills)
- [Claude Code Skills](https://code.claude.com/docs/en/skills)
- [Qoder IDE Skills](https://docs.qoder.com/extensions/skills)
- [Qoder CLI Skills](https://docs.qoder.com/cli/Skills)

## 本地工具的前置条件

指令型技能在对话里即可预览。下面这些能力还需要本机执行器和明确的数据路径；安装技能不会扫描你的个人数据。

- `memo-inbox`：Python 3（标准库即可）。普通库路径来自本机配置目录中的 `default-vault.json`（默认 `~/.config/alfred/`，以兼容已有指针；可用 `--config-dir` 或 `MEMO_CONFIG_DIR` 覆盖），或命令行显式传入。
- `audio-transcribe`：Python ≥ 3.11、`uv`、`ffmpeg`，以及脚本声明的转写依赖；首次使用可能下载模型。不要在无网或依赖缺失时声称已经转写完成。
- `life-knowledge`：随包 PowerShell kit（Windows 优先）。必须通过 `-VaultPath`、`LIFE_KNOWLEDGE_HOME` 或本机 profile 指定知识库，不会猜测某台机器上的默认路径。其他系统的完整运行仍待实测。
- `knowledge-maintenance`：Python 3 与仓库根目录的 `tools/okf-lite/`。只复制 `knowledge-maintenance/SKILL.md` 是不够的；本地链接安装可以定位本 checkout 中的工具。

## 校验

在本仓库根目录：

```powershell
pwsh -File scripts/validate.ps1
pwsh -File scripts/test-install-user.ps1
```

`validate.ps1` 会做嵌套审计、相对链接检查，并运行安装隔离测试、OKF-lite 单元测试，以及各技能自带的 Python / Pester 测试。缺少依赖时应如实标记，不要把跳过的测试说成通过。

## 许可

本仓库提取出的材料以 [MIT License](LICENSE) 授权，自有部分版权声明为 cty41；第三方部分保留各自版权与许可。部分通用方法最初从作者的 `tactics` 项目移植。`brainstorming` 为 obra/superpowers 的翻译改编，`eli5` 改编自 [DreambigOu/ELI5](https://github.com/DreambigOu/ELI5)，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。`life-knowledge/kit/LICENSE` 随 kit 保留。

个人笔记、健康记录和其他本地数据不适用本许可，也不得并入本仓库或随本仓库分发。
