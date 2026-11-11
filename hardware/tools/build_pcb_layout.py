"""@brief AI:将已核网表导入华秋KiCad，生成90mm四层板的未布线布局初稿。"""
import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pcbnew as pcb

ROOT=Path(__file__).resolve().parents[2]
PROJECT=ROOT/"hardware/kicad"
LIBRARIES=Path("D:/Application/kicad/install/share/kicad/footprints")
OFFSET=50


def positions():
    """@brief AI:显式给出各功能电路的初始位置；坐标相对板框左上角，角度为KiCad度数。
    @return 位号到(x毫米,y毫米,角度)的字典；不使用未列器件自动散排兜底。
    """
    result={
        "J1":(13.7,42,0),"J2":(5.79,56,-90),
        "U1":(18,42,0),"C1":(18,38,0),"R1":(22,38,0),
        "U2":(14,56,0),"C2":(12,51.5,0),"R2":(16,51.5,0),
        "R3":(9,56,90),"R4":(9,59.5,90),
        "U3":(32,46,0),"C3":(26,51.5,90),"C4":(35,51.5,0),
        "U4":(76,6.75,0),"C5":(63,3,0),"C6":(63,6,0),"C7":(63,9.5,0),
        "R5":(63,12,0),"R6":(63,21.5,0),"R7":(69,23,90),"R8":(66,23,90),
        "R9":(63,16,0),"R10":(77,34,0),"R11":(84,34,0),
        "R81":(58.5,23,90),"R82":(61,25,90),
        "J3":(54,5,0),"SW1":(66,28,0),"SW2":(75,28,0),"SW3":(84,28,0),
        "LED1":(77,37,0),"LED2":(84,37,0),
        "J9":(8,86,90),"J10":(24,86,90),"J11":(42,86,90),
        "Q8":(10,79,180),"Q9":(10,74,0),"Q10":(26,79,180),"Q11":(26,74,0),
        "U10":(11,66,180),"U11":(27,66,180),
        "Q6":(5,67,0),"Q7":(21,62,0),"R27":(5,73,90),"R30":(21,72,90),
        "R28":(3,63,0),"R29":(6.5,63,0),"R31":(18,58,0),"R32":(22,58,0),
        "RSH1":(40,77,180),"U12":(40,69.5,180),"R37":(36,72,90),"R38":(44,73,90),
        "C8":(40,73.5,0),"C9":(44,69.5,90),"R39":(40,65.5,0),
        "J12":(63,86,90),"J13":(81,86,90),"Q12":(64,80,90),"Q13":(69,80,-90),
        "Q14":(75,80,0),"R33":(68,76.5,0),"R34":(72,76,0),"R35":(79,77,0),"R36":(79,80,0),
        "U14":(53,63,0),"U13":(46,54,0),"U15":(46,44,0),
        "C18":(53,58,0),"C19":(53,67.5,0),"C20":(42,43,90),
        "C21":(46,40.5,0),"C22":(50.5,42.5,90),"C23":(50.5,46,90),
        "C24":(50,49,0),"C25":(51,54,90),
        "J18":(42,4,0),"U16":(39,15,0),"U17":(46,15,0),
        "C26":(38,11.5,0),"C27":(46,11.5,0),"R76":(35,15,90),"R77":(35,19,90),
        "R78":(49.5,15,90),"R79":(39,19,0),"R80":(46,19,0),
    }
    for i in range(5):
        y=5+6.5*i
        result.update({f"J{i+4}":(4,y,0),f"U{i+5}":(13,y+1.25,180),
                       f"Q{i+1}":(23,y+1.25,0),f"R{12+3*i}":(20,y-1,90),
                       f"R{13+3*i}":(27,y+0.5,90),f"R{14+3*i}":(27,y+3.5,0)})
    for i in range(4):
        y=51+7*i
        result[f"J{14+i}"]=(86,y,0)
        for j in range(5):
            result[f"R{40+9*i+j}"]=(81-5*j,y,0)
        result[f"R{45+9*i}"]=(64,y+3,0)
        result[f"C{10+2*i}"]=(60.5,y+3,0)
    # AI:运放反馈与输出滤波围绕共享U14/U13放置，不按通道网格复制到远端。
    result.update({"R46":(47,60.5,0),"R47":(47,63,0),"R48":(46,58,0),"C11":(42,58,90),
                   "R55":(47,65.5,0),"R56":(47,68,0),"R57":(43,61,0),"C13":(40,61,90),
                   "R64":(57.8,66,90),"R65":(57.8,69.5,90),"R66":(53,71,0),"C15":(49,71,90),
                   "R73":(57.8,59,90),"R74":(57.8,62.5,90),"R75":(55,54,0),"C17":(55,51,90)})
    return result


