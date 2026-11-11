"""@brief AI:从KiCad官方标准库及已核引脚表建立项目局部符号库。"""
from copy import deepcopy
import json
from pathlib import Path
from kicad_sexpr import Atom as A, child, children, parse, dumps

ROOT = Path(__file__).resolve().parents[2]
INSTALL = Path("D:/Application/kicad/install/share/kicad")
OUT = ROOT / "hardware/kicad"
G = 1.27
CACHE = {}


def n(key, *args):
    """@brief AI:构造S表达式节点。
    @param key KiCad关键字。
    @param args 节点值。
    @return 节点列表。
    """
    return [A(key), *args]


def effects(size=1.0, hide=False, justify=None):
    """@brief AI:生成统一文字样式。
    @param size 字高毫米。
    @param hide 是否隐藏。
    @param justify 对齐关键字列表。
    @return effects节点。
    """
    e = n("effects", n("font", n("size", size, size)))
    if justify:
        e.append(n("justify", *map(A, justify)))
    if hide:
        e.append(n("hide", A("yes")))
    return e


def prop(key, value, x=0, y=0, hide=True):
    """@brief AI:构造符号属性。
    @param key 属性名。
    @param value 属性值。
    @param x 位置毫米。
    @param y 位置毫米。
    @param hide 是否隐藏。
    @return property节点。
    """
    return n("property", key, value, n("at", x, y, 0), effects(hide=hide))


def standard(library, name):
    """@brief AI:展开标准库继承，保留官方图形与引脚类型。
    @param library 标准库名称。
    @param name 符号名称。
    @return 独立符号定义副本。
    """
    if library not in CACHE:
        CACHE[library] = {x[1]: x for x in children(parse((INSTALL / "symbols" / (library + ".kicad_sym")).read_text("utf-8")), "symbol")}
    item = deepcopy(CACHE[library][name])
    base = child(item, "extends")
    if base:
        result = standard(library, base[1])
        old = result[1]
        result[1] = name
        overrides = {p[1]: p for p in children(item, "property")}
        result = [v for v in result if not (isinstance(v, list) and v[0] == "property" and v[1] in overrides)]
        result.extend(overrides.values())
        for sub in children(result, "symbol"):
            sub[1] = name + sub[1][len(old):]
        return result
    return item


def rename(symbol, name):
    """@brief AI:为复制的标准符号设置项目唯一名称。
    @param symbol 独立符号节点。
    @param name 项目库名称。
    @return 重命名后的副本。
    """
    symbol = deepcopy(symbol)
    old = symbol[1]
    symbol[1] = name
    for sub in children(symbol, "symbol"):
        sub[1] = name + sub[1][len(old):]
    for p in children(symbol, "property"):
        if p[1] == "Value":
            p[2] = name
    return symbol


def line(points):
    """@brief AI:生成符号内的非电气图形线。
    @param points 以1.27mm为单位的点列表。
    @return polyline节点。
    """
    return n("polyline", n("pts", *[n("xy", x * G, y * G) for x, y in points]), n("stroke", n("width", 0.254), n("type", A("default"))), n("fill", n("type", A("none"))))


def pin(number, name, kind, x, y, angle, length=2):
    """@brief AI:建立带真实脚号及电气类型的引脚。
    @param number 实际脚号。
    @param name 引脚功能名。
    @param kind KiCad电气类型。
    @param x,y 以1.27mm为单位的坐标。
    @param angle 朝向符号内部的角度。
    @param length 引脚长度，单位1.27mm。
    @return pin节点。
    """
    return n("pin", A(kind), A("line"), n("at", x * G, y * G, angle), n("length", length * G), n("name", name, effects(0.9)), n("number", str(number), effects(0.8)))


def basic(name, ref, body, pins):
    """@brief AI:建立缺失的项目专用符号。
    @param name 符号名称。
    @param ref 位号前缀。
    @param body 符号内部图形。
    @param pins 引脚节点。
    @return 完整库符号。
    """
    return n("symbol", name, n("pin_names", n("offset", 0.635)), n("in_bom", A("yes")), n("on_board", A("yes")), prop("Reference", ref, hide=False), prop("Value", name, hide=False), prop("Footprint", ""), prop("Datasheet", ""), n("symbol", name + "_0_1", *body), n("symbol", name + "_1_1", *pins))


