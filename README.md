# AR · 人才与机会

## Kamal 生产部署

仅部署 `portal_server.py`（候选人/校友门户），**不对外开放本地中控服务**。配置见 `config/deploy.yml`，`main` 推送先运行测试；部署默认关闭。首次部署需要从 Actions 手动运行一次 `Test and deploy`，选择 `setup: true`；核验成功后把**仓库级** Actions Variable `DEPLOY_ENABLED` 设为 `true`，之后推送 `main` 才会自动 `kamal deploy`。首次 setup 会安装 Docker、启动 PostgreSQL accessory 和 Kamal proxy，并接管目标机 80/443；先确认端口未被其他服务占用。目标机 `devops` 需有免密 sudo 和 Docker 权限；不要改 sshd/ufw。

上线前配置 GitHub 仓库的 `production` Environment（可设人工批准规则），其中设置：

- 固定公开域名为 `match.miracleplus.com`：DNS A 记录需指向这台服务器对外的 IP；Kamal proxy 自动申请 HTTPS 证书。OAuth 应用 Redirect URI 为 `https://match.miracleplus.com/oauth/callback`。
- Secrets `DEPLOY_SSH_PRIVATE_KEY`、`DEPLOY_SSH_CERT`：建议为 CI 单独签发的私钥和对应的 90 天 SSH 用户证书；**不要把个人私钥贴到聊天、提交到仓库或发给他人**。证书到期前重签并更新 Environment Secret。CI 会在标准 `~/.ssh/config` 中配置服务器别名。
- Secret `DEPLOY_SSH_KNOWN_HOSTS`：由运维通过可信渠道确认的跳板机 `112.126.91.159:20202` 和目标机 `172.20.188.97:22` 主机公钥记录。不要使用未核实的 `ssh-keyscan` 作为信任依据。
- Secrets `POSTGRES_PASSWORD`（Kamal `db` accessory 初始化时使用，部署后不要随意更换）、`AR_CONFIG_JSON`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`MP_OAUTH_CLIENT_ID`、`MP_OAUTH_CLIENT_SECRET`、`CANDIDATE_AI_BASE_URL`、`CANDIDATE_AI_MODEL`、`CANDIDATE_AI_API_KEY`。CI 从 `AR_CONFIG_JSON` 生成 `ar.json` 并打包进镜像；本机部署使用项目目录的 `ar.json`。容器运行期配置（数据库 URL、飞书与 OAuth 凭据、AI 服务）直接明文写在 `config/deploy.yml` 的 `env.clear`，`db` accessory 的 `POSTGRES_PASSWORD` 同样在其中；`.kamal/secrets` 只保留动态获取的 `KAMAL_REGISTRY_PASSWORD`（GHCR 登录）。**因为 `config/deploy.yml` 含明文凭据，仓库必须保持私有，且不要把它贴到聊天或工单里。**

CI 通过 `GITHUB_TOKEN` 登录 GHCR；首次部署前确认仓库有 package 发布权限，目标服务器可访问 GHCR、Docker Hub 与 Let's Encrypt。该服务器的 Docker daemon 使用本机 sing-box 代理 `http://127.0.0.1:17891` 访问海外镜像；容器内不配置该代理。Kamal accessory 将 PostgreSQL 数据持久化在目标机 Kamal 数据目录的 `alumni-talent-db/postgres-data`；后续部署不会重建或升级数据库。旧 SQLite 数据升级前先备份；如需迁移，先启动 accessory、导入并核对数据，再启动门户，不要对已有数据重复运行迁移。请单独设置 PostgreSQL 定期备份和恢复演练；Kamal 卷持久化不等于备份。部署后核验 `https://match.miracleplus.com/health` 和实际 OAuth 登录；`/up` 仅用于 Kamal proxy 就绪探测。会话在进程内，滚动部署会使已登录用户重新登录；目前没有部署回滚时的数据回滚或备份自动化。
### 本机手动部署

