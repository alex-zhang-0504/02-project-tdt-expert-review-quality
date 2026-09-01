# TDRX评审事实与年度考评数据规范（按年度）V0.5

> 本文只定义字段、公式、聚合和校验。业务规则以[《TDT技术项目TDR评审人质量考评办法（按年度）V0.5》](tdr-expert-review-quality-assessment-by-year-v0.5.md)为准。

## 1．数据来源与场次主键

- 输入可以是飞书归档文件夹、单个飞书电子表格或本地Excel文件。
- 有效场次唯一键：`project_code + stage`。
- `stage`只允许TDR1、TDR2、TDR3。
- 所选报告中能够正常解析的全部场次进入评分，不以TDR3是否存在作为纳入条件，也不生成未完成TDR3提醒。
- 同一主键出现两份报告时阻断，不自行选择。

## 2．单场事实字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `review_id` | 文本 | `项目编码-评审阶段` |
| `project_code` | 文本 | 项目主键 |
| `project_name` | 文本 | 子任务名称 |
| `stage` | 枚举 | TDR1／TDR2／TDR3 |
| `expert_name` | 文本 | 归一后的原评审人姓名 |
| `proxy_name` | 文本／空 | 代理人姓名，分数仍归原评审人 |
| `attendance_score` | 整数 | 13或0 |
| `signoff_score` | 整数 | 25或0 |
| `opinion_score` | 整数 | 10、6或0 |
| `session_total` | 整数 | 0—48 |
| `problem_contribution` | 布尔 | 本场是否存在归属该评审人的至少一个有效问题 |
| `source_name` | 文本 | 源报告 |
| `sheet_name` | 文本 | 源Sheet |
| `evidence_cells` | 文本数组 | 计分证据位置 |

## 3．过程表现聚合

```text
session_total＝attendance_score＋signoff_score＋opinion_score

project_process_average
＝同一评审人、同一项目的session_total之和÷scoring_session_count

annual_process_average
＝同一评审人的project_process_average之和÷project_count
```

其中：

- `scoring_session_count`中文名为“计分场次”，表示项目平均分分母。
- 未发生阶段显示空白，不补0分。
- 已有记录中的缺席未改派按该场实际分数进入项目平均。
- 项目均分和年度均分均四舍五入到1位小数。

## 4．年度服务贡献字段

| 字段 | 公式或含义 |
|---|---|
| `participation_session_ids` | 该评审人的有效参评场次主键去重清单 |
| `participation_session_count` | `participation_session_ids`数量 |
| `problem_session_ids` | 至少含1条可归属有效问题的场次主键去重清单 |
| `problem_session_count` | `problem_session_ids`数量 |
| `service_eligible` | `participation_session_count >= 3` |
| `participation_score` | 合格人员中参评场次前两个不同数量档映射6／3／0 |
| `problem_score` | 合格人员中问题贡献场次前两个不同正数量档映射6／3／0 |
| `annual_service_score` | 两项相加，0—12 |

同一评审人在同一场提出多条问题时，`problem_contribution`仍为真一次，不能按问题条数累加。

## 5．代理字段

| 字段 | 公式 |
|---|---|
| `expected_session_count` | 原评审人名下的计分场次数 |
| `proxy_session_count` | 其中存在代理人的场次数 |
| `proxy_rate` | `proxy_session_count ÷ expected_session_count × 100％` |

代理率保留1位小数，只展示、不参与V0.5自动计分。

## 6．场次分布

系统在维度一结果和导出中持续输出：

- 少于3场人数。
- 3—5场人数。
- 6—10场人数。
- 超过10场人数。

分布基于完整分析对象中的`participation_session_count`计算，筛选页面行时不改变全批次分布。

## 7．分散提交字段

项目经理提交包至少保存：

- `schema_version`、`rule_version`、`batch_id`。
- `manager_id`、`manager_name`、`revision`、`exported_at`。
- 原始场次及其项目、阶段、评审人、代理、问题和证据。
- 可阅读的逐场事实、项目过程结果和年度临时结果。

汇总端校验规则：

1. 所有提交表的`rule_version`必须一致且为`annual-v0.5-dimension-one`。
2. 年度批次必须一致。
3. 项目只能属于一个项目经理。
4. 同一项目阶段只能出现一次。
5. 完整性校验失败的提交表不得进入汇总。
6. 汇总端从场次事实统一重算年度过程分、参评场次、问题贡献场次及两项排名分。

## 8．结果字段

| 字段 | 范围 |
|---|---:|
| 项目过程均分 | 0—48 |
| 年度评审过程表现 | 0—48 |
| 评审参与度 | 0／3／6 |
| 场次问题贡献 | 0／3／6 |
| 年度服务贡献 | 0—12 |
| 客观分数 | 0—60 |
| 专业价值贡献 | 0—40 |
| 年度总分 | 0—100 |

## 9．动态试算与年底冻结

结果元数据至少包含年度批次、统计截止时间、数据状态、规则版本、已提交项目经理数量和期望项目经理数量。

- 日常导入：`data_status = provisional`。
- 年底收齐并确认：`data_status = frozen`。
- 冻结前的6／3／0排名分允许随批次数据增加而变化。

## 10．阻断与非阻断边界

| 情形 | 处理 |
|---|---|
| 缺少TDR3 | 常规状态，不提示、不阻断 |
| 同一项目阶段重复 | 阻断 |
| 项目编码或阶段缺失／非法 | 阻断 |
| 评审人缺失 | 阻断 |
| 问题提出人或描述缺失 | 该问题不归属、不计贡献；按现行规则提醒 |
| 疑似同一评审人 | 人工确认前阻断，不自动合并 |
| 场次分、项目均分或客观分超出上限 | 阻断 |
| 经理提交表规则版本不一致 | 阻断 |

## 11．验收最低集

1. 只有TDR1或只有TDR1＋TDR2的项目能够生成项目过程分。
2. 一场多个问题只生成一个问题贡献场次。
3. 参评不足3场时两项服务贡献均为0。
4. 参评达到3场但只有1个问题贡献场次时，可以进入场次问题贡献排名。
5. 一个三场项目和三个一场项目都形成3个有效参评场次。
6. 代理记录归原评审人，同时代理率正确。
7. 16位项目经理提交后按完整批次重新排名，局部排名分不直接相加。
8. 页面、Excel和API统一显示48／12／60分上限及V0.5字段名。