def point(x,y):
    """@brief AI:将相对板框毫米坐标转换为KiCad内部坐标。
    @param x 相对横坐标，毫米。
    @param y 相对纵坐标，毫米。
    @return VECTOR2I坐标。
    """
    return pcb.VECTOR2I(pcb.FromMM(OFFSET+x),pcb.FromMM(OFFSET+y))


def line(board,start,end,layer,width=0.1):
    """@brief AI:添加板框或工程参考线。
    @param board 目标板对象。
    @param start 起点毫米二元组。
    @param end 终点毫米二元组。
    @param layer KiCad层标识。
    @param width 线宽毫米。
    @return None。
    """
    item=pcb.PCB_SHAPE(board)
    item.SetStart(point(*start)); item.SetEnd(point(*end))
    item.SetLayer(layer); item.SetWidth(pcb.FromMM(width)); board.Add(item)


def label(board,text,x,y,size=1,layer=pcb.F_SilkS):
    """@brief AI:添加端口标识或只出现在工程参考层的布局说明。
    @param board 目标板对象。
    @param text 标识文本。
    @param x 横坐标毫米。
    @param y 纵坐标毫米。
    @param size 字高毫米。
    @param layer 绘制层。
    @return None。
    """
    if layer==pcb.F_SilkS: size=max(size,0.8)
    item=pcb.PCB_TEXT(board); item.SetText(text); item.SetPosition(point(x,y))
    item.SetTextSize(pcb.VECTOR2I(pcb.FromMM(size),pcb.FromMM(size)))
    item.SetTextThickness(pcb.FromMM(0.15 if size>=1 else 0.12))
    item.SetLayer(layer); board.Add(item)


