"""@brief AI:将已核连接数据和真实库记录绑定，生成专业版正式脚本入口使用的脚本。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "hardware/easyeda-pro/rev-a"
SCRIPTS = ROOT / "hardware/easyeda-pro/scripts"


def load(name):
    """@brief AI:读取UTF-8设计数据。
    @param name 数据目录内文件名。
    @return 解析的JSON对象。
    """
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def source_pins(source):
    """@brief AI:按真实符号ATTR关联引脚，保留多子部件边界。
    @param source 编辑器导出的符号源文档。
    @return 子部件名称到引脚号集合的映射。
    """
    result = {}
    for line in source.splitlines():
        head, body = line.split("||", 1)
        head, body = json.loads(head), json.loads(body.rstrip("|"))
        if head["type"] == "ATTR" and body["key"] == "Pin Number":
            result.setdefault(body["partId"], []).append(str(body["value"]))
    return result


def main():
    """@brief AI:生成准确脚号映射、分页放置清单和一次性绘图脚本。
    @return None；输出binding.json及逐页绘图脚本，不直接操作云端。
    """
    design = load("design.json")
    records = {}
    for filename in ["library-records.json", "passives-connectors.json", "passive-records.json"]:
        records.update({r["name"]: r for r in load(filename)["records"]})
    records["WSK2512R0200BEA"] = dict(records["WSK2512R0100DEA"], device=load("u1-wired-shunt.json")["shunt"])
    resistors = {
        "4.7k": "RC0603FR-074K7L", "5.1k": "RC0603FR-075K1L",
        "10k": "RC0603FR-0710KL", "1k": "RC0603FR-071KL",
        "240": "RC0603FR-07240RL", "680": "RC0603FR-07680RL",
        "330": "RC0603FR-07330RL", "100": "RC0603FR-07100RL",
        "10": "RC0603FR-0710RL", "100k": "RC0603FR-07100KL",
        "470k": "RC0603FR-07470KL", "499": "TNPW0603499RBEEA",
    }
    capacitors = {
        "100nF": "GRM188R71H104KA93D", "1uF": "GRM188R71C105KA12D",
        "4.7uF": "GRM21BR71C475KA73L", "22uF": "GRM21BR61C226ME44L",
        "10nF": "GRM1885C1H103JA01D", "10uF": "GRM21BR61C106KE15L",
    }
    bound = []
    for part in design["components"]:
        ref = part["ref"]
        nets = {p["number"]: p["net"] for p in part["pins"]}
        key = part["mpn"]
        if key == "TLP176AM(TPL,E":
            key = "TLP176AM_C6285455"
        if ref == "J1":
            key = "DC_005_2.1"
            nets = {"1": nets["POS"], "2": nets["NEG"], "3": None}
        elif ref == "J2":
            key = "TYPE-C-31-M-12"
            nets = {**{p: "TYPEC_IN_5V" for p in ["A4B9", "B4A9"]},
                    **{p: "COMMON_GND" for p in ["A1B12", "B1A12", "1", "2", "3", "4"]},
                    "A5": "TYPEC_CC1", "B5": "TYPEC_CC2",
                    **{p: None for p in ["A6", "A7", "A8", "B6", "B7", "B8"]}}
        elif ref.startswith("J"):
            key = {2: "HEADER_2", 3: "HDR-M_2.54_1x3P", 5: "HDR-M_2.54_1x5P"}[len(nets)]
        elif ref.startswith("SW"):
            key = "TS-1187A-B-A-B"
            # AI:真实符号中1/2内部相连、3/4内部相连；不能把逻辑A/B映射成1/2。
            nets = {"1": nets["A"], "2": nets["A"], "3": nets["B"], "4": nets["B"]}
        elif ref.startswith("LED"):
            key = "LTST-C190KRKT" if ref == "LED1" else "LTST-C190KGKT"
            nets = {"1": nets["K"], "2": nets["A"]}
        elif ref == "RSH1":
            nets = {"1": nets["I2"], "2": nets["E2"], "3": nets["E1"], "4": nets["I1"]}
        elif ref.startswith("R") and not key:
            key = resistors[part["value"]]
            if part["package"] == "1206" and part["value"] == "100":
                key = "RC1206FR-07100RL"
            if ref in ["R47", "R56", "R65", "R74"]:
                key = "TNPW0603100KBEEA"
        elif ref.startswith("C"):
            key = capacitors[part["value"]]
        if ref == "U3":
            nets["4"] = "TOOL_3V3"
        # AI:专业版把网络名规范为大写；UART_TX_nOE对应UART_TX_NOE，连接语义不变。
        nets = {pin: net.upper() if net is not None else None for pin, net in nets.items()}
        record = records[key]
        unit_pins = source_pins(record["symbolSource"])
        assert set(nets) == {p for pins in unit_pins.values() for p in pins}, (ref, nets, unit_pins)
        device = record["device"]
        item = {"ref": ref, "page": part["page"], "value": part["value"],
                "device": {"uuid": device["uuid"], "libraryUuid": device["libraryUuid"]},
                "library_name": key, "manufacturerId": device["property"].get("manufacturerId", ""),
                "pins": nets, "units": unit_pins, "note": part["note"]}
        bound.append(item)
    pages = load("native-pages.json")["pages"]
    for page in pages:
        items = [p for p in bound if p["page"] == page["id"]]
        # AI:U1沿用已经验证的放置及连线；每个器件保留独立阅读空间。
        if page["id"] == "01":
            items.sort(key=lambda p: p["ref"] != "U1")
        slots = []
        for item in items:
            for index, (unit, pins) in enumerate(item["units"].items()):
                slot = len(slots)
                slots.append({**item, "unit": unit, "pins": {p: item["pins"][p] for p in pins},
                              "unitIndex": index, "x": 260 + (slot % 5) * 350,
                              "y": 220 - (slot // 5) * 260})
        page["slots"] = slots
    out = {"projectUuid": load("native-pages.json")["projectUuid"], "components": bound, "pages": pages}
    (DATA / "binding.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    template = (SCRIPTS / "build-schematic.template.js").read_text(encoding="utf-8")
    for page in pages:
        selected = {"projectUuid": out["projectUuid"], "pages": [page]}
        (SCRIPTS / f"build-page-{page['id']}.js").write_text("const DESIGN = " + json.dumps(selected, ensure_ascii=False) + ";\n" + template, encoding="utf-8")
    print(f"绑定{len(bound)}颗器件，{sum(len(x['pins']) for x in bound)}个物理引脚，{sum(len(x['slots']) for x in pages)}个符号子部件")


if __name__ == "__main__":
    main()