本机安装 Kamal 2.12.0，并在 `~/.ssh/config` 配置 `mp-jump` 和 `alumni-talent` 两个别名、目标用户 `devops`、跳板机以及密钥和证书。Net::SSH 需要在两个别名下都明确设置 `CertificateFile`，例如 `~/.ssh/id_ed25519-cert.pub`；文件名按本机证书调整。`.kamal/secrets` 只需 `KAMAL_REGISTRY_PASSWORD`（来自 shell 环境或 `.env` 的 `gh auth token`），其余运行时凭据已在 `config/deploy.yml` 中；项目目录的 `ar.json` 会打包进镜像。

```sh
kamal deploy
```

首次部署使用 `kamal setup`。

在本地查看两张 AR 表中的候选人与校友 JD，并进行 AI 打标签、初筛与匹配评估。原始收集表仍用于核对及管理员导入，不进入核心工作台。

## 新电脑第一次使用

需要 **Windows 10/11**、**Python 3.10 或更新版本**，以及已开通相应权限的飞书应用。不需要安装 Conda。

1. 下载完整项目，双击 **`首次配置AR.cmd`**。
2. 脚本会打开凭据文件。在文件顶部填写同一个飞书应用的 **App ID** 和 **App Secret**，保存并关闭记事本。
3. 如果这台电脑还没有 `ar.json`，按提示粘贴一次目标**飞书多维表格链接**。支持 `/base/` 链接，以及知识库中的 `/wiki/` 多维表格链接；后者需要给应用开通「查看知识库」API 权限。
4. 等待「首次配置完成」，然后双击 **`打开AR网页.cmd`**。

首次配置脚本会自动创建项目内的 Python 环境、安装依赖、识别并验证目标表、保存飞书凭据、下载记录和附件、生成网页数据。本地会同步五张表，核心工作台只展示 `AR-候选人-jiakai` 和 `AR-校友侧-jiakai`；旧版存档表不纳入新库配置。配置失败会显示原因；修正后重新运行即可。

## 平时使用

直接双击 **`打开AR网页.cmd`**。网页只在本机 `127.0.0.1:38479` 运行。要获取飞书新数据，点击网页中的「检查飞书更新」；没有变化时不会改动本地快照。

AI 服务的 API 地址、Key、模型和提示词在网页的「AI 管理」中另行设置。保存前可点击「测试连接」，用当前填写的配置发送一条不含候选人或 JD 数据的测试消息。候选人与 JD 的标签规则也在那里编辑。候选人批量打标签采用有上限的并发队列，默认同时处理 3 份，可在「AI 管理」调整为 1–10；停止后不再发出新请求，已发出的请求可能仍在服务端完成。深度评估不会自动推荐；评估完成后，无论星级，管理员都可逐人点击「确认推荐」，也可勾选多人点击页面上方的「确认推荐所选」。当前不会自动发送机器人消息。

「AI 管理」下方的分析记录从启用此功能后的新请求开始保存，包含发起时间、模型、实际发送的系统提示词与资料、模型原始回复和错误信息，便于核对提示词。记录保存在 PostgreSQL，其中可能含简历文字；请限制数据库访问并按需备份。

### PostgreSQL 配置与旧数据迁移

中控与门户共用同一个 PostgreSQL 数据库。先安装 `requirements.txt`，建立专用数据库和账号，并在**两个服务**的运行环境设置 `DATABASE_URL=postgresql://用户:密码@主机:5432/数据库`；连接失败时服务不会启动。首次启动会创建 `ai_calls`、`recommendations`、`feedback_events`、`portal_records`、`portal_field_schemas` 表。不要把连接串提交到 Git；部署时确保中控与门户都能读取此环境变量。

