"""@brief AI:独立核验PCB实体、网络、原理图关联、四层板及天线规则区。"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path
import pcbnew as pcb


def main():
    """@brief AI:读取已保存PCB及CLI网表，验证导入完整性并汇总未布线状态。
    @return None；任何完整性差异、布局违规或原理图一致性问题均以非零退出。
    """
    project=Path(__file__).resolve().parents[1]/"kicad"
    board=pcb.LoadBoard(str(project/"AI_MCUTOOL.kicad_pcb"))
    xml=ET.parse(project/"verification/netlist.xml").getroot()
    expected={}
    for net in xml.findall("./nets/net"):
        name=net.get("name")
        if name.startswith("unconnected-"): name=name.replace("/","{slash}")
        for node in net.findall("node"): expected[(node.get("ref"),node.get("pin"))]=name
    components={c.get("ref"):c for c in xml.findall("./components/comp")}
    fps=list(board.GetFootprints()); actual={}; errors=[]
    if len(fps)!=len(components) or {f.GetReference() for f in fps}!=set(components):
        errors.append("器件数量/位号不符")
    for fp in fps:
        ref=fp.GetReference()
        if ref not in components: continue
        comp=components[ref]
        expected_path=comp.find("sheetpath").get("tstamps")+comp.findtext("tstamps").split()[0]
        if fp.GetPath().AsString()!=expected_path: errors.append(ref+"原理图UUID关联不符")
        if fp.GetFPIDAsString()!=comp.findtext("footprint"): errors.append(ref+"库关联不符")
        for pad in fp.Pads():
            if not pad.GetNumber(): continue
            key=(ref,pad.GetNumber()); name=pad.GetNetname()
            if key in actual and actual[key]!=name: errors.append(ref+"重复编号铜盘归网矛盾")
            actual[key]=name
    if actual!=expected: errors.append("508个逻辑端子与网表不一致")
    if board.GetCopperLayerCount()!=4: errors.append("铜层数不为4")
    module=next(f for f in fps if f.GetReference()=="U4")
    zones=list(module.Zones())
    if len(zones)!=1:
        errors.append("天线规则区数量错误")
    else:
        zone=zones[0]
        if not (zone.GetIsRuleArea() and zone.GetDoNotAllowTracks() and zone.GetDoNotAllowVias()
                and zone.GetDoNotAllowPads() and zone.GetDoNotAllowZoneFills() and zone.GetDoNotAllowFootprints()):
            errors.append("天线禁布规则缺失")
        if not all(zone.GetLayerSet().Contains(layer) for layer in (pcb.F_Cu,pcb.In1_Cu,pcb.In2_Cu,pcb.B_Cu)):
            errors.append("天线禁布未覆盖四个铜层")
    drc=json.loads((project/"verification/pcb-drc.json").read_text("utf-8"))
    if drc["violations"]: errors.append("布局DRC存在违规")
    if drc["schematic_parity"]: errors.append("CLI原理图一致性存在问题")
    report={"passed":not errors,"components":len(fps),"logicalPins":len(actual),
            "physicalNumberedPads":sum(bool(p.GetNumber()) for f in fps for p in f.Pads()),
            "copperLayers":board.GetCopperLayerCount(),"tracksAndVias":len(list(board.GetTracks())),
            "layoutViolations":len(drc["violations"]),"schematicParityIssues":len(drc["schematic_parity"]),
            "unconnectedItems":len(drc["unconnected_items"]),"errors":errors,
            "stage":"未布线布局初稿；通过本检查不代表已完成布线、散热、外壳或制造验收"}
    (project/"verification/pcb-layout-check.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps(report,ensure_ascii=False))
    if errors: raise SystemExit(1)


if __name__=="__main__": main()
