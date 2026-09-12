# 分数统计数据规范V0.7

业务来源：[考核办法V0.7](tdr-expert-review-assessment-v0.7.md) 。计分版本scores-v0.7，事实载荷仍为facts-v0.6。

- GET /api/statistics/scores：输入analysis_id、scope_confirmed（默认false），从当前原始事实和已保存选项重算；阻断分析拒绝计分，不接收客户端分数。
- GET /api/statistics/scores/export：同样的输入和算法，导出汇总、阶段依据、主观选项与使用说明；未知值留空并给出原因。
- stages：每阶段四项分值7／7／14／7、满分35、有效权重、加权贡献和opinion_bonus；阶段奖励不加权，无适用场次为0，实参为0或未知为null。
- process_total：按4／2／4及适用阶段归一计算的过程基础分，满分35。
- participation_count：全部阶段有效参评场次；本人出勤未知则null。participation_tier为满足3场门槛后的不同数量档序号，不足3场则null。
- participation_score：完整批次全体有效场次确认后，前两档得5／3，其余0；未确认范围或任一人出勤未知则null。不得将分散提交的本地分直接相加。
- objective_total＝process_total＋participation_score，满分40。subjective_total由六项选档重算，满分60。
- opinion_bonus：逐阶段奖励之和，不抵扣其他阶段的不足；范围未确认、没有适用阶段或任一适用阶段奖励待确认则null。
- uncapped_total＝objective_total＋subjective_total＋opinion_bonus；total＝min（uncapped_total，100）。任一合计为空则两者均为空。奖励不绕过缺失检查。
- 中间计算使用未舍入值，API显示值保留两位；导出保留规则版本、封顶前合计和封顶说明。
- 问卷接口及问卷文件只保存选项和依据，不含分数。第三模块查阅同一评审人的过程详情，关闭后保留草稿与焦点。
- 人工修改对策计入状态后重算对策分与总分，不改变意见数量和奖励。事实、问卷和计分文件的回载边界不变。
