"""@brief AI:按功能电路重新绘制KiCad层次原理图，并保留独立连接校验依据。"""
import json
import math
import uuid
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from kicad_sexpr import Atom as A, child, children, dumps
from kicad_project_lib import build as build_library, allpins, effects, n, prop, G, OUT, ROOT

PROJECT = "AI_MCUTOOL"
NAMESPACE = uuid.UUID("fbb63381-2913-4993-8753-a5d4bbbf0fee")
BINDING = json.loads((ROOT / "hardware/easyeda-pro/rev-a/binding.json").read_text("utf-8"))
PARTS = {c["ref"]: c for c in BINDING["components"]}
SYMBOLS, MAPPING, FOOTPRINTS = build_library()
NET_PAGES = defaultdict(set)
for c in PARTS.values():
    for net in c["pins"].values():
        if net:
            NET_PAGES[net].add(c["page"])


def uid(key):
    """@brief AI:生成稳定的项目UUID。
    @param key 在项目内唯一的对象名。
    @return UUID字符串。
    """
    return str(uuid.uuid5(NAMESPACE, key))


def mm(value):
    """@brief AI:将1.27mm绘图网格转换为文件毫米坐标。
    @param value 网格坐标。
    @return 四舍五入后的毫米值。
    """
    return round(value * G, 6)


ROOT_ID = uid("root")