门户设置 `AR_LOCAL_PRIMARY=1` 后，PostgreSQL 是候选人和校友业务资料的主数据库。候选人资料、推荐开关、企业资料和 JD 保存时先写 PostgreSQL 并立即返回，事务提交后会立即唤醒后台线程同步飞书；空闲时线程休眠，不持续轮询。同一条记录短时间内的连续修改会合并成一次待同步更新。同步失败不会丢失本地数据，系统会按指数退避自动重试，最长间隔 5 分钟；另有 60 秒兜底扫描，用于恢复进程重启或极端情况下错过的内存通知。后台每 5 分钟也会从飞书拉取一次两张 AR 输出表；若本地记录仍有待同步修改，飞书旧值不会覆盖本地新值。

`/health` 的 `local_primary` 表示本地主存储是否启用，`sync_queue` 会报告 `synced`、`pending` 和 `failed` 数量。需要临时回退到原来的飞书直写方式时可将 `AR_LOCAL_PRIMARY` 设为 `0` 并重启服务。注册绑定和附件上传仍需立即调用飞书，以完成账号唯一性校验并取得飞书附件 token；成功后同样会镜像进 PostgreSQL。普通资料保存和推荐开关不再等待飞书。

升级前先停止两个服务、备份数据库和原有的 `ai_history.sqlite3`、`recommendations.sqlite3`。在空的目标库中设置 `DATABASE_URL` 后运行 `python migrate_sqlite.py`；核对返回的每表行数，再启动服务。导入脚本不会删除 SQLite 文件；目标表已有数据时拒绝导入。切勿在已开始写入 PostgreSQL 的库上重复运行迁移。OAuth 的账户数据仍在飞书，授权状态不依赖数据库；服务重启后的现有登录会话仍需重新登录。

## 候选人端与校友端

### 使用 mp 账号登录（可选）

在 mp 的 accelerator 站「OAuth 应用」创建授权码应用，Redirect URI 填写 `<AR_PORTAL_ORIGIN>/oauth/callback`（公网必须为 HTTPS），scope 使用 `public`。启动门户服务前设置：

```text
AR_PORTAL_ORIGIN=https://你的门户域名
MP_OAUTH_URL=https://build.miracleplus.com
MP_OAUTH_CLIENT_ID=mp 应用的 Client ID
MP_OAUTH_CLIENT_SECRET=mp 应用的 Client Secret
```

配置后候选人端使用 mp 账号登录，校友端要求 mp 账号具有 `founder_company_hr` 角色；两个入口不再接受本地手机号密码注册/登录。首次登录要求 mp UserInfo 提供有效的中国大陆手机号。若该手机号在对应端表中唯一匹配到一条尚未绑定 MP ID 的旧账户，系统会将其 `AR_MP用户ID` 更新为 mp UserInfo 的稳定 `sub` 后登录；如果手机号匹配多条记录，或目标记录已绑定其他 MP ID，则拒绝自动绑定，需管理员核实。不要把 Client Secret 提交到 Git 或暴露给浏览器。未配置 OAuth 时保留原有本地登录方式。
授权页打开后须在 10 分钟内完成；重启门户不会使尚未过期的授权失效，但已签发的门户登录会话保存在进程内，重启后需重新登录。更换 Client Secret 也会使未完成的授权失效。

候选人简历由 AI 自动识别后写入 PostgreSQL 草稿，用户可检查并补齐必填项；确认保存后由后台同步到飞书。已提交过简历的候选人再次登录会直接进入资料编辑页，并可继续修改资料。

首次配置完成后，分别双击 **`打开候选人端.cmd`** 和 **`打开校友端.cmd`**。两个页面由独立的本地服务提供（`127.0.0.1:38480`），不会开放中控的 AI 设置或数据管理接口。首次启动会自动在 **`AR-候选人-jiakai`** 和 **`AR-校友侧-jiakai`** 中补齐 `AR_` 字段；原始候选人表、校友 JD 收集表和校友流转简历表只读。

