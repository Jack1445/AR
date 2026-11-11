# AR · 人才与机会

在本地查看飞书多维表格中的候选人和校友 JD，并进行 AI 打标签、初筛与匹配评估。

## 新电脑第一次使用

需要 **Windows 10/11**、**Python 3.10 或更新版本**，以及已开通相应权限的飞书应用。不需要安装 Conda。

1. 下载完整项目，双击 **`首次配置AR.cmd`**。
2. 脚本会打开凭据文件。在文件顶部填写同一个飞书应用的 **App ID** 和 **App Secret**，保存并关闭记事本。
3. 如果这台电脑还没有 `ar.json`，按提示粘贴一次目标**飞书多维表格链接**。
4. 等待「首次配置完成」，然后双击 **`打开AR网页.cmd`**。

首次配置脚本会自动创建项目内的 Python 环境、安装依赖、识别并验证三张表、保存飞书凭据、下载记录和附件、生成网页数据。配置失败会显示原因；修正后重新运行即可。

## 平时使用

直接双击 **`打开AR网页.cmd`**。网页只在本机 `127.0.0.1:38479` 运行。要获取飞书新数据，点击网页中的「检查飞书更新」；没有变化时不会改动本地快照。

AI 服务的 API 地址、Key、模型和提示词在网页的「AI 管理」中另行设置。候选人与 JD 的标签规则也在那里编辑。当前不会向飞书写入匹配结果，也不会自动发送机器人消息。

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

`ar.py` 还支持 `set`、`create` 和 `attach`，可用 `.\.venv\Scripts\python.exe ar.py --help` 查看。通常只需使用网页，无须手动运行这些命令。
