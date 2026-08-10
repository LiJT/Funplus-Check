# FunPlus Zone 自动签到（Tiles Survive）

面向 [FunPlus Zone / Tiles Survive](https://zone.funplus.com/tilessurvive/) 的 GitHub Actions 每日自动化：

1. **会员签到礼**（`/signinbenefit`）：调用 `checkin/month` 领取当日奖励  
2. **任务中心**（`/benefits/pointstask`）：自动领取「游戏专区签到」「商城支付」等已完成任务积分  
3. **活跃任务 - 浏览帖子**：登录态下打开社区首页并浏览多条帖子，再尝试领取  
4. **会员专享礼包**：若有可领取项则自动领取  

实现风格参考 [SJS-Check](https://github.com/LiJT/SJS-Check)：GitHub Actions 定时执行 + Secret 配置凭据 + 可选 PushPlus 推送。

## 结论：GitHub Actions 能做吗？

**可以。** 但 FunPlus 登录是邮箱验证码，不适合把 Gmail 密钥放进 GitHub。推荐方案：

- 你在本地浏览器登录一次  
- 用本仓库 `export_auth.py` 导出 Cookie / localStorage（含 `h5-auth`）  
- 把导出内容放进仓库 Secret `FUNPLUS_AUTH`  
- Actions 每次带着这份登录态跑任务  

Cookie / token 过期后，重新导出并更新 Secret 即可。  
**不要**用 Actions Cache 存登录态：Cache 不是密钥存储，存在被读取风险，且会丢。

关于「累计 31 天签到后还有没有奖」：前端是**按月历/活动 active 周期**发放（`checkin/month/info` 的 `month` + `gift_list`）。一个周期内的每日格领完后，下一周期会重置天数；不是一次性 31 天永久结束。

## 快速开始

### 1. 本地导出登录态

**推荐（一键刷新）：** 双击仓库根目录的 `refresh_auth.bat`  
它会打开浏览器让你登录，校验成功后自动更新 GitHub Secret `FUNPLUS_AUTH`，并可选立刻触发一次 Actions。

也可以手动：

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
| `PUSHPLUS_TOKEN` | 否 | [PushPlus](http://www.pushplus.plus) 推送 |

可选（一般不必）：

| Secret / Var | 说明 |
|--------------|------|
| `FUNPLUS_H5_AUTH` | 仅 token |
| `FUNPLUS_COOKIE` | 仅 Cookie 字符串 |
| `FUNPLUS_STORAGE_STATE` | 原始 Playwright storage_state |
| `FUNPLUS_BASENAME` | 默认 `/tilessurvive` |
| `FUNPLUS_GAME_PROJECT` | 默认 `ts_global` |

### 3. 启用 Actions

1. 打开 **Actions**，启用 workflow  
2. 选择 **FunPlus 每日签到** → **Run workflow** 测试  
3. 默认定时：北京时间 **08:20**、**22:20**（避开整点高峰；一天两次防单次失败）

## 本地试跑

```bash
# 先 export_auth.py，确保存在 .auth/funplus_auth.json
python main.py
```

## 自动化覆盖说明

| 入口 | 行为 |
|------|------|
| 签到福利 `signinbenefit` | `checkin/month/info` → 未签则 `checkin/month` |
| 周签到（若开放） | `checkin/week/info` → `checkin/week` |
| 任务中心 | `task/task_list`（日常/活跃/成长/游戏）→ `get_times>0` 时 `task/get` |
| 浏览帖子 | Playwright 打开社区并访问帖子，再领取 |
| 会员礼包 | `member_gift/list` → 可领则 `member_gift/receive` |

「商城支付 1 次储值订单」只有你在游戏/商城真实消费后才会变成可领取；脚本负责**自动点领取**，不会替你下单。

## 常见问题

**Q: Actions 提示未登录 / h5-auth 无效**  
A: 重新运行 `export_auth.py`，更新 `FUNPLUS_AUTH`。

**Q: 社区浏览数量是 0**  
A: 社区是微前端，结构可能变化。先看 Actions 日志；也可本机 `FUNPLUS_HEADED=1 python main.py` 观察。脚本仍会尝试领取其他 API 任务。

**Q: 安全吗？**  
A: 比上传 Gmail 应用密码安全得多。`FUNPLUS_AUTH` 只存会话，仍请使用私有仓库，并定期轮换。

## 免责声明

仅供个人学习与自用。请遵守 FunPlus 用户协议与活动规则，避免过高频率请求。
