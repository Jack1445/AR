# AR × 飞书多维表格

用本地命令读取和修改飞书多维表格。复制 `ar.example.json` 为 `ar.json`，将自己的多维表格链接填入 `base_url`，并在 `tables` 中填写三张表的 ID、名称和类型（当前候选人、历史候选人、JD）。可先运行 `python ar.py check` 查看可访问的数据表 ID。`ar.json` 仅保存在本机，不进入 Git。需要 Python 3.10 或更新版本。网页的一键同步使用 `keyring` 保存凭据；如果缺少，运行 `python -m pip install -r requirements.txt`。

## 本地网页

首次使用网页的“检查飞书更新”按钮前，在此前设置过飞书环境变量的 **Conda PowerShell** 中运行一次：

```powershell
python ar.py save-credentials
```

这会把 App ID 和 App Secret 存到当前 Windows 用户的**凭据管理器**，不会写进仓库或浏览器。若环境变量已失效，请按下方“准备”重新设置后再运行。不要把 App Secret 发到聊天里。

然后在资源管理器中双击项目根目录的 **`打开AR网页.cmd`**。脚本会启动只监听 `127.0.0.1:38479` 的本地服务，并用 Edge 或 Chrome 打开网页。首页显示三张表的汇总数字和候选人 → AI → 校友企业流程图；点击两侧节点或左侧导航可进入“人才与岗位一览”，继续搜索、查看完整字段和打开已下载附件。左侧固定的 **AI 匹配** 入口可以随时回到匹配工作台；首次进入时选择一条 JD，核对公共提示词、该 JD 专属提示词与飞书 JD 原文。工作台先在本地比较资料与标签规则，只为新增或变化的 JD 和候选人调用 AI 打标签（已有且未变化的记录直接跳过），按标签和关键词即时初筛；勾选候选人后进行 AI 深度评估，显示 1–5 星与依据。打标签和批量 AI 评估都可展开查看逐条进度并手动停止；停止后进度面板立即收起，正常结束后保留 10 秒。已发出的请求可能仍会在服务端完成。工作台的 **编辑标签规则** 直达 AI 管理页，可分别增删或改名候选人/JD 的标签分类，编辑各类允许标签及文字判定规则。AI 管理页还集中配置 API 地址、模型和三段提示词。若一个飞书字段中包含多条岗位，可在 AI 管理页使用“手动拆分”。提示词、拆分设置和标签规则保存在当前浏览器；API Key 保存在 Windows 凭据管理器；标签与评估结果保存在本机的 `match_state.json`。**只有点击开始匹配、打标签或评估按钮时，候选人资料和 JD 才会发送到已配置的 AI 服务。**当前不会推送飞书机器人，也不会向飞书写入。左侧“数据中心”预留后续触达、反馈和面试数据。

点击 **检查飞书更新**：本地服务读取三张表，与已下载的快照比较；如果没有变化，不改动本地文件；如果有变化，只更新对应数据和缺少的附件，再刷新页面。浏览器不会收到 App Secret。

如果第一次打开时提示没有数据，先执行：

```powershell
python ar.py pull --all-tables
```

此后每次运行 `pull` 都会更新网页快照。你也可以运行 `python ar.py sync`，在命令行执行同样的“仅在变化时更新”流程。`python build_web.py` 只会从现有 `downloads/` 重新生成网页快照，不连接飞书。候选人数据与生成的 `web/data.js` 已被 Git 忽略，不会随源代码提交。

启动脚本会调用这台电脑上的 `D:\Miniconda3\pythonw.exe` 运行本地服务，并明确调用 Edge 或 Chrome；不会受到 `.html` 文件默认关联到 VS Code 的影响。

## 准备

在**运行命令的同一个 PowerShell 窗口**里设置应用凭据：

```powershell
$env:FEISHU_APP_ID = '你的 App ID'
$env:FEISHU_APP_SECRET = '你的 App Secret'
```

这些值只在当前 PowerShell 会话中生效。不要将 App Secret 写进 `ar.json`、提交到 Git，或发到聊天里。如果 `check` 返回权限错误，请在多维表格页面将该应用添加为文档应用，并赋予相应的读取或编辑权限；开放平台的 API 权限与目标文档权限都需要满足。

```powershell
python ar.py check
```

若返回 `91403 Forbidden`，飞书[官方错误码说明](https://open.feishu.cn/document/server-docs/api-call-guide/generic-error-code)指出这是**应用缺少目标文档权限**。打开目标多维表格，右上角「…」→「更多」→「添加文档应用」，添加当前应用并授予可阅读或可编辑权限。若开启了高级权限，还需在多维表格中给应用相应的高级权限。此错误通常不是终端代理造成的。

## 下载

```powershell
python ar.py pull
```

默认下载链接中指定的数据表，输出到 `downloads/<table_id>/`：`fields.json`、`records.json`、`attachments.json` 和 `attachments/`。`records.json` 保留飞书返回的字段值和记录 ID，便于后续精确修改。`downloads/` 已加入 `.gitignore`。

下载同一多维表格内的所有数据表：

```powershell
python ar.py pull --all-tables
```

再次运行会更新同名文件；不会删除本地以前下载、这次已不在飞书记录中的附件。

## 修改

`record_id` 可从 `records.json` 中找到。字段名必须与飞书多维表格中的字段名一致。

```powershell
python ar.py set recXXXXXXXX 标题 '新的标题'
python ar.py set recXXXXXXXX 数量 12 --json
python ar.py attach recXXXXXXXX 附件 .\example.pdf
```

新增记录时，可先新建 `new-record.json`，内容如 `{"标题":"新词条"}`，然后运行：

```powershell
python ar.py create '@new-record.json'
```

`set` 默认按文本写入；数字、布尔值、列表等使用 `--json`。`attach` 会先读取原附件列表，再追加新文件；当前支持不超过 20 MiB 的文件。复杂字段的 JSON 格式需符合飞书[新增记录接口](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/create)的字段要求。

## 对应的官方接口

- [自建应用获取 tenant_access_token](https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal)
- [多维表格记录接口](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/list)
- [多维表格附件上传和下载 FAQ](https://open.feishu.cn/document/docs/bitable-v1/faq?lang=zh-CN)

如果将来使用知识库内的多维表格链接，当前 `ar.py` 还不支持直接解析 `/wiki/` 地址；需要先取得对应的 `app_token`。
