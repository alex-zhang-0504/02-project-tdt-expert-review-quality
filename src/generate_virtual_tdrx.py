from __future__ import annotations

import argparse
import posixpath
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"

ET.register_namespace("", MAIN_NS)
ET.register_namespace("r", DOC_REL_NS)


EXPERTS = [
    "宋祖防",
    "高腾飞",
    "高大宇",
    "滕帅",
    "林世杰",
    "罗勇平",
    "梅傲寒",
    "吴贞奇",
    "赵阳",
    "杨凯",
    "刘振岩",
]


SESSIONS = {
    "TDR1": {
        "date": date(2026, 3, 18),
        "meeting_conclusion": "Go with Risk",
        "meeting_opinion": "技术路线可行，需补齐关键器件边界、功耗预算和首轮验证计划后并行推进。",
        "signoffs": [
            ("宋祖防", "正常", "Go", ""),
            ("高腾飞", "正常", "Go with Risk", "关键器件能力边界需要用样片数据闭环，否则后续方案选型存在偏差。"),
            ("高大宇", "缺席未改派", "TBD", ""),
            ("滕帅", "正常", "Go with Risk", "链路预算对温漂和批次差异的余量不足，需要增加最差条件校核。"),
            ("林世杰", "正常", "Go", ""),
            ("罗勇平", "部分参加", "Go", ""),
            ("梅傲寒", "缺席未改派", "Go", ""),
            ("吴贞奇（代理：李俊）", "改派（正常）", "Go", ""),
            ("赵阳", "正常", "TBD", ""),
            ("杨凯", "正常", "Go with Risk", "验证计划缺少弱网和高温组合场景，无法覆盖核心技术风险。"),
            ("刘振岩", "正常", "Go with Risk", "质量门限应在TDR1阶段明确并与后续量产判定保持一致。"),
        ],
        "problems": [
            (
                "TDR1-1",
                "高腾飞、滕帅、杨凯、刘振岩",
                "关键器件边界、链路余量和组合场景验证尚未形成统一基线。",
                "建立统一技术基线，补充最差条件链路预算及弱网高温组合验证计划。",
                "评审基线文档完成会签；仿真余量不低于3 dB；组合场景用例覆盖率达到100%。",
                "03.25：基线与验证计划已更新，等待首轮样片数据。",
                "open",
            ),
            (
                "TDR1-2",
                "林世杰",
                "整机天线布局需要提前预留隔离区，避免结构冻结后返工。",
                "在结构草图中标记天线净空区并纳入设计检查表。",
                "结构草图通过天线与结构联合评审，净空尺寸满足设计规范。",
                "03.22：联合评审完成。",
                "closed",
            ),
        ],
    },
    "TDR2": {
        "date": date(2026, 5, 27),
        "meeting_conclusion": "Redirect",
        "meeting_opinion": "样片结果暴露高温稳定性风险，完成根因定位和回归验证前不得进入设计冻结。",
        "signoffs": [
            ("宋祖防", "正常", "Go（逾期）", ""),
            ("高腾飞", "正常", "Redirect", "高温样片数据超过技术基线，尚不能证明方案达到冻结条件。"),
            ("高大宇", "挂会", "TBD", ""),
            ("滕帅", "部分参加", "Go with Risk", "射频校准偏差集中在高温区间，需要增加分段补偿。"),
            ("林世杰", "正常", "Go", ""),
            ("罗勇平", "正常", "Redirect", "结构热路径与仿真假设不一致，需要重新核对边界条件。"),
            ("梅傲寒", "正常", "TBD", ""),
            ("吴贞奇", "正常", "Go", ""),
            ("赵阳", "正常", "Go（逾期）", ""),
            ("杨凯", "部分参加", "Redirect", "回归测试尚未覆盖高温连续运行和恢复场景。"),
            ("刘振岩", "正常", "Go with Risk（逾期）", "关键风险已识别，但关闭证据提交晚于会签时限。"),
        ],
        "problems": [
            (
                "TDR2-1",
                "高腾飞、滕帅、刘振岩",
                "高温条件下链路性能下降，样片结果超出TDR1技术基线。",
                "完成根因分层定位，增加高温分段校准并重新执行全链路回归。",
                "连续高温运行8小时无异常，链路余量不低于3 dB，三轮回归结果一致。",
                "06.08：校准方案已合入，第二轮回归通过。",
                "open",
            ),
            (
                "TDR2-2",
                "罗勇平、杨凯",
                "结构热路径假设与实测不一致，高温连续运行场景覆盖不足。",
                "重新标定热仿真边界，并增加高温连续运行与恢复测试。",
                "",
                "06.05：边界条件已重算，测试通过条件待补充。",
                "open",
            ),
        ],
    },
    "TDR3": {
        "date": date(2026, 8, 6),
        "meeting_conclusion": "Go with Risk",
        "meeting_opinion": "核心指标已达到目标，遗留的量产一致性和长期稳定性问题可按计划并行关闭。",
        "signoffs": [
            ("宋祖防", "部分参加", "Go", ""),
            ("高腾飞", "正常", "Go", ""),
            ("高大宇", "部分参加", "Go", ""),
            ("滕帅", "正常", "Go with Risk", "量产校准参数尚未覆盖全部器件批次，需要补充抽样策略。"),
            ("林世杰", "正常", "Go（逾期）", ""),
            ("罗勇平", "正常", "Go", ""),
            ("梅傲寒", "挂会", "TBD", ""),
            ("吴贞奇（代理：李俊）", "改派（部分）", "Go", ""),
            ("赵阳", "正常", "Go with Risk", "量产一致性风险需要通过三批次试产数据确认。"),
            ("杨凯", "正常", "Go with Risk", "长期稳定性测试已启动，但尚未达到完整周期。"),
            ("刘振岩", "缺席未改派", "Go", ""),
        ],
        "problems": [
            (
                "TDR3-1",
                "赵阳、杨凯",
                "量产一致性和长期稳定性证据尚未覆盖完整批次与周期。",
                "完成三批次试产抽检，并持续执行500小时稳定性测试。",
                "三批次关键指标通过率不低于99%；500小时测试无严重故障。",
                "08.10：首批试产通过，稳定性测试累计180小时。",
                "open",
            ),
            (
                "TDR3-2",
                "滕帅",
                "量产校准参数对器件批次差异的覆盖范围待确认。",
                "补充跨批次抽样并更新校准参数边界。",
                "",
                "08.09：已完成抽样方案，判定阈值待补充。",
                "open",
            ),
        ],
    },
}


