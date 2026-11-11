"""@brief AI:比较EDA实际网表与独立的物理脚号连接映射，不以绘图脚本成功代替连接检查。"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "hardware/easyeda-pro/rev-a"


def verify(text, binding):
    """@brief AI:逐端点检查网名、遗漏、额外端点和明确NC脚。
    @param text 编辑器导出的Protel2网表文本。
    @param binding 已核物理引脚定义。
    @return 检查计数和完整差异列表。
    """
    text = text.replace("\r", "")
    actual = {}
    errors = []
    for group in re.findall(r"^\(\n(.*?)^\)", text, re.M | re.S):
        lines = [line.strip() for line in group.splitlines() if line.strip()]
        net = lines[0]
        for line in lines[1:]:
            endpoint = line.split()[0]
            if endpoint in actual and actual[endpoint] != net:
                errors.append(f"重复端点: {endpoint} 同时属于 {actual[endpoint]} / {net}")
            actual[endpoint] = net
    expected = {f"{c['ref']}-{pin}": net for c in binding["components"] for pin, net in c["pins"].items() if net is not None}
    nc = {f"{c['ref']}-{pin}" for c in binding["components"] for pin, net in c["pins"].items() if net is None}
    for pin, net in expected.items():
        if actual.get(pin) != net:
            errors.append(f"{pin}: 预期{net}，实际{actual.get(pin, '缺失')}")
    for pin, net in actual.items():
        if pin not in expected:
            errors.append(f"额外端点: {pin}={net}" + ("（应为NC）" if pin in nc else ""))
    refs = re.findall(r"^DESIGNATOR\n+([^\n]+)", text, re.M)
    expected_refs = {c["ref"] for c in binding["components"]}
    if set(refs) != expected_refs:
        errors.append(f"位号集合不一致，缺失{sorted(expected_refs-set(refs))}，额外{sorted(set(refs)-expected_refs)}")
    if len(refs) != len(set(refs)):
        errors.append("网表存在重复器件位号")
    return {"passed": not errors, "components": len(refs), "connectedPins": len(actual), "expectedConnectedPins": len(expected), "ncPins": len(nc), "nets": len(set(actual.values())), "errors": errors}


def main():
    """@brief AI:读取真实下载结果并输出可复核检查报告。
    @return None；存在差异时进程非零退出。
    """
    binding = json.loads((DATA / "binding.json").read_text("utf-8"))
    report = json.loads((DATA / "native-verification.json").read_text("utf-8"))
    result = verify(report["netlist"], binding)
    # AI:同时核对原生NC属性的完整性及位置，避免未接脚虽然无网表却标记漂移。
    records = {}
    for filename in ["library-records.json", "passives-connectors.json", "passive-records.json"]:
        records.update({r["name"]: r for r in json.loads((DATA / filename).read_text("utf-8"))["records"]})
    parts = {c["ref"]: c for c in binding["components"]}
    seen_nc = set()
    for page in report["pages"]:
        page_rows = []
        for line in page["source"].splitlines():
            head, body = line.split("||", 1)
            page_rows.append((json.loads(head), json.loads(body.rstrip("|"))))
        components = {c["primitiveId"]: c for c in page["components"]}
        for head, body in page_rows:
            if head["type"] != "ATTR" or body["key"] != "NO_CONNECT":
                continue
            comp_id, pin_id = body["parentId"].split("-", 1)
            comp = components[comp_id]
            record = records[parts[comp["designator"]]["library_name"]]
            pin = None
            number = None
            for line in record["symbolSource"].splitlines():
                h, b = line.split("||", 1)
                h, b = json.loads(h), json.loads(b.rstrip("|"))
                if h["type"] == "PIN" and h["id"] == pin_id:
                    pin = b
                if h["type"] == "ATTR" and b.get("parentId") == pin_id and b["key"] == "Pin Number":
                    number = str(b["value"])
            endpoint = comp["designator"] + "-" + str(number)
            seen_nc.add(endpoint)
            if pin is None or abs(body["x"] - comp["x"] - pin["x"]) > 1e-6 or abs(body["y"] + comp["y"] - pin["y"]) > 1e-6:
                result["errors"].append(f"NC标记坐标不符: {endpoint}")
    expected_nc = {c["ref"] + "-" + n for c in binding["components"] for n, net in c["pins"].items() if net is None}
    if seen_nc != expected_nc:
        result["errors"].append(f"NC集合不一致: 缺失{sorted(expected_nc-seen_nc)}，额外{sorted(seen_nc-expected_nc)}")
    result["ncMarkersVerified"] = len(seen_nc)
    result["passed"] = not result["errors"]
    (DATA / "native-netlist-check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
