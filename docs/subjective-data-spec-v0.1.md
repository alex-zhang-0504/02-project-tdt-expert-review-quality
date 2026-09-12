# 主观评价数据规范V0.1

新业务口径见[考核办法V0.7第四节](tdr-expert-review-assessment-v0.7.md#四维度二专业价值贡献60分) 。六项选项结构及依据要求不变，模块改名「专业价值贡献」，第四模块按8／5／0、13／9／0、13／9／0、8／5／0、8／5／0及10／0换算；规则版本需同步，满分60。已按subjective-v0.7实现，以下记录保存与接口结构。

- WorkbookAnalysis新增subjective_reviews，以expert_name为键，保存本批次该人的一份评价。
- 记录包含规则版本、评价人、六维选项（high／medium／low，突出贡献仅high／low）、项目编码、事实说明、更新时间与完成状态，不含total。
- 服务端校验维度和选项，依据项目必须属于当前评审人；只保存问卷，不接收客户端分数。
- 部分选项允许暂存；缺项或必填依据不全保留对应状态，保存要求评价人非空、分析存在且无阻断。
- GET /api/subjective/catalog仅返回六维标题、小标题与解释，不返回分值。
- POST /api/subjective/review保存评价并返回记录；GET /api/subjective/export?analysis_id=…导出当前分析的全部评审人评价及未评价状态。
- 问卷Excel不含分数，第四模块依据已保存问卷现算，详见《score-statistics-data-spec-v0.1.md》。不恢复旧/api/score或/api/questionnaire，不修改facts-v0.6载荷；主观多人合并及回载待实施。
