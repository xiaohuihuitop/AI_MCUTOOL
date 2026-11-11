"""@brief AI:以华秋pcbnew实际载入封装，检查网表到铜焊盘的完整映射；不生成或覆盖PCB。"""
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pcbnew


def inspect(project, libraries):
    """@brief AI:按当前导出网表核验每个可导入封装的引脚、重复铜盘及原理图路径。
    @param project 含verification/netlist.xml的KiCad工程目录。
    @param libraries 当前华秋KiCad标准封装库目录。
    @return 检查结果字典；未绑定器件独立列出，不视作完整导入成功。
    """
    xml = ET.parse(project / "verification/netlist.xml").getroot()
    endpoints = {}
    for net in xml.findall("./nets/net"):
        for node in net.findall("node"):
            key = (node.get("ref"), node.get("pin"))
            if key in endpoints:
                raise ValueError("端点重复归网: " + str(key))
            endpoints[key] = net.get("name")
    pending, errors, records = [], [], []
    for component in xml.findall("./components/comp"):
        ref = component.get("ref")
        assigned = component.findtext("footprint")
        if not assigned:
            pending.append(ref)
            continue
        library, name = assigned.split(":", 1)
        directory = project / "AI_MCUTOOL.pretty" if library == "AI_MCUTOOL" else libraries / (library + ".pretty")
        footprint = pcbnew.FootprintLoad(str(directory), name)
        if footprint is None:
            errors.append(ref + ": 华秋pcbnew无法载入封装")
            continue
        expected = {pin for item_ref, pin in endpoints if item_ref == ref}
        pads = [pad for pad in footprint.Pads() if pad.GetNumber()]
        numbers = {pad.GetNumber() for pad in pads}
        if numbers != expected:
            errors.append(ref + ": 符号脚号与铜焊盘不一致，缺少" + str(sorted(expected-numbers)) + "，额外" + str(sorted(numbers-expected)))
        stamps = component.findtext("tstamps").split()
        # AI:多单元器件的多个符号UUID不能误当作多个实体封装；此处记录完整来源供导入使用。
        sheet_path = component.find("sheetpath").get("tstamps")
        records.append({"ref": ref, "footprint": assigned, "numberedCopperPads": len(pads),
                        "uniquePadNumbers": len(numbers), "symbolUuids": stamps, "sheetPath": sheet_path,
                        "pads": [{"number": p.GetNumber(), "net": endpoints.get((ref, p.GetNumber()))} for p in pads]})
    return {"kicadVersion": pcbnew.GetBuildVersion(), "readyForCompleteImport": not pending and not errors,
            "boundFootprintsPassed": not errors, "checkedComponents": len(records),
            "pendingFootprints": pending, "errors": errors, "components": records,
            "scope": "本机原生封装加载及网表到焊盘映射；不是PCB布局、布线或制造验收"}


def main():
    """@brief AI:运行导入准备检查并写入报告。
    @return None；已有封装映射错误时退出1，尚未绑定的器件保留为报告中的阻塞项。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1] / "kicad")
    parser.add_argument("--libraries", type=Path, default=Path("D:/Application/kicad/install/share/kicad/footprints"))
    args = parser.parse_args()
    report = inspect(args.project, args.libraries)
    (args.project / "verification/pcb-import.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", "utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "components"}, ensure_ascii=False))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
