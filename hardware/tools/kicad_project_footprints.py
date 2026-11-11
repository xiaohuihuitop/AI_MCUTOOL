"""@brief AI:建立保留实际焊盘编号的项目封装，制造审查状态独立记录。"""
import argparse
import json
import math
from pathlib import Path
from kicad_sexpr import Atom as A, parse, dumps, children, child
from kicad_typec_footprint import make_typec
from kicad_dc_footprint import make_dc


# AI:按本项目封装方向记录厂家本体尺寸；MOS依据TI第8页，VOM1271依据Vishay第5页。
BODY_GEOMETRY = {
    "N_FET": {"nominal": (3.15, 3.00), "maximum": (3.25, 3.10)},
    "P_FET": {"nominal": (3.15, 3.00), "maximum": (3.25, 3.10)},
    "PHOTO_PV": {"nominal": (4.42, 4.57), "maximum": (4.92, 4.82)},
    "SHUNT4": {"nominal": (6.35, 3.18), "maximum": (6.604, 3.434)},
}


def make_footprints(root, install, out, n, footprints):
    """@brief AI:复制官方SOT223并转换已核SMD焊盘，核对脚号集合。
    @param root 项目根目录。
    @param install KiCad共享资源目录。
    @param out 当前KiCad工程目录。
    @param n S表达式节点构造函数。
    @param footprints 逐位号封装关联。
    @return None；输出项目局部封装库及来源说明。
    """
    target=out/"AI_MCUTOOL.pretty";target.mkdir(exist_ok=True)
    # AI:唯一输入为审查前冻结的几何，禁止从已修复输出再次翻转或自动寻找替代数据。
    source_path=out/"footprint-source.json"
    source=json.loads(source_path.read_text("utf-8"))
    if source["schema"]!="ai-mcutool-footprint-source/1" or source["units"]!="mm" or source["coordinateFrame"]!="source-y-up":
        raise ValueError("封装来源单位或坐标约定不匹配")
    evidence=[]
    for record in source["footprints"]:
        name,source_name=record["name"],record["sourceName"]
        pads=record["pads"]
        description="Vishay WSK2512 0.005-0.2ohm推荐铜盘；钢网及焊接工艺待确认" if name=="SHUNT4" else "迁移自实际库焊盘；尺寸、钢网及焊接工艺待制造审查"
        fp=n("footprint",name,n("version",20241229),n("generator",A("pcbnew")),n("layer","F.Cu"),n("descr",description),n("attr",A("smd")))
        bounds=[]
        for p in pads:
            if p["shape"] not in ["rect","oval","circle"]:
                raise ValueError(("超出本次SMD转换范围",name,p))
            # AI:来源封装使用向上的Y轴，KiCad板面使用向下的Y轴，必须翻转中心Y。
            x,y=round(p["x"],6),-round(p["y"],6)
            w,h=p["width"],p["height"]
            kind=p["shape"]
            if kind=="circle" and abs(w-h)>1e-6:raise ValueError("不支持非圆椭圆焊盘")
            # AI:本批仅有正交且中心对称的焊盘；90/270度的轴方向等价，保留原角度。
            if not math.isclose(float(p["angle"]) % 90,0,abs_tol=1e-6):
                raise ValueError(("非正交焊盘须先核准角度约定",name,p["number"],p["angle"]))
            fp.append(n("pad",str(p["number"]),A("smd"),A(kind),n("at",x,y,p["angle"]),n("size",w,h),n("layers","F.Cu","F.Paste","F.Mask")))
            bounds.extend([(x-max(w,h)/2,y-max(w,h)/2),(x+max(w,h)/2,y+max(w,h)/2)])
        if name in BODY_GEOMETRY:
            body=BODY_GEOMETRY[name]
            max_x,max_y=body["maximum"]
            bounds.extend([(-max_x/2,-max_y/2),(max_x/2,max_y/2)])
            width,height=body["nominal"]
            # AI:Fab倒角标记项目1脚方向，SHUNT4的1脚在左上；外包络不是器件凹口轮廓。
            outline=[(-width/2,-height/2),(width/2,-height/2),(width/2,height/2),
                     (-width/2+0.4,height/2),(-width/2,height/2-0.4),(-width/2,-height/2)]
            if name == "SHUNT4":
                outline=[(x,-y) for x,y in outline]
            for start,end in zip(outline,outline[1:]):
                fp.append(n("fp_line",n("start",*[round(v,6) for v in start]),n("end",*[round(v,6) for v in end]),
                            n("stroke",n("width",0.1),n("type",A("default"))),n("layer","F.Fab")))
        left=min(p[0] for p in bounds)-0.25;right=max(p[0] for p in bounds)+0.25
        top=min(p[1] for p in bounds)-0.25;bottom=max(p[1] for p in bounds)+0.25
        # AI:向外取整到0.05mm网格，避免舍入缩小0.25mm的装配间隙。
        left,top=(math.floor(v/0.05+1e-9)*0.05 for v in (left,top))
        right,bottom=(math.ceil(v/0.05-1e-9)*0.05 for v in (right,bottom))
        fp.append(n("fp_rect",n("start",round(left,4),round(top,4)),n("end",round(right,4),round(bottom,4)),n("stroke",n("width",0.05),n("type",A("default"))),n("fill",A("none")),n("layer","F.CrtYd")))
        first=next(p for p in pads if str(p["number"])=="1")
        first_y=-round(first["y"],6)
        # AI:在焊盘范围外添加1脚三角；实际装配仍以器件标记和厂家图共同核对。
        triangle=[(left-0.15,first_y),(left-0.5,first_y-0.2),(left-0.5,first_y+0.2),(left-0.15,first_y)]
        for start,end in zip(triangle,triangle[1:]):
            fp.append(n("fp_line",n("start",*[round(v,6) for v in start]),n("end",*[round(v,6) for v in end]),n("stroke",n("width",0.12),n("type",A("default"))),n("layer","F.SilkS")))
        for text,value,y,layer in [("reference","REF**",top-1,"F.SilkS"),("value",name,bottom+1,"F.Fab")]:
            fp.append(n("fp_text",A(text),value,n("at",0,round(y,4)),n("layer",layer),n("effects",n("font",n("size",1,1),n("thickness",0.15)))))
        (target/(name+".kicad_mod")).write_text(dumps(fp)+"\n","utf-8")
        evidence.append({"footprint":name,"source":source_name,"pads":[str(p["number"]) for p in pads],
                         "copperCoordinates":"固定来源已换算为mm，X保持、Y反号；正交中心对称焊盘保留原轴角度",
                         "sourceFile":"footprint-source.json","unfixedFootprintSha256":record["unfixedFootprintSha256"],
                         "manufacturerReview":record.get("manufacturerReview"),
                         "bodyGeometryMm":BODY_GEOMETRY.get(name),
                         "courtyardMm":[round(right-left,4),round(bottom-top,4)],
                         "manufacturingReview":"方向已修正；焊盘尺寸、钢网/阻焊及未登记本体外形仍待制造审查"})
    ldo=parse((install/"footprints/Package_TO_SOT_SMD.pretty/SOT-223-3_TabPin2.kicad_mod").read_text("utf-8"))
    ldo[1]="LDL1117"
    tabs=[p for p in children(ldo,"pad") if p[1]=="2" and float(child(p,"at")[1])>0]
    if len(tabs)!=1:raise ValueError("SOT223散热焊盘识别失败")
    tabs[0][1]="4"
    (target/"LDL1117.kicad_mod").write_text(dumps(ldo)+"\n","utf-8")
    evidence.append({"footprint":"LDL1117","source":"KiCad SOT-223-3_TabPin2","pads":["1","2","3","4"],"note":"库编号4仅指散热片，与实际VOUT/2同网，不是新增芯片功能引脚"})
    evidence.append(make_typec(out,n))
    evidence.append(make_dc(out,n))
    # AI:天线伸出主板时，标准模组跨板边的丝印无印刷载体；仅把轮廓移到Fab，铜盘和禁布区原样保留。
    esp_source=install/"footprints/RF_Module.pretty/ESP32-S3-WROOM-1.kicad_mod"
    esp=parse(esp_source.read_text("utf-8")); esp[1]="ESP32_S3_WROOM_1_Edge"
    for graphic in esp:
        if isinstance(graphic,list) and graphic[0] in ("fp_line","fp_rect","fp_poly","fp_arc"):
            layer=child(graphic,"layer")
            if layer and layer[1]=="F.SilkS": layer[1]="F.Fab"
    (target/"ESP32_S3_WROOM_1_Edge.kicad_mod").write_text(dumps(esp)+"\n","utf-8")
    evidence.append({"footprint":"ESP32_S3_WROOM_1_Edge","source":"KiCad10 RF_Module:ESP32-S3-WROOM-1",
                     "change":"仅将标准丝印图形转至Fab，保留全部焊盘和全铜层天线禁布规则",
                     "report":"../../docs/ESP32模组天线布局核定.md"})
    libraries=sorted({f.split(":",1)[0] for f in footprints.values() if f})
    table=n("fp_lib_table",n("version",7))
    for library in libraries:
        uri="${KIPRJMOD}/AI_MCUTOOL.pretty" if library=="AI_MCUTOOL" else "${KICAD10_FOOTPRINT_DIR}/"+library+".pretty"
        table.append(n("lib",n("name",library),n("type","KiCad"),n("uri",uri),n("options",""),n("descr","项目关联封装")))
    (out/"fp-lib-table").write_text(dumps(table)+"\n","utf-8")
    (out/"footprint-provenance.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n","utf-8")


def main():
    """@brief AI:只重建项目封装，逐图读取现有封装关联，不重画原理图。
    @return None；相同位号关联不一致或来源几何不支持时抛错。
    """
    root=Path(__file__).resolve().parents[2]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install",type=Path,default=Path("D:/Application/kicad/install/share/kicad"))
    args=parser.parse_args()
    out=root/"hardware/kicad"
    footprints={}
    for path in sorted(out.glob("*.kicad_sch")):
        for symbol in children(parse(path.read_text("utf-8")),"symbol"):
            properties={p[1]:p[2] for p in children(symbol,"property")}
            ref=properties["Reference"]
            if ref.startswith("#"):continue
            footprint=properties.get("Footprint","")
            if ref in footprints and footprints[ref]!=footprint:
                raise ValueError(("同位号封装关联不一致",ref))
            footprints[ref]=footprint
    if not footprints:raise ValueError("没有读取到实体器件，停止生成")
    make_footprints(root,args.install,out,lambda key,*values:[A(key),*values],footprints)
    print("已重建10个项目封装；原理图未重画。")


if __name__=="__main__":main()
