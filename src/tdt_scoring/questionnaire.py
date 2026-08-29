from __future__ import annotations


QUESTIONS = [
    {
        "id": "fulfillment_collaboration",
        "title": "履职与协作",
        "prompt": "回顾整个项目，该专家的评审准备、响应复核和协作表现符合哪种情况？",
        "options": [
            {
                "level": "high",
                "score": 10,
                "label": "稳定履职",
                "description": "评审准备充分，按要求完成参评、会签和问题复核；响应及时，沟通方式未影响协作。",
            },
            {
                "level": "medium",
                "score": 6,
                "label": "基本履职",
                "description": "完成主要职责，但存在准备不足、响应延迟或复核不及时；尚未明显影响项目推进。",
            },
            {
                "level": "low",
                "score": 0,
                "label": "履职明显不足",
                "description": "多次未按要求响应、复核或完成职责，且未合理改派；已经影响评审闭环或项目推进。",
            },
        ],
    },
    {
        "id": "professional_judgement_guidance",
        "title": "专业判断与指导",
        "prompt": "结合项目最终结果，该专家的风险判断、技术结论和指导意见符合哪种情况？",
        "options": [
            {
                "level": "high",
                "score": 20,
                "label": "判断准确，指导有效",
                "description": "关键判断与后续开发、测试或量产结果一致，并给出明确、可执行的改善或验证路径。",
                "reference": [
                    "关键风险判断准确，技术结论得到后续事实验证。",
                    "指导意见可以直接转化为改善、验证或处置行动。",
                ],
            },
            {
                "level": "medium",
                "score": 14,
                "label": "整体准确，但存在误判或遗漏",
                "description": "主要判断整体正确，但存在个别偏差或指导不够具体；得到及时纠正，或未造成重大损失。",
                "reference": [
                    "存在个别误判、风险遗漏或竞争力判断偏差，但在关键节点前得到纠正。",
                    "产生额外验证、局部返工或一定资源浪费，但未造成重大质量、节点、成本或机会损失。",
                ],
            },
            {
                "level": "low",
                "score": 0,
                "label": "严重判断失误并造成重大影响",
                "description": "因履职态度或专业能力原因发生严重误判，评审结论与最终结果明显不符，并造成重大影响。",
                "reference": [
                    "对可控风险作出明显失衡判断，造成不必要阻断，最终错失技术领先、产品首发或市场窗口。",
                    "对行业、竞品或技术竞争力严重误判，导致方向选择错误、资源浪费或竞争对手率先实现技术领先。",
                    "严重技术误判导致量产质量事故。",
                    "遗漏重大风险，导致项目无法通过TDR3或其他关键节点。",
                    "错误指导造成大范围返工、显著延期或重大成本损失。",
                    "明显错误放行，导致相关风险在测试、交付或量产阶段实际发生。",
                ],
            },
        ],
    },
    {
        "id": "outstanding_contribution",
        "title": "突出贡献",
        "prompt": "该专家是否产生了超出常规评审职责、且能够明确指认的项目价值？",
        "options": [
            {
                "level": "high",
                "score": 10,
                "label": "有突出贡献",
                "description": "避免重大风险或损失，推动更优方案落地，显著提升技术价值，或协助攻克关键技术难题。",
            },
            {
                "level": "low",
                "score": 0,
                "label": "无突出贡献",
                "description": "完成正常评审职责，但没有超出常规履职范围的可指认贡献。",
            },
        ],
    },
]

QUESTION_IDS = tuple(question["id"] for question in QUESTIONS)
QUESTION_SCORES = {
    question["id"]: {
        option["level"]: option["score"] for option in question["options"]
    }
    for question in QUESTIONS
}


def questionnaire_payload() -> list[dict[str, object]]:
    """Return a copy suitable for API responses without preselecting answers."""
    return [
        {
            **question,
            "options": [dict(option) for option in question["options"]],
        }
        for question in QUESTIONS
    ]