def main():
    """@brief AI:从已核网表生成未布线初稿；已有手工修改或布线时拒绝覆盖。
    @return None；检查输入或保存失败时抛错，输出PCB及创建摘要。
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace-draft",action="store_true")
    args=parser.parse_args()
    dest=PROJECT/"AI_MCUTOOL.kicad_pcb"
    manifest=PROJECT/"verification/pcb-layout-build.json"
    if dest.exists():
        if not args.replace_draft or not manifest.exists():
            raise RuntimeError("PCB已存在，拒绝覆盖；仅允许显式重建本脚本未修改初稿")
        previous=json.loads(manifest.read_text("utf-8"))
        if hashlib.sha256(dest.read_bytes()).hexdigest()!=previous["boardSha256"]:
            raise RuntimeError("PCB已被修改，拒绝覆盖")
    checked=json.loads((PROJECT/"verification/check.json").read_text("utf-8"))
    if not checked["passed"] or checked["unboundFootprints"]:
        raise RuntimeError("必须先通过完整原理图/封装校验")
    for name,digest in checked["schematicSha256"].items():
        if hashlib.sha256((PROJECT/name).read_bytes()).hexdigest()!=digest:
            raise RuntimeError("原理图已变化，请重新导出并校验网表")
    xml=ET.parse(PROJECT/"verification/netlist.xml").getroot()
    components={c.get("ref"):c for c in xml.findall("./components/comp")}
    placement=positions()
    if set(placement)!=set(components):
        raise RuntimeError(("摆放表器件集合不一致",set(components)-set(placement),set(placement)-set(components)))
    board=pcb.BOARD(); board.SetCopperLayerCount(4)
    nets={}; endpoint_nets={}
    for index,net in enumerate(xml.findall("./nets/net"),1):
        name=net.get("name")
        # AI:XML把NC引脚名中的斜杠解码，PCB内部沿用KiCad的{slash}转义；层次网名斜杠仍保留。
        if name.startswith("unconnected-"): name=name.replace("/","{slash}")
        native=pcb.NETINFO_ITEM(board,name,index); board.Add(native); nets[name]=native
        for node in net.findall("node"):
            key=(node.get("ref"),node.get("pin"))
            if key in endpoint_nets: raise RuntimeError(("重复归网",key))
            endpoint_nets[key]=native
    mappings=[]
    for ref,c in components.items():
        library,name=c.findtext("footprint").split(":",1)
        directory=PROJECT/"AI_MCUTOOL.pretty" if library=="AI_MCUTOOL" else LIBRARIES/(library+".pretty")
        fp=pcb.FootprintLoad(str(directory),name)
        if fp is None: raise RuntimeError(("无法载入封装",ref))
        fp.SetReference(ref); fp.SetValue(c.findtext("value")); fp.SetFPID(pcb.LIB_ID(library,name))
        # AI:沿用KiCad COMPONENT::SetFootprint：层次路径加首个单元UUID，多单元仍为一颗实体。
        path=c.find("sheetpath").get("tstamps")+c.findtext("tstamps").split()[0]
        fp.SetPath(pcb.KIID_PATH(path))
        props={p.get("name"):p.get("value") for p in c.findall("property")}
        fp.SetSheetname(props["Sheetname"]); fp.SetSheetfile(props["Sheetfile"])
        for field in c.findall("./fields/field"):
            key=field.get("name")
            if key!="Footprint":
                fp.SetField(key,field.text or "")
                fp.GetField(key).SetVisible(False)
        board.Add(fp)
        x,y,angle=placement[ref]; fp.SetOrientationDegrees(angle); fp.SetPosition(point(x,y))
        for pad in fp.Pads():
            number=pad.GetNumber()
            if number:
                if (ref,number) not in endpoint_nets: raise RuntimeError(("铜盘缺少归网",ref,number))
                pad.SetNet(endpoint_nets[(ref,number)])
        # AI:初稿位号放Fab便于密集电路审阅；接口另加清晰丝印，正式装配丝印在布线后复核。
        fp.Reference().SetLayer(pcb.F_Fab); fp.Reference().SetTextSize(pcb.VECTOR2I(pcb.FromMM(0.7),pcb.FromMM(0.7)))
        fp.Reference().SetTextAngle(pcb.EDA_ANGLE(0,pcb.DEGREES_T)); fp.Reference().SetPosition(point(x,y))
        fp.Value().SetVisible(False)
        if any(isinstance(g,pcb.PCB_TEXT) and g.GetText()=="${REFERENCE}" for g in fp.GraphicalItems()):
            fp.Reference().SetVisible(False)
        mappings.append({"ref":ref,"path":path,"xMm":x,"yMm":y,"angle":angle,"footprint":c.findtext("footprint")})
    corners=[(0,0),(90,0),(90,90),(0,90),(0,0)]
    for a,b in zip(corners,corners[1:]): line(board,a,b,pcb.Edge_Cuts,0.05)
    for i in range(5):
        y=5+6.5*i
        label(board,f"KEY{i+1}",5,y-2,0.8)
        label(board,"A",7,y,0.8); label(board,"B",7,y+2.54,0.8)
    for i in range(4):
        y=51+7*i
        label(board,f"AIN{i+1}",85,y-2,0.8); label(board,"+",88.4,y,0.8); label(board,"G",88.4,y+2.54,0.8)
    for ref,name in [("J9","BAT_IN"),("J10","EXT_IN"),("J11","DUT_PWR"),("J12","CHG_IN"),("J13","DUT_CHG")]:
        x,y,_=placement[ref]; label(board,name,x+1.27,83.5,0.8)
        label(board,"+  G",x+1.27,88.5,0.7)
    label(board,"DC 5V",10,36,1); label(board,"USB-C 5V",7,49,0.8)
    label(board,"DUT UART",42,1.8,0.8); label(board,"3V3",47.5,6,0.7)
    label(board,"DOWNLOAD",54,2,0.8)
    for y,t in [(5,"TX"),(7.54,"RX"),(10.08,"G"),(12.62,"BOOT"),(15.16,"EN")]: label(board,t,58,y,0.65)
    for y,t in [(4,"TX"),(6.54,"RX"),(9.08,"G")]: label(board,t,37.5,y,0.65)
    for x,t in [(66,"RESET"),(75,"BOOT"),(84,"CONFIG")]: label(board,t,x,31.5,0.8)
    label(board,"PWR",77,39,0.8); label(board,"STATUS",84,39,0.8)
    label(board,"AI-MCUTOOL RevA",42,34,1.2)
    # AI:只预留散热面积，不在布局阶段声称已完成1.55W热设计或铺铜。
    area=[(17,34),(42,34),(42,59),(17,59),(17,34)]
    for a,b in zip(area,area[1:]): line(board,a,b,pcb.Dwgs_User)
    label(board,"LDO OUT / 3V3 THERMAL AREA",29.5,55,0.7,pcb.Dwgs_User)
    label(board,"PLACEMENT DRAFT - UNROUTED",45,94,1.3,pcb.Dwgs_User)
    # AI:新建BOARD对象的默认设置不能覆盖已存在的原理图/工程配置。
    if not pcb.SaveBoard(str(dest),board,True): raise RuntimeError("PCB保存失败")
    report={"kicadVersion":pcb.GetBuildVersion(),"boardSha256":hashlib.sha256(dest.read_bytes()).hexdigest(),
            "boardSizeMm":[90,90],"copperLayers":4,"components":len(mappings),"stage":"placement-unrouted",
            "schematicSha256":checked["schematicSha256"],"placements":mappings,
            "netlistSha256":hashlib.sha256((PROJECT/"verification/netlist.xml").read_bytes()).hexdigest()}
    manifest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("placements","schematicSha256")},ensure_ascii=False))


if __name__=="__main__": main()
