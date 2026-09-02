# FunPlus Zone 自动签到（Tiles Survive）

**语言：** [English](README.md) · 简体中文

面向 [FunPlus Zone / Tiles Survive](https://zone.funplus.com/tilessurvive/) 的 GitHub Actions 每日自动化：签到、任务领取、社区浏览、免费会员礼包等。

---

## 新手教程：Fork 到自己的 GitHub 并跑起来（无需编程基础）

按顺序做即可。全程不用写代码。

### 你需要准备

- 一个 **GitHub 账号**（免费即可）
- 一台 **Windows 电脑**（推荐）或 Mac / Linux
- **Python 3.9+** — 从 [python.org](https://www.python.org/downloads/) 下载，安装时勾选 **“Add Python to PATH”**

### 第一步 — Fork 本仓库

1. 在 GitHub 打开本仓库页面。
2. 点击右上角 **Fork**。
3. 保持默认选项并确认。完成后你会有自己的副本，例如 `https://github.com/你的用户名/Funplus-Check`。

### 第二步 — 开启 GitHub Actions

Fork 出来的仓库，Actions **默认可能是关着的**。

1. 打开 **你的 Fork** → 顶部 **Actions**。
2. 若出现黄色提示条，点 **“I understand my workflows, go ahead and enable them”**（我了解我的工作流，继续启用）。
3. 列表里应能看到 **「FunPlus 每日签到」** 工作流。

### 第三步 — 在电脑上导出 FunPlus 登录态

FunPlus 用 **邮箱验证码** 登录，**不要把 Gmail 密码** 填进 GitHub。正确做法是：在本地浏览器登录一次，导出会话文件。

**方式 A — Windows 一键（最省事）**

1. 安装 [GitHub CLI](https://cli.github.com/)，在终端执行一次 `gh auth login` 完成登录。
2. 把 **你的 Fork** 克隆到电脑（仓库页 **Code** → 复制 HTTPS 地址）：

   ```bash
   git clone https://github.com/你的用户名/Funplus-Check.git
   cd Funplus-Check
   ```

3. 双击项目里的 **`refresh_auth.bat`**。
4. 弹出 Chromium 浏览器 → 用邮箱验证码登录 FunPlus Zone。
5. 登录成功后，脚本会自动把 **`FUNPLUS_AUTH`** 上传到你 Fork 的 GitHub Secret。

**方式 B — 手动（全平台通用）**

```bash
git clone https://github.com/你的用户名/Funplus-Check.git
cd Funplus-Check
pip install -r requirements.txt
python -m playwright install chromium
python -u export_auth.py
```

成功后打开 `.auth/funplus_auth.b64.txt`，**全选复制**（一整行 Base64 是正常的）。

### 第四步 — 填写 GitHub Secret

1. 在 GitHub 打开 **你的 Fork** → **Settings** → **Secrets and variables** → **Actions**。
2. 点 **New repository secret**。
3. **Name** 填：`FUNPLUS_AUTH`
4. **Secret** 粘贴 `.auth/funplus_auth.b64.txt` 的全部内容（或用 `.auth/funplus_auth.json` 原文）。
5. 点 **Add secret** 保存。

> 日常使用只需 **`FUNPLUS_AUTH`** 这一个 Secret。PushPlus 推送为可选项，不配也能正常签到。

### 第五步 — 手动测试一次

1. 打开 **Actions** → 选择 **FunPlus 每日签到**。
2. 点 **Run workflow** → 再点绿色 **Run workflow**。
3. 等约 2 分钟，点进这次运行，在日志里找 **「FunPlus 签到报告」**。
4. 若显示登录有效、签到或礼包相关成功信息，说明部署完成。

### 第六步 — 自动定时

无需额外设置。工作流每天 **北京时间 08:20、22:20** 各跑一次（在 workflow 里用 UTC 定时）。

登录态过期后（可能几天到几周），重新运行 **`refresh_auth.bat`** 或 **`export_auth.py`**，再更新 `FUNPLUS_AUTH` 即可。

### 常见问题速查

| 现象 | 处理 |
|------|------|
| Actions 是空的 / 无法运行 | 按第二步启用工作流。 |
| 提示未登录 / h5-auth 无效 | 重新导出登录态并更新 `FUNPLUS_AUTH`。 |
| `refresh_auth.bat` 提示找不到 gh | 安装 GitHub CLI 并 `gh auth login`，或改用方式 B + 第四步手动粘贴 Secret。 |
| Fork 里没有 Secrets 菜单 | 必须是你自己的 Fork，且你有管理员权限。 |

---

## 自动化做什么

1. **会员签到礼**（`/signinbenefit`）：月历签到  
2. **任务中心**（`/benefits/pointstask`）：领取已完成任务积分（如游戏专区签到）  
3. **活跃任务 - 浏览帖子**：登录态下浏览社区帖子并领取  
4. **会员专享礼包**（`/benefits/pack`）：每天检查 **每周礼包、等级礼包** 等免费项（已领则跳过）

风格参考 [SJS-Check](https://github.com/LiJT/SJS-Check)：GitHub Actions 定时执行 + Secret 存登录态。

## GitHub Actions 能做吗？

**可以。** 推荐流程：

- 本地浏览器登录一次  
- 用 `export_auth.py` 导出 Cookie / localStorage（含 `h5-auth`）  
- 写入 Secret **`FUNPLUS_AUTH`**  
- Actions 每次带着这份登录态执行任务  

过期后重新导出并更新 Secret。**不要**用 Actions Cache 存登录态。

**关于「31 天签到」：** 奖励按**月历 / 活动周期**发放（`checkin/month/info`），周期结束后会重置，不是一辈子只能领 31 天。

## 快速开始（维护者 / 本地开发）

### 1. 本地导出登录态

**推荐：** 双击 `refresh_auth.bat`（需已 `gh auth login`，会自动更新 GitHub Secret）。

**手动：**

```bash
pip install -r requirements.txt
python -m playwright install chromium
python -u export_auth.py --push-secret
```

导出文件（本地私有，勿提交）：

- `.auth/funplus_auth.json`
- `.auth/funplus_auth.b64.txt`

### 2. 配置 GitHub Secrets

仓库 → **Settings** → **Secrets and variables** → **Actions**：

| Secret | 必填 | 说明 |
|--------|------|------|
| `FUNPLUS_AUTH` | **是** | `funplus_auth.b64.txt` 全文，或 JSON 原文 |
| `PUSHPLUS_TOKEN` | 否 | 可选 PushPlus 推送 |

可选：

| Secret / Var | 说明 |
|--------------|------|
| `FUNPLUS_H5_AUTH` | 仅 token |
| `FUNPLUS_COOKIE` | 仅 Cookie 字符串 |
| `FUNPLUS_STORAGE_STATE` | 原始 Playwright storage_state |
| `FUNPLUS_BASENAME` | 默认 `/tilessurvive` |
| `FUNPLUS_GAME_PROJECT` | 默认 `ts_global` |

### 3. 启用 Actions

1. **Actions** → 启用 workflow  
2. **FunPlus 每日签到** → **Run workflow** 测试  
3. 默认定时：北京时间 **08:20**、**22:20**（一天两次更稳）

## 本地试跑

```bash
# 先运行 export_auth.py，确保存在 .auth/funplus_auth.json
python main.py
```

## 自动化覆盖说明

| 入口 | 行为 |
|------|------|
| 签到福利 `signinbenefit` | `checkin/month/info` → 未签则 `checkin/month` |
| 周签到（若开放） | `checkin/week/info` → `checkin/week` |
| 任务中心 | `task/task_list` → `get_times>0` 时 `task/get` |
| 浏览帖子 | Playwright 打开社区帖子详情，再领取 |
| 会员礼包 `benefits/pack` | `GET member_gift/list` + `list_grouped` → 可领则 `receive`（含每周/等级礼包；每天执行） |

「商城支付 1 次储值订单」需真实消费后才可领取；脚本只负责**点领取**，不会替你下单或扣积分。

## 常见问题

**Q: Actions 提示未登录 / h5-auth 无效**  
A: 重新运行 `export_auth.py`，更新 `FUNPLUS_AUTH`。

**Q: 社区浏览数量是 0**  
A: 社区为微前端，结构可能变化。先看 Actions 日志；本机可 `FUNPLUS_HEADED=1 python main.py` 观察。其他 API 任务仍会继续。

**Q: 安全吗？**  
A: 比把 Gmail 密码放进 GitHub 安全得多。`FUNPLUS_AUTH` 仅为会话，建议用**私有仓库**并定期刷新。

## 免责声明

仅供个人学习与自用。请遵守 FunPlus 用户协议与活动规则，避免过高频率请求。