class Page:
    """AI:一个功能图页，显式管理器件、导线、网络名称及交点。"""

    def __init__(self, number, name, description):
        """@brief AI:建立A3功能页。
        @param number 功能编号。
        @param name 中文页名。
        @param description 本页用途和接线边界。
        @return None。
        """
        self.number, self.name = number, name
        self.uuid = uid("page/" + number)
        self.sheet_uuid = uid("sheet/" + number)
        self.path = "/" + ROOT_ID + "/" + self.sheet_uuid
        self.instances = []
        self.pins = {}
        self.nodes = []
        self.wires = []
        self.symbol_names = set()
        self.serial = 0
        self.covered = set()
        self.power_nodes = set()
        self.text(name, 12, 13, 2.5, True)
        self.text(description, 12, 20, 1.1)

    def ident(self, kind):
        """@brief AI:生成当前页图元UUID。
        @param kind 图元类型名称。
        @return 唯一UUID。
        """
        self.serial += 1
        return uid(self.number + "/" + kind + "/" + str(self.serial))

    def text(self, value, x, y, size=1.1, bold=False):
        """@brief AI:绘制工程说明文字。
        @param value 说明内容。
        @param x,y 网格坐标。
        @param size 字高毫米。
        @param bold 是否加粗。
        @return None。
        """
        eff = effects(size, justify=["left", "bottom"])
        if bold:
            child(eff, "font").append(A("bold"))
        self.nodes.append(n("text", value, n("at", mm(x), mm(y), 0), eff, n("uuid", self.ident("text"))))

    def place(self, ref, x, y, rotation=0, unit=1, mirror=None, value=None, fields=None):
        """@brief AI:放置一个实际器件或运放单元，并登记真实引脚坐标。
        @param ref 位号。
        @param x,y 中心网格坐标。
        @param rotation 逆时针旋转角度。
        @param unit 多单元编号。
        @param mirror 可选x轴镜像，用于背靠背MOS。
        @param value 可选显示值。
        @param fields 可选位号、值文字坐标。
        @return 当前器件实例。
        """
        name = MAPPING[ref]
        symbol = SYMBOLS[name]
        self.symbol_names.add(name)
        instance_id = uid(self.number + "/" + ref + "/" + str(unit))
        obj = n("symbol", n("lib_id", "AI_MCUTOOL:" + name), n("at", mm(x), mm(y), rotation), n("unit", unit), n("in_bom", A("yes")), n("on_board", A("yes")), n("dnp", A("no")), n("uuid", instance_id))
        if mirror:
            obj.append(n("mirror", A(mirror)))
        positions = []
        for p in allpins(symbol, unit):
            local = child(p, "at")
            px, py, angle = map(float, local[1:])
            if mirror == "x":
                py, angle = -py, -angle
            elif mirror == "y":
                px, angle = -px, 180 - angle
            theta = math.radians(rotation)
            gx = x + (px * math.cos(theta) - py * math.sin(theta)) / G
            gy = y - (px * math.sin(theta) + py * math.cos(theta)) / G
            gx, gy = round(gx, 6), round(gy, 6)
            angle = (angle + rotation) % 360
            dx, dy = round(-math.cos(math.radians(angle))), round(math.sin(math.radians(angle)))
            number = child(p, "number")[1]
            key = ref + "." + number
            if key in self.pins:
                raise ValueError("重复引脚 " + key)
            self.pins[key] = {"xy": (gx, gy), "dir": (dx, dy), "net": PARTS[ref]["pins"][number], "ref": ref, "number": number}
            positions.append((gx, gy))
            obj.append(n("pin", number, n("uuid", uid(instance_id + "/" + number))))
        if fields:
            ref_at, value_at = fields
        elif name == "LED" and rotation in (90,270):
            ref_at, value_at = (x+14,y-1),(x+14,y+2)
        elif name in ["R", "C", "LED"]:
            ref_at, value_at = ((x, y-3), (x, y+3)) if rotation in (90, 270) or name == "LED" and rotation == 0 else ((x+4, y-1), (x+4, y+1.5))
        elif name == "MMBT3904":
            ref_at, value_at = (x+6, y-2), (x+6, y+1)
        elif name in ["N_FET", "P_FET"]:
            ref_at, value_at = (x+8, y-1), (x+8, y+2)
        else:
            top = min(py for px, py in positions)
            ref_at, value_at = (x, top-6), (x, top-3.5)
        show_value = value if value is not None else PARTS[ref]["value"]
        obj += [prop("Reference", ref, mm(ref_at[0]), mm(ref_at[1]), False), prop("Value", show_value, mm(value_at[0]), mm(value_at[1]), False), prop("Footprint", FOOTPRINTS[ref]), prop("Datasheet", ""), prop("Manufacturer Part", PARTS[ref]["manufacturerId"]), prop("Design Note", PARTS[ref]["note"]), prop("Footprint Status", "封装几何仍需制造审查" if FOOTPRINTS[ref] else "待选定和核对封装；原理图阶段未绑定")]
        # AI:KiCad字段角度跟随符号变换；反向补偿使位号和值始终水平阅读。
        for field in children(obj,"property"):
            if field[1] in ["Reference","Value"]:
                child(field,"at")[3] = rotation % 180
                if name in ["MMBT3904","N_FET","P_FET"] or name in ["R","C"] and rotation==0:
                    child(field,"effects").append(n("justify",A("left")))
        obj.append(n("instances", n("project", PROJECT, n("path", self.path, n("reference", ref), n("unit", unit)))))
        self.instances.append(obj)
        return obj

    def point(self, endpoint):
        """@brief AI:解析引脚名或坐标点。
        @param endpoint 位号.脚号字符串或坐标元组。
        @return 网格坐标。
        """
        return self.pins[endpoint]["xy"] if isinstance(endpoint, str) else tuple(endpoint)

    def net(self, endpoint):
        """@brief AI:取得已审核的引脚网络名。
        @param endpoint 位号.脚号。
        @return 网络名。
        """
        return self.pins[endpoint]["net"]

    def connect(self, *points, net=None):
        """@brief AI:按给定折点绘制正交导线，校验两端网络一致。
        @param points 引脚名或坐标点组成的路径。
        @param net 路径无引脚端点时必填。
        @return None。
        """
        names = {self.net(p) for p in points if isinstance(p, str)}
        if len(names) > 1 or None in names:
            raise ValueError(("连线网络不一致", self.number, points, names))
        net = net or (next(iter(names)) if names else None)
        if not net:
            raise ValueError("导线未指定网络")
        coords = [self.point(p) for p in points]
        for a, b in zip(coords, coords[1:]):
            if a == b:
                continue
            if a[0] != b[0] and a[1] != b[1]:
                raise ValueError(("非正交导线", self.number, a, b))
            self.wires.append((a, b, net))
        for p in points:
            if isinstance(p, str):
                self.covered.add(p)

    def link(self, a, b, bend="h"):
        """@brief AI:以一个拐点连接两端。
        @param a,b 引脚端点。
        @param bend h先水平，v先垂直。
        @return None。
        """
        pa, pb = self.point(a), self.point(b)
        corner = (pb[0], pa[1]) if bend == "h" else (pa[0], pb[1])
        self.connect(a, corner, b)

    def tag(self, endpoint, global_=False, length=5, direction=None):
        """@brief AI:在模块边界放置有明确网络名的接口标签。
        @param endpoint 引脚端点或已注册坐标端点。
        @param global_ 是否跨图页全局连接。
        @param length 端口短线长度，单位网格。
        @param direction 可选离开引脚的方向。
        @return 标签锚点坐标。
        """
        p = self.pins[endpoint]
        dx, dy = direction or p["dir"]
        x, y = p["xy"]
        anchor = (x + dx * length, y + dy * length)
        self.connect(endpoint, anchor)
        if global_:
            angle = 0 if dx > 0 else 180 if dx < 0 else 90 if dy < 0 else 270
            label = n("global_label", p["net"], n("shape", A("bidirectional")), n("at", mm(anchor[0]), mm(anchor[1]), angle), effects(0.95, justify=["left"] if dx >= 0 else ["right"]), n("uuid", self.ident("global")))
            label.append(prop("Intersheetrefs", "${INTERSHEET_REFS}", hide=True))
        else:
            label = n("label", p["net"], n("at", mm(anchor[0]), mm(anchor[1]), 0), effects(0.95, justify=["right" if dx < 0 else "left", "bottom"]), n("uuid", self.ident("label")))
        self.nodes.append(label)
        return anchor

    def power(self, endpoint, net=None, length=4, flag=False):
        """@brief AI:接入电源或地符号；外部供电由显式PWR_FLAG声明。
        @param endpoint 引脚名或坐标。
        @param net 坐标端点时所需的电源网名。
        @param length 与引脚的垂直间隔。
        @param flag 是否额外声明该网由外部电源驱动。
        @return 电源符号坐标。
        """
        point = self.point(endpoint)
        net = net or self.net(endpoint)
        rotation = 0
        if net == "COMMON_GND" and isinstance(endpoint, str):
            dx,dy=self.pins[endpoint]["dir"]
            x,y=point[0]+dx*length,point[1]+dy*length
            rotation = 90 if dx>0 else 270 if dx<0 else 180 if dy<0 else 0
        else:
            x, y = point[0], point[1] + (length if net in ["COMMON_GND", "VNEG"] else -length)
        self.connect(endpoint, (x, y), net=net)
        if (x, y, net) not in self.power_nodes:
            self.power_nodes.add((x, y, net))
            self.helper(net, x, y, rotation)
        if flag:
            self.helper("PWR_FLAG", x, y)
        return x, y

    def helper(self, name, x, y, rotation=0):
        """@brief AI:放置不计BOM的电源符号。
        @param name 项目电源符号名。
        @param x,y 网格坐标。
        @param rotation 电源图形旋转角度。
        @return None。
        """
        self.symbol_names.add(name)
        ref = ("#FLG" if name == "PWR_FLAG" else "#PWR") + self.number + str(len(self.instances)).zfill(3)
        obj = n("symbol", n("lib_id", "AI_MCUTOOL:"+name), n("at", mm(x), mm(y), rotation), n("unit", 1), n("in_bom", A("no")), n("on_board", A("no")), n("uuid", self.ident("power")), prop("Reference", ref), prop("Value", name, mm(x), mm(y+4 if name=="VNEG" else y-4), name in ["COMMON_GND", "PWR_FLAG"]), prop("Footprint", ""), n("instances", n("project", PROJECT, n("path", self.path, n("reference", ref), n("unit", 1)))))
        self.instances.append(obj)

    def port(self, net, point, global_=True, direction=1):
        """@brief AI:在已绘制线路端点标注模块接口。
        @param net 已确认网络名。
        @param point 标签锚点坐标。
        @param global_ 是否跨页连接。
        @param direction 全局标签朝向；1向右，-1向左。
        @return None。
        """
        obj=n("global_label" if global_ else "label",net,n("at",mm(point[0]),mm(point[1]),180 if global_ and direction<0 else 0),effects(0.95,justify=["right" if direction<0 else "left"] if global_ else ["left","bottom"]),n("uuid",self.ident("port")))
        if global_:
            obj.insert(2,n("shape",A("bidirectional")));obj.append(prop("Intersheetrefs","${INTERSHEET_REFS}",hide=True))
        self.nodes.append(obj)

    def flag_at(self, endpoint):
        """@brief AI:声明真实外部输入电源，不新建电气连接。
        @param endpoint 输入连接器或既有节点的引脚。
        @return None。
        """
        self.helper("PWR_FLAG", *self.point(endpoint))

    @staticmethod
    def on_segment(point, a, b):
        """@brief AI:判断点是否落在正交线段上。
        @param point,a,b 待测点和线段端点。
        @return 布尔值。
        """
        return (a[0] == b[0] == point[0] and min(a[1], b[1]) <= point[1] <= max(a[1], b[1])) or (a[1] == b[1] == point[1] and min(a[0], b[0]) <= point[0] <= max(a[0], b[0]))

    def finish(self):
        """@brief AI:补齐跨页接口及电源、校验局部未接脚，拆分T形连接并添加接点。
        @return None；异常时停止生成，不能用自动标签掩盖缺失的局部连线。
        """
        anchored = set()
        for key, p in self.pins.items():
            touching = {net for a, b, net in self.wires if self.on_segment(p["xy"], a, b)}
            if touching - {p["net"]}:
                raise ValueError(("导线穿过其他网络引脚", self.number, key, p["xy"], p["net"], touching))
            if p["net"] is None:
                self.nodes.append(n("no_connect", n("at", *[mm(v) for v in p["xy"]]), n("uuid", self.ident("nc"))))
            elif not touching:
                if (p["xy"], p["net"]) in anchored:
                    continue
                anchored.add((p["xy"], p["net"]))
                if p["net"] in ["COMMON_GND", "TOOL_3V3", "VNEG"]:
                    self.power(key)
                elif len(NET_PAGES[p["net"]]) > 1:
                    self.tag(key, True)
                else:
                    raise ValueError(("本地引脚尚未连线", self.number, key, p["net"]))
        # AI:所有端点、引脚和同网交叉点参与分段；不同网络只允许无接点交叉。
        points = {p["xy"] for p in self.pins.values()} | {q for a,b,net in self.wires for q in [a,b]}
        for i,(a,b,net) in enumerate(self.wires):
            for c,d,other in self.wires[i+1:]:
                if (a[0]==b[0]) != (c[0]==d[0]):
                    cross = (a[0],c[1]) if a[0]==b[0] else (c[0],a[1])
                    if net == other and self.on_segment(cross,a,b) and self.on_segment(cross,c,d):
                        points.add(cross)
        segments = {}
        degree = defaultdict(int)
        for a,b,net in self.wires:
            cut = sorted(q for q in points if self.on_segment(q,a,b))
            for p,q in zip(cut,cut[1:]):
                pair = tuple(sorted([p,q]))
                if pair in segments and segments[pair] != net:
                    raise ValueError(("不同网络导线重叠",self.number,pair,net,segments[pair]))
                segments[pair]=net
        point_nets = defaultdict(set)
        for (a,b),net in segments.items():
            for p in [a,b]:
                point_nets[p].add(net);degree[p]+=1
            self.nodes.append(n("wire",n("pts",n("xy",*[mm(v) for v in a]),n("xy",*[mm(v) for v in b])),n("stroke",n("width",0),n("type",A("default"))),n("uuid",self.ident("wire"))))
        for point,nets in point_nets.items():
            if len(nets)>1:
                raise ValueError(("不同网络端点相接",self.number,point,nets))
            if degree[point]>=3:
                self.nodes.append(n("junction",n("at",*[mm(v) for v in point]),n("diameter",0),n("color",0,0,0,0),n("uuid",self.ident("junction"))))

    def save(self):
        """@brief AI:保存嵌入完整符号定义的KiCad原理图。
        @return 输出文件路径。
        """
        definitions=[]
        for name in sorted(self.symbol_names):
            s=deepcopy(SYMBOLS[name]);s[1]="AI_MCUTOOL:"+name;definitions.append(s)
        doc=n("kicad_sch",n("version",20250114),n("generator",A("eeschema")),n("generator_version","9.0"),n("uuid",self.uuid),n("paper","A3"),n("title_block",n("title",self.name),n("date","2026-10-24"),n("rev","A-KiCad"),n("company","AI-MCUTOOL"),n("comment",1,"原理样机；封装、热设计和测量精度仍需验证")),n("lib_symbols",*definitions),*self.nodes,*self.instances)
        path=OUT/(self.number+"_"+PAGE_FILES[self.number]+".kicad_sch")
        path.write_text(dumps(doc)+"\n","utf-8")
        return path


