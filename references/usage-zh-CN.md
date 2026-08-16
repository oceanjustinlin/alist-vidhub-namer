# AList Infuse + VidHub 命名助手

这是一个可分享的 Codex Skill，用来扫描 AList 媒体目录、生成命名和目录组织计划、通过用户自备的 TMDB Token 快速生成候选，并在人工确认映射后执行可回滚的重命名与精确目录移动。默认不会修改远端文件；没有 TMDB Token 时自动降级为本地文件名解析。

## 推荐命名

二级目录指 `Movies/` 或 `TV Shows/` 下面的影片/剧集目录。Skill 会提供两个选项：

- `中文名 + 规范标题`：中文提问时默认，例如 `盗梦空间 Inception (2010) {tmdb-27205}`。
- `仅规范标题`：英文提问时默认，例如 `Inception (2010) {tmdb-27205}`。

用户明确选择时始终以用户选择为准。这个选项只影响二级目录；视频文件名仍使用规范标题。中英文名称相同时不重复，没有核验过中文名称时不猜测。

电影：

```text
Movies/
  [中文名 ]规范标题 (上映年) {tmdb-电影ID}/
    规范标题.上映年.{tmdb-电影ID}.分辨率.片源.视频编码.音频编码.ext
```

完整标准要求在所确认的媒体根目录下设独立顶层分类目录：电影用 `Movies/`，电视剧用 `TV Shows/`。不要把电影目录与剧集目录直接混放在来源根目录。

示例：

```text
Movies/
  盗梦空间 Inception (2010) {tmdb-27205}/
    Inception.2010.{tmdb-27205}.1080p.BluRay.x264.DTS.mkv
    Inception.2010.{tmdb-27205}.1080p.BluRay.x264.DTS.zh-CN.srt
```

电视剧：

```text
TV Shows/
  [中文名 ]规范剧集标题 (首播年) {tmdb-剧集ID}/
    Season 01/
      剧集标题.S01E01.集标题.分辨率.片源.视频编码.音频编码.ext
```

剧集的 TMDB ID 和首播年默认放在剧集目录和本地 JSON 计划中，不强制写入每个单集文件名。单集依靠 `剧名 + SxxEyy` 匹配。特别篇使用 `Season 00` 和 `S00Eyy`；迷你剧、动漫从 `Season 01` 开始。

字幕必须与视频完整文件名同源，只在结尾增加语言：

```text
Series.Title.S01E01.1080p.WEB-DL.mkv
Series.Title.S01E01.1080p.WEB-DL.zh-CN.srt
```

## 使用流程

推荐在 AList 管理后台创建临时低权限用户：

- 基本路径设置为测试根目录的上一级。
- 只开放浏览/列出、重命名，以及在确认根目录内新建分类目录和移动所需的权限。
- 测试目录在该用户视角下必须是 `/Canary` 之类的非根路径，不能是 `/`。
- 测试完成后禁用临时用户。

不要把密码或 Token 写进聊天、命令参数、计划文件或社交媒体。由用户在自己的终端运行：

```bash
export ALIST_URL='https://alist.example.test'
export ALIST_USERNAME='codex-canary'
python3 scripts/alist_vidhub_namer.py login --token-file work/alist-canary.token
export ALIST_TOKEN_FILE="$PWD/work/alist-canary.token"
```

命令会安全提示输入密码，并创建只有当前用户可读的临时 Token 文件。局域网 HTTP 仍是明文传输，条件允许时使用 HTTPS。

如需快速 TMDB 匹配，每个用户都应在 `https://www.themoviedb.org/settings/api` 注册自己的 API Read Access Token，并阅读当前 TMDB API 条款。不要共享作者 Token。由用户在自己的终端运行：

```bash
python3 scripts/alist_vidhub_namer.py tmdb-setup \
  --token-file work/tmdb.token \
  --accept-terms
export TMDB_TOKEN_FILE="$PWD/work/tmdb.token"
python3 scripts/alist_vidhub_namer.py tmdb-check
```

`tmdb-setup` 会隐藏输入、先验证凭据，再创建权限为 `0600` 的文件。Token 不会写入计划、CSV 或重命名日志。TMDB 条款目前对 API 与 AI/LLM 的结合有限制；BYOK 是用户明确选择，不代表 Skill 作者代替用户取得授权。商业使用需要另行联系 TMDB。

先检查和生成计划，均为只读：

```bash
python3 scripts/alist_vidhub_namer.py check --path '/Canary'

python3 scripts/alist_vidhub_namer.py plan \
  --path '/Canary' \
  --kind auto \
  --resolver auto \
  --output work/media-plan.json \
  --csv work/media-plan.csv
```

配置 Token 后，`--resolver auto` 会使用本地固定契约调用 TMDB；没有 Token 时只做本地解析。也可用 `--resolver none` 禁止 TMDB 网络访问，或用 `--resolver tmdb` 要求必须使用 TMDB。候选会显示建议文件名、TMDB ID 和直达链接，但仍保持 `review`，等待用户确认。

## 已处理状态与快速过滤

Skill 默认把处理状态记录在本地 SQLite：

```text
work/alist-vidhub-state.sqlite
```

它不写入 AList 挂载、不保存 Token，也不能随 Skill 分享，因为其中包含用户的媒体路径和处理历史。初始化和查看状态：

```bash
python3 scripts/alist_vidhub_namer.py state-init
python3 scripts/alist_vidhub_namer.py state-status
```

混合目录先运行快速待处理报告；默认不访问 TMDB：

```bash
python3 scripts/alist_vidhub_namer.py pending-report \
  --path '/MediaLibrary/Movies' \
  --resolver none \
  --output work/pending.json \
  --csv work/pending.csv
```

