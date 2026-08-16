# AList Infuse + VidHub 命名助手

[English](README.md)

> 一个可用于 CLI 或 Agent 的工具与 Skill：为 Infuse 和 VidHub 生成可审阅的 AList 媒体命名与目录整理计划。它默认只扫描、不修改远端；只有在用户明确确认后，才会以小批次执行原地操作。

## 这是什么

这个 Skill 用于把 AList 挂载的媒体库整理成更适合 Infuse 和 VidHub 抓取的命名与目录结构。它可以：

- 扫描指定媒体路径，生成只读 JSON 与 CSV 计划；
- 解析本地文件名，或在用户提供自己的 TMDB Token 后补充只读候选；
- 规范电影、剧集、特别篇和字幕文件名；
- 通过精确、限量的目录移动建立 `Movies/` 或 `TV Shows/` 层级；
- 使用本地 SQLite 账本记录已处理路径，并从日志重建账本；
- 预览、执行与回滚已批准的计划。

脚本只会调用列目录、重命名、新建直接子目录，以及单文件夹移动所需的 AList API。它不会下载媒体、直连网盘提供商 API、删除、上传、复制或递归移动文件。

## 当前状态

仓库已包含初始实现和文档。但当前提交中有两项文件名解析测试失败，问题集中在去除中文字幕或发布组备注。测试通过、并在你自己的 AList 完成灰度验证前，请不要把远端修改流程当作可发布版本。

## 使用前

- 在 AList 创建临时低权限账户，把根路径设为一个小范围测试目录的上一级，例如 `/Canary` 的父目录。
- 尽量使用 HTTPS。HTTP 会以明文传输凭据和 Token。
- 将 Token、计划、日志和本地账本放在被忽略的 `work/` 目录。它们可能包含媒体路径与操作历史。
- 如需 TMDB 候选，使用你自己的 Read Access Token，并先阅读当前 TMDB 条款。这个 Skill 不内置或共享任何 TMDB 凭据。
- 先跑 1–20 项灰度批次。检查 AList 结果后，只重新扫描 Infuse 或 VidHub 中受影响的文件源，再扩大范围。

## 快速开始

克隆仓库后，可从终端、脚本或 Agent harness 运行 CLI。你的 harness 支持 Skill 指令时，请阅读 [SKILL.md](SKILL.md)。

CLI 只使用 Python 标准库。在仓库根目录运行：

```bash
python3 scripts/alist_vidhub_namer.py --help
```

用交互方式创建临时 AList Token，避免把密码写入 Shell 历史：

```bash
export ALIST_URL='https://alist.example.test'
export ALIST_USERNAME='alist-canary'
python3 scripts/alist_vidhub_namer.py login --token-file work/alist-canary.token
export ALIST_TOKEN_FILE="$PWD/work/alist-canary.token"
```

先检查目标，再生成只读计划：

```bash
python3 scripts/alist_vidhub_namer.py check --path '/Canary'

python3 scripts/alist_vidhub_namer.py plan \
  --path '/Canary' \
  --kind auto \
  --resolver none \
  --output work/media-plan.json \
  --csv work/media-plan.csv
```

配置用户自备 TMDB Token 后可使用 `--resolver auto`。没有 Token 时它会回退到本地解析；需要完全禁止 TMDB 网络请求时使用 `--resolver none`。

## 安全流程

| 阶段 | 你的操作 | 是否改动远端 |
| --- | --- | --- |
| 1. 连接 | 创建低权限账户并运行 `check`。 | 否 |
| 2. 计划 | 运行 `plan`、`pending-report`、`folder-plan` 或 `organize-plan`。 | 否 |
| 3. 审阅 | 检查每个映射，处理 `review` 与 `conflict`。 | 否 |
| 4. 灰度 | 精确选择 1–20 个视频，预览 `apply`，再明确确认根路径和数量。 | 仅 `--execute` 后 |
| 5. 验证 | 检查 AList，并在 Infuse 或 VidHub 重新扫描受影响的文件源。 | 否 |
| 6. 恢复 | 先预览 `rollback`，再明确执行。 | 仅 `--execute` 后 |

扫描、研究、审计或生成计划的请求都不等同于授权远端改名。脚本会拒绝对 `/` 修改；遇到过期源路径、目标冲突或认证错误会停止；每次成功修改后都会写入日志。

