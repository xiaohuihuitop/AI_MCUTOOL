"""@brief AI:按HRO 2020-12-08厂家图建立与项目符号脚号一致的Type-C封装。"""
import json
from kicad_sexpr import Atom as A, dumps

NAME = "USB_C_HRO_TYPE_C_31_M_12"


def make_typec(out, n):
    """@brief AI:根据固定厂家尺寸数据生成Type-C铜盘、定位孔、本体和板边参考。
    @param out KiCad工程目录，内含typec-footprint-source.json。
    @param n S表达式节点构造函数。
    @return 封装来源字典；输出项目封装文件，不改原理图。
    """
    source = json.loads((out / "typec-footprint-source.json").read_text("utf-8"))
    if source["units"] != "mm" or source["y_positive"] != "toward mouth / PCB edge":
        raise ValueError("Type-C固定输入坐标约定不一致")
    fp = n("footprint", NAME, n("version",20241229), n("generator",A("pcbnew")),
           n("layer","F.Cu"), n("descr",source["source"]+"; project pin names; see docs/电源连接器封装核定.md"), n("attr",A("smd")))
    for pad in source["pads"]:
        kind = pad["type"]
        if kind not in ("smd", "thru_hole", "np_thru_hole"):
            raise ValueError("未支持的Type-C焊盘类型: "+kind)
        shape = "rect" if kind == "smd" else "oval" if kind == "thru_hole" else "circle"
        item = n("pad",pad["number"],A(kind),A(shape),n("at",*pad["xy"]),n("size",*pad["size"]))
        if kind == "smd":
            item.append(n("layers","F.Cu","F.Paste","F.Mask"))
        else:
            w,h = pad["drill"]
            item.extend([n("drill",w) if w==h else n("drill",A("oval"),w,h),n("layers","*.Cu","*.Mask")])
        fp.append(item)
    body=source["body_nominal"]
    fp.append(n("fp_rect",n("start",body["x_min"],body["y_min"]),n("end",body["x_max"],body["y_max"]),
                n("stroke",n("width",0.1),n("type",A("default"))),n("fill",A("none")),n("layer","F.Fab")))
    # AI:包络覆盖铜盘及本体，较名义本体保留至少0.5mm，后续仍须核实际外壳装配。
    fp.append(n("fp_rect",n("start",-5.3,-2.2),n("end",5.3,6.8),
                n("stroke",n("width",0.05),n("type",A("default"))),n("fill",A("none")),n("layer","F.CrtYd")))
    edge = source["pcb_edge_y"]
    # AI:使用Dwgs.User作为板边参考，不能把封装内参考线写成实际Edge.Cuts。
    fp.append(n("fp_line",n("start",-5.5,edge),n("end",5.5,edge),
                n("stroke",n("width",0.1),n("type",A("default"))),n("layer","Dwgs.User")))
    for kind,label,x,y,layer,size in [("reference","REF**",0,-3,"F.SilkS",1),
                                      ("value",NAME,0,8,"F.Fab",0.7),
                                      ("user","PCB EDGE",0,5.2,"Dwgs.User",0.6)]:
        fp.append(n("fp_text",A(kind),label,n("at",x,y),n("layer",layer),
                    n("effects",n("font",n("size",size,size),n("thickness",0.12)))))
    (out / "AI_MCUTOOL.pretty" / (NAME+".kicad_mod")).write_text(dumps(fp)+"\n","utf-8")
    return {"footprint":NAME,"source":source["source"],"sourceFile":"typec-footprint-source.json",
            "pads":[p["number"] for p in source["pads"] if p["number"]],
            "report":"../../docs/电源连接器封装核定.md","manufacturingReview":"已按厂家铜盘/槽孔核定；实际采购图版、钢网及装配待确认"}