def excel_serial(value: date) -> int:
    return (value - date(1899, 12, 30)).days


def sheet_paths(archive: ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationships.findall(f"{{{PKG_REL_NS}}}Relationship")
    }
    paths: dict[str, str] = {}
    for sheet in workbook.findall(f"{{{MAIN_NS}}}sheets/{{{MAIN_NS}}}sheet"):
        relation_id = sheet.attrib[f"{{{DOC_REL_NS}}}id"]
        target = rel_targets[relation_id].lstrip("/")
        paths[sheet.attrib["name"]] = (
            target if target.startswith("xl/") else posixpath.normpath(f"xl/{target}")
        )
    return paths


def set_cell(root: ET.Element, reference: str, value: object) -> None:
    cell = root.find(f".//{{{MAIN_NS}}}c[@r='{reference}']")
    if cell is None:
        raise ValueError(f"模板缺少单元格{reference}")
    for child in list(cell):
        if child.tag in {
            f"{{{MAIN_NS}}}f",
            f"{{{MAIN_NS}}}v",
            f"{{{MAIN_NS}}}is",
        }:
            cell.remove(child)
    if value is None or value == "":
        cell.attrib.pop("t", None)
        return
    if isinstance(value, date):
        cell.attrib["t"] = "n"
        ET.SubElement(cell, f"{{{MAIN_NS}}}v").text = str(excel_serial(value))
        return
    cell.attrib["t"] = "inlineStr"
    inline_string = ET.SubElement(cell, f"{{{MAIN_NS}}}is")
    text = ET.SubElement(inline_string, f"{{{MAIN_NS}}}t")
    text.attrib[f"{{{XML_NS}}}space"] = "preserve"
    text.text = str(value)


def build_sheet(xml_bytes: bytes, stage: str, session: dict[str, object]) -> bytes:
    root = ET.fromstring(xml_bytes)
    basics = {
        "B3": "虚拟智能终端协同增强（TRAIN-001）",
        "B4": stage,
        "B5": session["date"].isoformat(),
        "B6": "虚拟项目经理甲",
        "B7": session["meeting_conclusion"],
        "B8": session["meeting_opinion"],
    }
    for reference, value in basics.items():
        set_cell(root, reference, value)

    signoffs = session["signoffs"]
    if len(signoffs) != len(EXPERTS):
        raise ValueError(f"{stage}会签人数不是{len(EXPERTS)}人")
    for row_number, signoff in enumerate(signoffs, start=13):
        for column, value in zip("BCDE", signoff, strict=True):
            set_cell(root, f"{column}{row_number}", value)
    for column in "BCDE":
        set_cell(root, f"{column}24", None)

    problems = session["problems"]
    for row_number in range(29, 35):
        values = problems[row_number - 29] if row_number - 29 < len(problems) else (None,) * 7
        for column, value in zip("ABCDEFG", values, strict=True):
            set_cell(root, f"{column}{row_number}", value)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def generate(template: Path, output: Path, *, overwrite: bool = False) -> None:
    if output.exists() and not overwrite:
        raise FileExistsError(f"输出文件已存在：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(template, "r") as source:
        paths = sheet_paths(source)
        replacements = {
            paths[stage]: build_sheet(source.read(paths[stage]), stage, session)
            for stage, session in SESSIONS.items()
        }
        with ZipFile(output, "w", ZIP_DEFLATED) as destination:
            for info in source.infolist():
                destination.writestr(info, replacements.get(info.filename, source.read(info.filename)))


def main() -> None:
    parser = argparse.ArgumentParser(description="基于TDRX模板生成虚拟训练评审报告")
    parser.add_argument("template", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    arguments = parser.parse_args()
    generate(
        arguments.template.resolve(),
        arguments.output.resolve(),
        overwrite=arguments.overwrite,
    )
    print(arguments.output.resolve())


if __name__ == "__main__":
    main()