def rect(x1, y1, x2, y2):
    """@brief AI:绘制IC或连接器轮廓。
    @param x1,y1,x2,y2 角点，单位1.27mm。
    @return rectangle节点。
    """
    return n("rectangle", n("start", x1 * G, y1 * G), n("end", x2 * G, y2 * G), n("stroke", n("width", 0.254), n("type", A("default"))), n("fill", n("type", A("background"))))


def allpins(symbol, unit=None):
    """@brief AI:展开指定符号单元的引脚。
    @param symbol 库符号。
    @param unit 单元编号；None返回全部。
    @return 引脚节点列表。
    """
    result = []
    for sub in children(symbol, "symbol"):
        u, body_style = map(int, sub[1].rsplit("_", 2)[1:])
        if body_style <= 1 and (unit is None or u in (0, unit)):
            result.extend(children(sub, "pin"))
    return result


def build():
    """@brief AI:构建项目库及逐位号绑定，完整保留508个引脚。
    @return 符号映射、器件到符号名称映射、封装映射。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = {}
    source = {
        "R": ("Device", "R"), "C": ("Device", "C"), "LED": ("Device", "LED"),
        "MMBT3904": ("Transistor_BJT", "MMBT3904"), "N_FET": ("Transistor_FET", "CSD17577Q3A"),
        "P_FET": ("Transistor_FET", "CSD25402Q3A"), "ESP32_S3_N16R8": ("RF_Module", "ESP32-S3-WROOM-1"),
        "LM66100": ("Power_Management", "LM66100DCK"), "INA228": ("Sensor_Energy", "INA228"),
        "ADS1115": ("Analog_ADC", "ADS1115IDGS"), "OPA4391": ("Amplifier_Operational", "LM2902"),
        "LM7705": ("Regulator_SwitchedCapacitor", "LM7705"), "TX_BUFFER": ("74xGxx", "74AUP1G125"),
        "RX_BUFFER": ("74xGxx", "74LVC1G17"), "SW4": ("Switch", "SW_Push"),
    }
    for name, (library, item) in source.items():
        symbols[name] = rename(standard(library, item), name)
    for name in ["N_FET", "P_FET"]:
        pins = allpins(symbols[name])
        five = next(p for p in pins if child(p, "number")[1] == "5")
        owner = next(s for s in children(symbols[name], "symbol") if five in s)
        existing = {child(p, "number")[1] for p in pins}
        for number in ["6", "7", "8", "9"]:
            if number not in existing:
                p = deepcopy(five)
                child(p, "number")[1] = number
                # AI:右侧五个焊盘在器件内同电位，叠放仍逐个保留实际编号。
                child(p, "name")[2].append(n("hide", A("yes")))
                child(p, "number")[2].append(n("hide", A("yes")))
                owner.append(p)
    for p in allpins(symbols["LM66100"]):
        number = child(p, "number")[1]
        if number == "4":
            # AI:此NC脚允许接地；符号保留脚号，避免标为禁止连接。
            p[1] = A("passive")
        if number == "6":
            # AI:理想二极管ORing输出不是推挽驱动，汇合节点用PWR_FLAG声明供电。
            p[1] = A("passive")
    # AI:本项目ST按TI手册固定接GND，采用专用被动端模型；下面强制校验，禁止作为通用ST输出符号复用。
    symbols["LM66100"] = basic("LM66100", "U", [rect(-5,6,5,-6)], [pin(1,"VIN","power_in",-7,4,0),pin(3,"~{CE}","input",-7,0,0),pin(4,"NC","passive",-7,-4,0),pin(6,"VOUT","passive",7,4,180),pin(5,"ST_GND","passive",7,0,180),pin(2,"GND","power_in",0,-8,90)])
    sw_pins = allpins(symbols["SW4"])
    owner = next(s for s in children(symbols["SW4"], "symbol") if sw_pins[0] in s)
    child(sw_pins[1], "number")[1] = "3"
    for p, number in [(sw_pins[0], "2"), (sw_pins[1], "4")]:
        extra = deepcopy(p)
        child(extra, "number")[1] = number
        owner.append(extra)
    symbols["LDL1117"] = basic("LDL1117", "U", [rect(-5, 4, 5, -4)], [pin(3, "IN", "power_in", -7, 2, 0), pin(2, "OUT", "power_out", 7, 2, 180), pin(4, "TAB", "passive", 7, 2, 180), pin(1, "GND", "power_in", 0, -6, 90)])
    for count in [2, 3, 5]:
        for side in ["L", "R"]:
            name = f"HDR{count}_{side}"
            symbols[name] = basic(name, "J", [rect(-2, 1, 2, -2 * count + 1)], [pin(i+1, "", "passive", -4 if side == "L" else 4, -2*i, 0 if side == "L" else 180) for i in range(count)])
    symbols["DC_IN"] = basic("DC_IN", "J", [rect(-4, 4, 4, -6), line([(-3, 2), (2, 2)]), line([(-2, -2), (2, -2)]), line([(0, -4), (2, -2)])], [pin(1, "+", "passive", 6, 2, 180), pin(2, "-", "passive", 6, -2, 180), pin(3, "SW", "passive", 6, -4, 180)])
    usb_pins = [pin(p, "VBUS", "passive", 10, 10, 180) for p in ["A4B9", "B4A9"]]
    usb_pins += [pin(p, "GND", "passive", 0, -14, 90) for p in ["A1B12", "B1A12", "1", "2", "3", "4"]]
    usb_pins += [pin("A5", "CC1", "passive", 10, 4, 180), pin("B5", "CC2", "passive", 10, 0, 180)]
    usb_pins += [pin(p, p, "passive", -10, 8-3*i, 0) for i, p in enumerate(["A6", "A7", "A8", "B6", "B7", "B8"])]
    symbols["USB_POWER"] = basic("USB_POWER", "J", [rect(-8, 12, 8, -12)], usb_pins)
    led_body = [rect(-7, 5, 7, -5), line([(-3, 2), (-3, -2)]), line([(-5, 1), (-3, -2), (-1, 1), (-5, 1)]), line([(0, 1), (2, 2)]), line([(0, -1), (2, 0)])]
    symbols["PHOTO_MOS"] = basic("PHOTO_MOS", "U", led_body + [line([(3, 3), (3, -1), (5, 1), (5, -3)])], [pin(1,"A","passive",-9,3,0),pin(3,"K","passive",-9,-3,0),pin(4,"CONTACT_A","passive",9,3,180),pin(6,"CONTACT_B","passive",9,-3,180)])
    symbols["PHOTO_PV"] = basic("PHOTO_PV", "U", led_body + [line([(3, 2),(5, 2)]),line([(4, 3),(4, 1)]),line([(3,-2),(5,-2)])], [pin(1,"A","passive",-9,3,0),pin(2,"K","passive",-9,-3,0),pin(4,"PV+","output",9,3,180),pin(3,"PV-","passive",9,-3,180)])
    symbols["SHUNT4"] = basic("SHUNT4", "RSH", [rect(-4,2,4,-2),line([(-6,3),(-6,-3)]),line([(6,3),(6,-3)]),line([(-6,0),(-4,0)]),line([(4,0),(6,0)])], [pin(4,"I1","passive",-8,3,0),pin(3,"E1","passive",-8,-3,0),pin(1,"I2","passive",8,3,180),pin(2,"E2","passive",8,-3,180)])
    for net in ["COMMON_GND", "TOOL_3V3", "VNEG", "LDO_VIN"]:
        body = [line([(0,0),(0,2),(-1,1),(0,2),(1,1)])] if net != "COMMON_GND" else [line([(0,0),(0,-1),(-2,-1),(0,-3),(2,-1),(0,-1)])]
        if net == "VNEG":
            body = [line([(0,0),(0,-2),(-1,-1),(0,-2),(1,-1)])]
        sym = basic(net, "#PWR", body, [pin(1,net,"power_in",0,0,90,0)])
        child(sym,"pin_names").append(n("hide", A("yes")))
        sym.insert(2,n("pin_numbers",n("hide",A("yes"))))
        sym.insert(2,n("power"))
        child(sym,"in_bom")[1]=A("no");child(sym,"on_board")[1]=A("no")
        symbols[net]=sym
    # AI:堆叠焊盘保留全部真实脚号，只显示一根引脚，避免文字重叠。
    for name, symbol in symbols.items():
        for sub in children(symbol, "symbol"):
            seen = set()
            for p in children(sub, "pin"):
                position = tuple(child(p,"at")[1:])
                if position in seen:
                    p.append(n("hide",A("yes")))
                seen.add(position)
    symbols["PWR_FLAG"] = rename(standard("power","PWR_FLAG"),"PWR_FLAG")
    # AI:按键符号内部已绘出隔离触点，隐藏长名称避免覆盖触点图形，脚号保持可见。
    child(symbols["PHOTO_MOS"],"pin_names").append(n("hide",A("yes")))
    binding = json.loads((ROOT / "hardware/easyeda-pro/rev-a/binding.json").read_text("utf-8"))["components"]
    footprints = {}; mapping = {}
    chip_map = {"U1":"LM66100","U2":"LM66100","U3":"LDL1117","U4":"ESP32_S3_N16R8",**{f"U{i}":"PHOTO_MOS" for i in range(5,10)},"U10":"PHOTO_PV","U11":"PHOTO_PV","U12":"INA228","U13":"ADS1115","U14":"OPA4391","U15":"LM7705","U16":"TX_BUFFER","U17":"RX_BUFFER"}
    for c in binding:
        ref=c["ref"]
        if ref in chip_map:name=chip_map[ref]
        elif ref=="J1":name="DC_IN"
        elif ref=="J2":name="USB_POWER"
        elif ref.startswith("J"):name=f"HDR{len(c['pins'])}_"+("R" if ref in ["J3","J9","J10","J12","J14","J15","J16","J17"] else "L")
        elif ref=="RSH1":name="SHUNT4"
        elif ref.startswith("R"):name="R"
        elif ref.startswith("C"):name="C"
        elif ref.startswith("SW"):name="SW4"
        elif ref.startswith("LED"):name="LED"
        elif c["library_name"]=="CSD17577Q3A":name="N_FET"
        elif c["library_name"]=="CSD25402Q3A":name="P_FET"
        else:name="MMBT3904"
        if name=="LM66100" and c["pins"]["5"]!="COMMON_GND":raise ValueError("LM66100专用符号仅允许ST接地")
        mapping[ref]=name
        numbers={child(p,"number")[1] for p in allpins(symbols[name])}
        if numbers!=set(c["pins"]):raise ValueError((ref,name,sorted(numbers),sorted(c["pins"])))
        fp = next((p[2] for p in children(symbols[name],"property") if p[1]=="Footprint"), "")
        if name=="R":
            size="1206" if c["library_name"].startswith(("TNPW1206","RC1206")) else "0805" if c["library_name"].startswith("TNPW0805") else "0603"
            fp=f"Resistor_SMD:R_{size}_{dict([('0603','1608'),('0805','2012'),('1206','3216')])[size]}Metric"
        elif name=="C":
            size="0805" if c["library_name"].startswith("GRM21") else "0603"
            fp=f"Capacitor_SMD:C_{size}_{'2012' if size=='0805' else '1608'}Metric"
        elif name.startswith("HDR"):fp=f"Connector_PinHeader_2.54mm:PinHeader_1x{len(c['pins']):02d}_P2.54mm_Vertical"
        elif name=="LED":fp="LED_SMD:LED_0603_1608Metric"
        elif name=="MMBT3904":fp="Package_TO_SOT_SMD:SOT-23"
        elif name in ["TX_BUFFER","RX_BUFFER"]:fp="Package_TO_SOT_SMD:SOT-23-5"
        elif name in ["N_FET","P_FET","SHUNT4","LDL1117"]:fp="AI_MCUTOOL:"+name
        elif name=="LM66100":fp="Package_TO_SOT_SMD:SOT-363_SC-70-6"
        elif name=="OPA4391":fp="Package_SO:TSSOP-14_4.4x5mm_P0.65mm"
        elif name in ["PHOTO_MOS","PHOTO_PV","SW4"]:fp="AI_MCUTOOL:"+name
        elif name in ["DC_IN","USB_POWER"]:fp=""
        footprints[ref]=fp
    (OUT/"AI_MCUTOOL.kicad_sym").write_text(dumps(n("kicad_symbol_lib",n("version",20241209),n("generator",A("kicad_symbol_editor")),*symbols.values()))+"\n","utf-8")
    (OUT/"sym-lib-table").write_text(dumps(n("sym_lib_table",n("version",7),n("lib",n("name","AI_MCUTOOL"),n("type","KiCad"),n("uri","${KIPRJMOD}/AI_MCUTOOL.kicad_sym"),n("options",""),n("descr","本项目已核脚号与绘图符号"))))+"\n","utf-8")
    from kicad_project_footprints import make_footprints
    make_footprints(ROOT,INSTALL,OUT,n,footprints)
    return symbols,mapping,footprints


if __name__=="__main__":
    s,m,f=build()
    print("符号",len(s),"器件",len(m))
