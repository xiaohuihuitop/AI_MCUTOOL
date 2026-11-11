"""@brief AI:使用KiCad独立导出结果检查迁移连接、NC、BOM及封装脚号。"""
import argparse
import csv
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from kicad_sexpr import parse, children, child
from verify_kicad_footprints import check_geometry

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "hardware/kicad"


def main():
    """@brief AI:导出后逐端点核对已确认电路，并保存可审查的JSON结果。
    @return None；CLI失败或任何不一致时以非零状态退出。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kicad-cli", type=Path, default=Path("D:/Application/kicad/install/bin/kicad-cli.exe"))
    parser.add_argument("--footprints", type=Path, default=Path("D:/Application/kicad/install/share/kicad/footprints"))
    args = parser.parse_args()
    out = PROJECT / "verification"
    out.mkdir(exist_ok=True)
    schematic = PROJECT / "AI_MCUTOOL.kicad_sch"
    jobs = [
        ["sch","export","netlist","--format","kicadxml","-o",str(out/"netlist.xml")],
        ["sch","erc","--format","json","--severity-all","--exit-code-violations","-o",str(out/"erc.json")],
        ["sch","export","bom","--fields","Reference,Value,Manufacturer Part,Footprint,QUANTITY,Footprint Status","--labels","位号,图纸值,制造商料号,封装,数量,封装状态","-o",str(PROJECT/"AI_MCUTOOL-BOM.csv")],
    ]
    results = []
    for job in jobs:
        run = subprocess.run([str(args.kicad_cli),*job,str(schematic)],capture_output=True,text=True,encoding="utf-8",errors="replace")
        results.append({"command":job,"exitCode":run.returncode,"output":run.stdout+run.stderr})
        if run.returncode:
            (out/"cli-failure.json").write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n","utf-8")
            raise RuntimeError(results[-1])
    # AI:回归基准来自修复前已核端点快照，固定读取，不自动接受当前输出为新基准。
    binding_path = PROJECT/"connectivity-baseline.json"
    baseline = json.loads(binding_path.read_text("utf-8"))
    components = baseline["components"]
    expected = defaultdict(set)
    nc = set()
    all_pins = set()
    by_ref = {c["ref"]:c for c in components}
    for c in components:
        for pin, net in c["pins"].items():
            endpoint = (c["ref"],pin)
            all_pins.add(endpoint)
            if net is None:
                nc.add(endpoint)
            else:
                expected[net].add(endpoint)
    xml = ET.parse(out/"netlist.xml").getroot()
    errors = []
    actual = {}
    actual_nc = set()
    occurrences = Counter()
    for net in xml.findall("./nets/net"):
        nodes = [n for n in net.findall("node") if not n.attrib["ref"].startswith("#")]
        endpoints = frozenset((n.attrib["ref"],n.attrib["pin"]) for n in nodes)
        occurrences.update(endpoints)
        if net.attrib["name"].startswith("unconnected-"):
            actual_nc.update(endpoints)
            if len(nodes)!=1 or "no_connect" not in nodes[0].attrib.get("pintype",""):
                errors.append("NC网络缺少明确标记: "+net.attrib["name"])
        else:
            actual[endpoints] = net.attrib["name"]
    if nc!=actual_nc:errors.append("NC集合不一致")
    if set(occurrences)!=all_pins or any(n!=1 for n in occurrences.values()):errors.append("物理引脚缺失、重复或额外出现")
    expected_sets = {frozenset(v) for v in expected.values()}
    if expected_sets!=set(actual):errors.append("连接网络端点集合不一致")
    matches = [{"designNet":name,"kicadNet":actual.get(frozenset(pins)),"pins":[".".join(v) for v in sorted(pins)]} for name,pins in expected.items()]
    actual_components = {c.attrib["ref"]:c for c in xml.findall("./components/comp")}
    if set(actual_components)!=set(by_ref):errors.append("实体器件集合不一致")
    with (PROJECT/"AI_MCUTOOL-BOM.csv").open(encoding="utf-8-sig",newline="") as stream:
        bom = list(csv.DictReader(stream))
    if {r["位号"] for r in bom}!=set(by_ref) or len(bom)!=len(by_ref) or sum(int(r["数量"]) for r in bom)!=len(by_ref):
        errors.append("BOM存在缺失、重复或错误数量")
    footprints = []
    unbound = []
    for ref,c in actual_components.items():
        assigned = c.findtext("footprint")
        if not assigned:
            unbound.append(ref)
            continue
        library,name = assigned.split(":",1)
        path = PROJECT/"AI_MCUTOOL.pretty"/(name+".kicad_mod") if library=="AI_MCUTOOL" else args.footprints/(library+".pretty")/(name+".kicad_mod")
        pads = {str(p[1]) for p in children(parse(path.read_text("utf-8")),"pad") if p[1]}
        missing = set(by_ref[ref]["pins"])-pads
        if missing:errors.append(f"{ref}封装缺少焊盘: {sorted(missing)}")
        footprints.append({"ref":ref,"footprint":assigned,"missingPads":sorted(missing)})
    if unbound:errors.append("存在未绑定封装的实体器件: "+", ".join(sorted(unbound)))
    # AI:脚号集合无法发现镜像，另外检查输出封装的编号方向和装配边界。
    geometry_checks, geometry_errors = check_geometry(PROJECT)
    errors.extend(geometry_errors)
    erc = json.loads((out/"erc.json").read_text("utf-8"))
    violations = [v for sheet in erc["sheets"] for v in sheet["violations"]]
    if violations:errors.append("ERC存在违规")
    symbol_units = 0
    hashes = {}
    for path in sorted(PROJECT.glob("*.kicad_sch")):
        document = parse(path.read_text("utf-8"))
        symbol_units += sum(1 for s in children(document,"symbol") if not next(p[2] for p in children(s,"property") if p[1]=="Reference").startswith("#"))
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = {
        "passed":not errors,"kicadVersion":erc["kicad_version"],"date":erc["date"],
        "sheets":len(xml.findall("./design/sheet")),"components":len(actual_components),"symbolUnits":symbol_units,
        "physicalPins":len(occurrences),"connectedPins":len(all_pins)-len(nc),"connectedNets":len(actual),"ncPins":len(actual_nc),
        "netDifferences":len(expected_sets-set(actual))+len(set(actual)-expected_sets),"bomQuantity":sum(int(r["数量"]) for r in bom),
        "ercViolations":len(violations),"ercDefaultIgnoredChecks":erc.get("ignored_checks",[]),
        "unboundFootprints":sorted(unbound),"footprintChecks":footprints,"netMapping":matches,
        "footprintGeometryChecks":geometry_checks,
        "bindingSha256":baseline["originalBindingSha256"],
        "baselineSha256":hashlib.sha256(binding_path.read_bytes()).hexdigest(),"schematicSha256":hashes,
        "errors":errors,"cli":results,
    }
    (out/"check.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({k:report[k] for k in ["passed","sheets","components","symbolUnits","physicalPins","connectedNets","ncPins","netDifferences","ercViolations","unboundFootprints","errors"]},ensure_ascii=False))
    if errors:raise SystemExit(1)


if __name__=="__main__":main()