PAGE_FILES={"01":"power","02":"controller","03":"keys","04":"source_switch","05":"charger","06":"current_sense","07":"voltage_sense","08":"uart"}


def main():
    """@brief AI:绘制全部功能页、总览页及项目配置。
    @return None；缺失引脚或误连时异常退出。
    """
    from kicad_circuit_pages import draw_pages
    pages=draw_pages(Page)
    placed={p["ref"] for page in pages for p in page.pins.values()}
    if placed!=set(PARTS):raise ValueError(("器件集合不符",set(PARTS)-placed,placed-set(PARTS)))
    for page in pages:
        page.finish();page.save()
    overview=n("kicad_sch",n("version",20250114),n("generator",A("eeschema")),n("generator_version","9.0"),n("uuid",ROOT_ID),n("paper","A3"),n("title_block",n("title","MCU开发辅助工具 / 系统总览"),n("date","2026-10-24"),n("rev","A-KiCad"),n("company","AI-MCUTOOL")),n("lib_symbols"))
    summaries = [
        "DC / Type-C：仅5V\nLM66100双入口隔离\nLDL1117输出3.3V\n输出：TOOL_3V3 / COMMON_GND",
        "ESP32-S3-WROOM-1-N16R8\nWi-Fi控制与共享I2C\nRESET / BOOT / CONFIG\n独立下载口和状态指示",
        "KEY1～KEY5独立无极性触点\nTLP176AM + MMBT3904\n按键边界：≤6V、≤20mA\n触点侧不接工具公共地",
        "BAT_IN / EXT_IN → VSEL_P\nVOM1271T隔离栅极驱动\n共源背靠背N-MOS\n两路互斥、先断后通",
        "CHG_IN → DUT_CHG\n独立5V充电器输入\n共源背靠背P-MOS\n无主动放电；真实电池模式验证",
        "VSEL_P → DUT_PWR\n20mΩ四端分流 + INA228\n电池端双向电流 / 接口电压\nI2C + CURRENT_ALERT",
        "AIN1～AIN4：共地0～15V\n高阻分压 → OPA4391 → ADS1115\nLM7705提供近零测量负轨\n四路分别校准；I2C读取",
        "DUT_UART：3.3V TTL\nTX三态缓冲，默认高阻\nRX施密特缓冲，持续接收\nTX / RX / GND三针接口",
    ]
    for i,page in enumerate(pages):
        x,y=25+(i%4)*98,45+(i//4)*100
        overview.append(n("sheet",n("at",x,y),n("size",85,65),n("stroke",n("width",0.254),n("type",A("solid"))),n("fill",n("color",0,0,0,0)),n("uuid",page.sheet_uuid),n("property","Sheetname",page.name,n("at",x,y-2,0),effects(1.27,justify=["left","bottom"])),n("property","Sheetfile",page.number+"_"+PAGE_FILES[page.number]+".kicad_sch",n("at",x,y+67,0),effects(1.0,justify=["left","top"])),n("instances",n("project",PROJECT,n("path","/"+ROOT_ID,n("page",str(i+2)))))))
        overview.append(n("text",summaries[i],n("at",x+6,y+16,0),effects(1.5,justify=["left","top"]),n("uuid",uid("overview/summary/"+page.number))))
    overview.append(n("sheet_instances",n("path","/",n("page","1"))))
    overview.append(n("text","AI-MCUTOOL  /  ESP32-S3-WROOM-1-N16R8\nWi-Fi控制 · 五路按键 · 电源切换 · 充电插拔 · 电池测量 · 四路电压 · 3.3V UART",n("at",25,25,0),effects(1.8,justify=["left","bottom"]),n("uuid",uid("overview/title"))))
    overview.append(n("text","外部电池 / 模拟电源 / 充电器各自独立；工具自身仅使用5V供电。\n双击功能框进入图页。跨页接口使用命名端口；同页功能电路优先直接连线。\n当前为原理图设计，未做PCB、样机或整机额定能力验收。",n("at",25,245,0),effects(1.27,justify=["left","bottom"]),n("uuid",uid("overview/notes"))))
    (OUT/(PROJECT+".kicad_sch")).write_text(dumps(overview)+"\n","utf-8")
    if not (OUT/(PROJECT+".kicad_pro")).exists():
        (OUT/(PROJECT+".kicad_pro")).write_text(json.dumps({"meta":{"filename":PROJECT+".kicad_pro","version":1},"text_variables":{}},indent=2)+"\n","utf-8")
    manifest={"components":len(placed),"physicalPins":sum(len(p.pins) for p in pages),"pages":[{"number":p.number,"name":p.name,"components":len({v['ref'] for v in p.pins.values()}),"wireSegments":len(p.wires)} for p in pages],"symbols":MAPPING,"footprints":FOOTPRINTS}
    (OUT/"generation-manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({"components":len(placed),"physicalPins":manifest["physicalPins"],"functionalPages":len(pages)},ensure_ascii=False))


if __name__=="__main__":main()