### 批量自动执行模式

在同一个个人媒体库反复处理时，用户可以每个会话选择一次这个模式，免除重复的逐项确认。只有身份唯一明确、计划没有目标冲突、实时目录结构符合计划、且置信度达到计划阈值时，Skill 才能自动批准并执行视频名或文件夹名改动。

该模式不会自动授权移入 `Movies/` 或 `TV Shows/` 的目录移动。执行 `organize-apply --execute` 前，用户仍需审阅本批所有待移动文件夹，并给出一次明确的批次确认。

## 命名结构

人工核验后，电影目录和文件名使用稳定的 TMDB ID：

```text
Movies/
  Inception (2010) {tmdb-27205}/
    Inception.2010.{tmdb-27205}.1080p.BluRay.x264.DTS.mkv
```

中文提问时，媒体目录可采用 `中文名 + 规范标题`：

```text
Movies/
  盗梦空间 Inception (2010) {tmdb-27205}/
```

电视剧单集使用剧名和集号。剧集 TMDB ID 与首播年保留在剧集目录和计划内，不必重复写进每个文件名：

```text
TV Shows/
  The Pitt (2025) {tmdb-12345}/
    Season 01/
      The.Pitt.S01E01.1080p.WEB-DL.mkv
      The.Pitt.S01E01.1080p.WEB-DL.zh-CN.srt
```

## 修改前后示例

以下示例保留了本地扫描到的文件名形态，但去掉了服务器和挂载路径。它们代表人工确认后的计划，不代表自动匹配；执行前仍要核验标题、年份、集号、语言和 TMDB ID。

### 电影目录与文件

```text
修改前
  [为所应为][1989][英语中字][1080P][780MB]/
    [为所应为].Do.the.Right.Thing.1989.BD.MiniSD-TLF.mkv

修改后
  Movies/为所应为 Do the Right Thing (1989) {tmdb-925}/
    Do.the.Right.Thing.1989.{tmdb-925}.BD.MiniSD-TLF.mkv
```

计划会去掉分享目录噪声、保留有用的发布标签，并加入已核验的电影 ID。配对字幕会使用完整目标视频名作为前缀，再保留原有语言后缀。

### 电视剧单集

```text
修改前
  先见之明.S01E01.HD1080P.YYeTs.中英双字.霸王龙压制组T-Rex.mp4

修改后
  The.OA.S01E01.1080p-YYeTs.mp4
```

计划会解析中文片名、去掉字幕和压制组噪声，并保留来源可佐证的发布组。剧集年份与 ID 放在剧集目录和计划中；单集保留剧名与规范化后的 `SxxEyy` 键。

### 目录整理

```text
修改前
  the vince staple show/

修改后
  TV Shows/The Vince Staples Show (2024) {tmdb-243861}/
```

计划会统一大小写，并加入已核验的年份和 ID。移动目录与重命名视频使用独立计划和日志。执行前分别审阅；需要恢复时按依赖的反向顺序回滚。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `check` | 读取 AList 版本、存储驱动与写入状态。 |
| `plan` | 递归生成只读媒体计划。 |
| `pending-report` | 过滤已经按当前规则版本处理过的路径。 |
| `tmdb-setup` / `tmdb-check` | 保存并校验用户自己的 TMDB Token。 |
| `approve` | 把一条人工核验映射写入计划副本。 |
| `select` | 从精确路径生成 1–20 个视频的灰度计划。 |
| `apply` / `rollback` | 预览或执行已批准的视频、文件夹改名计划，或恢复。 |
| `organize-plan` / `organize-apply` / `organize-rollback` | 计划、执行或回退移入 `Movies/`、`TV Shows/` 的精确目录移动。 |
| `state-init` / `state-status` / `state-rebuild` | 管理本地版本化处理账本。 |

完整操作约束请读 [SKILL.md](SKILL.md)。详细规则见 [AList API 安全说明](references/api-and-safety.md)、[命名规则](references/naming.md)、[TMDB 使用](references/tmdb-api.md)、[状态账本](references/state-ledger.md) 与 [中文示例](references/usage-zh-CN.md)。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## 许可证

仓库尚未提供许可证文件。在维护者添加开源许可证前，请不要假设代码可以被再分发或复用。
