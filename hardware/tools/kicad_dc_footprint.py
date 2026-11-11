"""@brief AI:按具体DC插座厂家图建立保留项目端子约定的直插封装。"""
import json
from kicad_sexpr import Atom as A, dumps

NAME = "DC_XKB_DC005_5A_2_0"


def make_dc(out, n):
    """@brief AI:从固定厂家图参数生成DC插座铜盘、孔槽、本体和装配边界。
    @param out KiCad工程目录，含dc-footprint-source.json。
    @param n S表达式节点构造函数。
    @return 来源记录字典；生成项目封装，不更改电路连接。
    """
    source=json.loads((out/"dc-footprint-source.json").read_text("utf-8"))
    if source["units"]!="mm" or source["coordinateFrame"]!="component-side-x-right-y-down":
        raise ValueError("DC插座来源坐标或单位不匹配")
    fp=n("footprint",NAME,n("version",20241229),n("generator",A("pcbnew")),n("layer","F.Cu"),
         n("descr",source["source"]),n("attr",A("through_hole")))
    for pad in source["pads"]:
        if pad["type"]!="thru_hole":
            raise ValueError("DC插座必须使用已核定的金属化通孔")
        w,h=pad["drill"]
        drill=n("drill",w) if w==h else n("drill",A("oval"),w,h)
        if pad["shape"] not in ("rect","oval"):
            raise ValueError("DC铜盘形状未核定")
        fp.append(n("pad",pad["number"],A("thru_hole"),A(pad["shape"]),n("at",*pad["xy"]),
                    n("size",*pad["size"]),drill,n("layers","*.Cu","*.Mask")))
    body=source["body_nominal"]
    for box,layer,width in [(body,"F.Fab",0.1),(source["courtyard"],"F.CrtYd",0.05)]:
        fp.append(n("fp_rect",n("start",box["x_min"],box["y_min"]),n("end",box["x_max"],box["y_max"]),
                    n("stroke",n("width",width),n("type",A("default"))),n("fill",A("none")),n("layer",layer)))
    for kind,label,y,layer in [("reference","REF**",body["y_min"]-1.5,"F.SilkS"),
                                ("value",NAME,body["y_max"]+1.5,"F.Fab")]:
        fp.append(n("fp_text",A(kind),label,n("at",(body["x_min"]+body["x_max"])/2,y),n("layer",layer),
                    n("effects",n("font",n("size",0.8,0.8),n("thickness",0.12)))))
    (out/"AI_MCUTOOL.pretty"/(NAME+".kicad_mod")).write_text(dumps(fp)+"\n","utf-8")
    return {"footprint":NAME,"source":source["source"],"sourceFile":"dc-footprint-source.json",
            "pads":[pad["number"] for pad in source["pads"]],"report":"../../docs/电源连接器封装核定.md",
            "manufacturingReview":"按厂家孔位及触点映射建立；实物配合与焊接工艺待样机确认"}
