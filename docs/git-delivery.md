# 跨电脑使用与Git交付

交付标准：全新检出可通过首次初始化启动系统，不依赖原电脑的var、虚拟环境、测试遗留文件或工作区外脚本。Git同步通用程序与规则；继续已有考评另需迁移本机数据。

## 文件边界

| 纳入Git | 不纳入Git |
|---|---|
| src全部正式代码及前端资源 | .venv、缓存、构建和输出产物 |
| start.cmd、start.command、pyproject.toml、.gitattributes、.gitignore | 本机环境、密钥、密码凭据 |
| config下客观、主观、报告所有者及AI判定配置 | config/project-managers.json真实人员配置 |
| config/project-managers.example.json虚拟账号示例 | var下数据库、备份、原始人工纠正、日志及临时验收文件 |
| tests、虚拟data样本及生成器 | 真实报告、姓名、内部业务内容与未脱敏学习样本 |
| README、AGENTS、ROADMAP、规则规范与脱敏验收记录 | 私人编辑器及AI工具配置 |

docs中的草稿和archive中的历史规则可保留用于追溯，不是启动依赖。提交截图、表格、案例前检查内容，不因文件后缀或所在目录就视为安全。不要把正式功能写在被忽略的var脚本中。

## 新电脑首次使用

1. 拉取已提交并推送的版本。Windows准备Python 3.12或更高版本；macOS启动器支持uv或python3.12／python3.13。启动时需要能下载声明的依赖，已安装的环境可复用。
2. Windows运行start.cmd，macOS运行start.command。脚本创建项目内.venv并安装依赖；不需要原电脑的var或真实名单才能启动。
3. 在首次页面登记管理员并设置本机密码，系统创建账号配置与空数据库。
4. 参照project-managers.example.json维护本机project-managers.json，保留已有管理员编号。启用的技术项目经理用于新任务；既有任务通过任务卡片修改名单。
5. 导入本地Excel报告并开展考评。飞书来源须在新电脑另外安装并授权lark-cli；AI分析须配置有效API凭据。授权、密钥及模型调用不由Git提供。

不自动创建示例账号，不附带通用密码。项目经理仍按当前姓名登录机制识别，Git同步不会增强身份认证。

## 继续原电脑已有考评

停止源电脑业务写入后，通过受控文件迁移方式保存同一时点的真实config/project-managers.json、var/multi-user目录及var/scoring-admin.json；包含数据库、人工纠正记录与管理员密码凭据。目标若已有数据，先备份并核对，不能直接覆盖或用Git合并数据库。跨机恢复需另外验收，不等同于启动空系统。

## 提交前验收

- 新增正式源码和资源必须进入Git清单；移动配置同时更新后台路径、读取凭据、测试及有效文档链接。
- 检查真实名单、数据库、凭据及原始样本仍被忽略；通用配置和虚拟示例未被误排除。
- 用仅含候选Git文件的独立检出，验证Windows启动脚本CRLF、macOS脚本LF及初始Git状态；从无var、无.venv开始实际启动。
- 验证首次初始化、配置读取及虚拟任务保存／重启；实际验证范围写入ROADMAP。Windows验证不能代替macOS实机验证，接口成功不能代替页面交互验收。
- 未提交或未推送的本地改动，另一台电脑不能通过pull取得。