默认只输出 `ready`、`review`、`conflict`、`needs_recheck`、`changed_since_processed`、`moved_externally` 和 `rolled_back`。`processed_current` 会被快速过滤；增加 `--include-processed` 才输出完整清单。

状态数据库版本、命名规则版本和 Skill 发布版本彼此独立。只有相关命名规则升级才会产生 `needs_recheck`，普通 Skill 升级不会让全库重新处理。TMDB ID 不作为文件唯一键，因此同一电影的 1080p、4K、导演剪辑版可以分别记录。

既有用户可按时间顺序从日志重建一个全新账本：

```bash
python3 scripts/alist_vidhub_namer.py state-rebuild \
  --journal work/video-journal.json \
  --journal work/folder-journal.json \
  --journal work/organize-journal.json \
  --output-db work/rebuilt-state.sqlite
```

输出数据库必须不存在。验证后，再将其作为统一的 `--state-db` 使用。日志是不可变审计与回滚依据，SQLite 只是可重建的快速索引。

二级目录改名必须使用独立计划。先创建只含 1–20 个精确映射的 JSON：

```json
[
  {
    "old_name": "Inception_2010",
    "new_name": "盗梦空间 Inception (2010) {tmdb-27205}"
  }
]
```

然后只读生成并预览：

```bash
python3 scripts/alist_vidhub_namer.py folder-plan \
  --path '/MediaLibrary/Movies' \
  --mapping-file work/folder-mapping.json \
  --output work/folder-plan.json

python3 scripts/alist_vidhub_namer.py apply --plan work/folder-plan.json
```

确认后使用独立日志执行，并传入精确文件夹数量：

```bash
python3 scripts/alist_vidhub_namer.py apply \
  --plan work/folder-plan.json \
  --journal work/folder-rename-journal.json \
  --execute \
  --confirm-root '/MediaLibrary/Movies' \
  --confirm-folder-count 1
```

如果视频文件和父文件夹都改过名，需要恢复时先回滚文件夹日志，再回滚视频日志；否则视频日志记录的旧路径尚未恢复。

如影片文件夹目前直接位于来源根目录，先用独立组织计划沉淀完整 `Movies/` 层级。每个 `--folder` 都必须是根目录下已确认的精确名称，最多 20 个：

```bash
python3 scripts/alist_vidhub_namer.py organize-plan \
  --path '/MediaLibrary/Incoming' \
  --destination 'Movies' \
  --folder '盗梦空间 Inception (2010) {tmdb-27205}' \
  --output work/movies-organize-plan.json

python3 scripts/alist_vidhub_namer.py organize-apply \
  --plan work/movies-organize-plan.json
```

预览无误后，确认精确根路径和文件夹数量再执行：

```bash
python3 scripts/alist_vidhub_namer.py organize-apply \
  --plan work/movies-organize-plan.json \
  --journal work/movies-organize-journal.json \
  --execute \
  --confirm-root '/MediaLibrary/Incoming' \
  --confirm-folder-count 1
```

脚本只在目标不存在时新建 `Movies`，并逐个移动文件夹、逐项落日志。需要恢复时先预览：

```bash
python3 scripts/alist_vidhub_namer.py organize-rollback \
  --journal work/movies-organize-journal.json
```

确认后增加 `--execute --confirm-root '/MediaLibrary/Incoming'`。回滚会把影片目录移回原处，但不会删除空的 `Movies`；Skill 永远不调用删除接口。若三层操作都做过，恢复顺序为：先组织移动，再二级目录名，最后视频文件名。

用户确认 API 候选或其他可靠来源后，批准一条：

```bash
python3 scripts/alist_vidhub_namer.py approve \
  --plan work/media-plan.json \
  --old-path '/Canary/Inception_2010_1080p.mkv' \
  --new-name 'Inception.2010.{tmdb-27205}.1080p.mkv' \
  --tmdb-id 27205 \
  --note '人工核验' \
  --output work/media-plan.approved.json
```

电视剧同样可以记录剧集 ID，但单集目标名不必带 ID：

```bash
python3 scripts/alist_vidhub_namer.py approve \
  --plan work/tv-plan.json \
  --old-path '/Canary/Show 2021 S1E1.mkv' \
  --new-name 'Show.S01E01.mkv' \
  --tmdb-id 12345 \
  --note '剧集 ID 已人工核验' \
  --output work/tv-plan.approved.json
```

确认候选后，用 `select` 精确选择视频（每批最多 20 个）；不要自动取列表前几个。字幕会自动随对应视频进入灰度计划：

```bash
python3 scripts/alist_vidhub_namer.py select \
  --plan work/media-plan.approved.json \
  --old-path '/Canary/Movie-A.mkv' \
  --old-path '/Canary/Movie-B.mkv' \
  --old-path '/Canary/Movie-C.mkv' \
  --old-path '/Canary/Movie-D.mkv' \
  --old-path '/Canary/Movie-E.mkv' \
  --expected-videos 5 \
  --output work/media-canary-5.json
```

先预览；只有在确认根目录、文件数量和映射后才执行：

```bash
python3 scripts/alist_vidhub_namer.py apply --plan work/media-canary-5.json

python3 scripts/alist_vidhub_namer.py apply \
  --plan work/media-canary-5.json \
  --journal work/media-rename-journal.json \
  --execute \
  --confirm-root '/Canary' \
  --confirm-video-count 5
```

需要恢复时先预览，再明确执行：

```bash
python3 scripts/alist_vidhub_namer.py rollback --journal work/media-rename-journal.json
```

VidHub 验证每个条目后，删除 `work/alist-canary.token`，并在 AList 中禁用临时用户或撤销会话。

完整规则见同目录的 `naming.md`，AList API 与安全边界见 `api-and-safety.md`，TMDB 本地调用契约见 `tmdb-api.md`。
