# 主观评价数据规范V0.1

2026-09-25配置化：GET `/api/subjective/catalog?analysis_id=...`读取该考核问卷快照；不传编号用于读取当前模板。返回题目内容、统一说明、贡献提示、无法判断提示及`questionnaire_hash`。问卷提交携带该指纹，明确不匹配时拒绝。确认考核保存`assessment.questionnaire`完整配置（含文案与分值），`assessment.policy`保存合并计分参数。两个管理员范围接口`/api/assessment/admin/policy/objective`与`/subjective`支持GET／PUT；PUT须授权及旧指纹，客观只能修改客观字段，主观为文案与scores一次原子保存。内容版本自增，算法版本不变。详见`questionnaire-configuration.md`。

2026-09-23采用subjective-v0.9，完整题目见《subjective-questionnaire-v0.9.md》，分值维持70分。

- `manager_reviews[manager_id][expert_name]`保存经理一票；每份问卷携带`rule_version`、`ratings`、状态、修订、评价人和更新时间，不接受客户端分数。
- `ratings[dimension_id]`保留`option`、兼容字段`project_code`／`note`，增加`evidence:[{project_code,note}]`与`reason`。每条依据沿用100字，可关联多个共同项目及同一项目的多条记录，项目必须属于该经理和评审人的交集。
- 前五题内部行为编码high／medium／low，额外回应状态unable／no_opportunity；贡献仅high／low。网页与Excel显示中文行为，不暴露编码和选项分值。
- 无法判断／无职责机会须填写原因，算已回应，分数为null。未选或依据不齐不算已回应；有效0分正常计入平均。
- 2026-09-25依据必填范围：第1题不强制；第2—5题仅low；第6题仅high。判定按选项编号，不随管理员调整分值而改变。其他档位不提供依据填写入口，历史非必填依据保留且不参与完成门槛判断。
- `GET /api/subjective/catalog`返回title、prompt、boundary、options、response_options及rule_version，不返回分值。题干、职责边界、行为解释直接显示。
- `POST /api/subjective/review`校验版本和共同项目范围；新旧版本不混算。旧记录保留但待重新确认；旧任务Excel版本不符拒绝回收。新客户端提交当前题目版本。
- 保存完整回应的问卷标记「已完成」，不代表所有题都有有效分。逐题输出valid_count、responded_count；前五题有效等权平均，贡献取有效最高分。所有任务已回应或排除、各题均有有效分且经理归属无缺失才生成最终分；否则仅保留可计算的题分及暂定结果。
- 主观结果导出包含中文行为、题干、边界、问卷版本、每题有效人数及全部依据。经理Excel往返接口保留兼容，新增补充依据sheet，中文下拉选项映射内部编码；页面不恢复分发／回收入口。
- 尚未实现跨重启持久化、半年度转年度初稿或管理员复核。当前数据仍仅在本次服务内存中。
