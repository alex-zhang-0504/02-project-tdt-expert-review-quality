# 分数统计数据规范V0.8

2026-09-25：主观题目和分值从考核固定的问卷／参数快照读取，不随管理员更新模板改变。主观及总分导出携带问卷快照，题目标题、选项及边界与本次评价一致。默认分数不变，编辑后按新考核快照计算。

业务来源：[考核办法V0.8](tdr-expert-review-assessment-v0.8.md) 。计分版本scores-v0.11，事实载荷仍为facts-v0.6；已完成任务返回原归档结果及其版本。

- GET /api/statistics/scores：输入analysis_id；已确认名单时服务端自动确认本次导入范围。scope_confirmed（默认false）仅保留历史接口兼容，不再由页面勾选，从当前原始事实和已保存选项重算；阻断分析拒绝计分，不接收客户端分数。
- GET /api/statistics/scores/export：同样的输入和算法，导出汇总、阶段依据、主观选项与使用说明；未知值留空并给出原因。
- stages：每阶段三项分值5／10／10、满分25、有效权重、加权贡献和opinion_bonus；阶段奖励不加权，无适用场次为0，实参为0或未知为null。
- process_total：按适用阶段组合的百分比直接加权计算的过程基础分，默认满分25。scores-v0.11使用stage_percentages：all含TDR1／TDR2／TDR3，first_third含TDR1／TDR3，with_second含TDR1_or_TDR3／TDR2；每组合计100％。单阶段固定100％，不作为可修改字段。旧未归档快照在读取层兼容，已归档结果不重算。
- participation_count：全部阶段有效参评场次；本人出勤未知则null。participation_tier为达到本任务最低场次后的高／中／低档1／2／3，未达门槛或尚不可统计则null。
- participation_score：完整批次按实参场次降序、并列占位名次计算，分界为ceil(N×10%)及ceil(N×30%)，并列跨界取高档；N为完整考核名单人数。各档分值与最低场次读取任务参数，未达门槛取低档分。未确认范围或任一人出勤未知则null。不得将分散提交的本地分直接相加，筛选不改变计分范围。
- objective_total＝process_total＋participation_score，满分30。subjective_total由六项选档重算，满分70。
- opinion_bonus：逐阶段奖励之和，不抵扣其他阶段的不足；范围未确认、没有适用阶段或任一适用阶段奖励待确认则null。
- solution_bonus：含对策意见条数×2，各阶段直接相加；范围未确认、无适用阶段或有待识别则null。识别待处理只阻断对策奖励和总分，不阻断已具备事实的过程基础分。
- uncapped_total＝objective_total＋subjective_total＋opinion_bonus＋solution_bonus；total＝min（uncapped_total，100）。任一合计为空则两者均为空。奖励不绕过缺失检查。
- 中间计算使用未舍入值，API显示值保留两位；导出保留规则版本、封顶前合计和封顶说明。
- 问卷接口及问卷文件只保存选项和依据，不含分数。第三模块查阅同一评审人的过程详情，关闭后保留草稿与焦点。
- 人工修改对策计入状态后重算对策奖励与总分，不改变意见数量、过程基础分或超额意见奖励。事实、问卷和计分文件的回载边界不变。

## 2026-09-17接口更新

名单门禁、评分配置快照、两维独立导出及经理问卷往返接口见《assessment-workflow-v0.1.md》。计分请求必须先确认名单；分析新增assessment和manager_reviews。意见平均数字段为opinion_average，不再以百分比展示；旧opinion_rate仅兼容旧载荷。第二、三模块分别显示客观与主观评分，第四模块不重复加奖励。

2026-09-23：范围确认指第一模块固定的本次导入范围，不证明外部报告完整。评分导出记录纳入报告清单。评审人多选只改变显示，不作为计分请求参数。客观评分字段采用基础得分、评审意见超额得分、输出有效对策得分、客观总得分；内部字段与公式不变。

客观模块两页统一调用GET /api/statistics/scores/export?analysis_id=…&dimension=objective，文件名为「客观数据评价结果_截止YYYY年MM月DD日前的评审记录.xlsx」。仅含「数据统计」「客观评分」两个工作表，前者每人四行（全部阶段及TDR1／2／3）；后者保留完整评分名单，并在数据区下方附评分参数及报告范围凭据。筛选器只覆盖评分数据行，不含凭据区。主观导出及经理提交包接口不变。

2026-09-23主观升级：每题独立筛选有效评价，前五题按有效人数等权平均，贡献取最高分。输出subjective_items中的valid_count和responded_count；subjective_progress.completed为完成所有回应的经理数（可含有原因的无法判断），final另要求各题有有效分及全部任务闭合。缺失不得补0或折算。旧问卷版本不参与新规则计分。主观导出新增有效人数、完整多条依据及题目版本。