两端使用手机号和至少 5 位密码注册。密码以加盐摘要形式保存在对应的 AR 表中。候选人可以编辑资料、上传简历并开关后续推荐；校友首次登录时必须填写企业名称、姓名和职务，没有 JD 时会继续打开新增 JD 窗口。企业信息分别写入飞书的 `公司名称（对外展示的名称）`、`填写人姓名`、`填写人职务` 字段，并同步到所属 JD 行；旧字段 `填写人与职位` 仅保留历史数据。中控 AI 评估只保存评分，管理员在对应候选人行点击「确认推荐」后，校友端才会看到该候选人；测试阶段不设星级门槛。数据中心按 JD 展示推荐人数、感兴趣和录用进展。每组候选人和 JD 的星级、理由、感兴趣、面试和未录用记录保存在 PostgreSQL。有用的业务结果同时写入飞书：候选人表的 `AR_已推荐JD`、`AR_录用JD`，校友表每条 JD 的 `AR_已录用候选人`。每条 JD 单独占一行，使用 `AR_账户ID` 关联校友账号，并填写公司名称和联系人手机号。启动校友端时会把本地已有结果补写到两张 AR 表；同步失败时可修复飞书连接后重启校友端重试。旧版本写在 AR 校友表中的推荐过程行会复制到本地数据库，旧行暂时保留。换电脑部署时需迁移 PostgreSQL 数据，否则会丢失过程和未同步的结果。

中控「AI 匹配」会按候选人和当前 JD 显示已推荐次数，以及尚未反馈、感兴趣、未录用或录用等状态。校友一旦反馈“不感兴趣”，该候选人在这条 JD 下无法再次勾选或确认推荐；服务端也会阻止重复请求。修改 JD 正文不会清除这条限制。过程反馈只保存在本地数据库。

在用户端提交或修改资料后，到中控点击 **「检查飞书更新」**，新简历和 JD 即可进入本地匹配视图。既有来源表的资料不会让新注册者仅凭手机号自行认领；管理员核实账户归属、同步最新来源数据后，可在项目目录运行 `python portal_import.py candidate 已核实手机号` 或 `python portal_import.py alumni 已核实手机号`，将匹配的来源记录复制进对应的 AR 表。候选人表单依照飞书字段生成，已上传附件可删除后替换；姓名、简历、求职意向、到岗信息、招聘信息来源及联系同意为必填。

两个新页面当前默认只允许在运行服务的电脑上访问。若要让候选人和校友从外网登录，需要另外部署带 HTTPS 的服务，并加入手机号验证；只靠填写手机号无法证明号码归属。部署时可通过 `AR_PORTAL_BIND`、`AR_PORTAL_PORT` 和 `AR_PORTAL_ORIGIN` 配置独立门户服务，不应将本地中控服务暴露到外网。

## 常见问题

- **找不到 Python**：安装 Python 3.10 或更新版本，再运行 `首次配置AR.cmd`。
- **`app secret invalid`**：检查填写的 App ID 和 App Secret 是否来自同一个飞书应用、是否为当前有效密钥。
- **`91403 Forbidden`**：在目标多维表格中把该应用添加为文档应用，并授予读取权限；飞书应用的 API 权限也需要已开通。
- **简历文字没有被读取**：脚本会安装 PDF 读取依赖；图片扫描版 PDF 仍需先做文字识别。

`setup-feishu-credentials.ps1`、`ar.json`、`.venv/`、`downloads/` 和生成的网页数据都只保存在本机，并已被 Git 忽略。不要把 App Secret 发到聊天中或提交到仓库。

## 命令行（可选）

首次配置完成后，在项目目录的 PowerShell 中可以运行：

```powershell
.\.venv\Scripts\python.exe ar.py check
.\.venv\Scripts\python.exe ar.py pull --all-tables
.\.venv\Scripts\python.exe ar.py sync
```

`ar.py` 还支持 `set`、`create` 和 `attach`，但必须用 `--table candidate_output` 或 `--table alumni_output` 指定 AR 输出表；原始三张表禁止写入。可用 `.\.venv\Scripts\python.exe ar.py --help` 查看。通常只需使用网页，无须手动运行这些命令。
