"""@brief AI:按厂家顶视图及项目端子约定检查封装朝向和已核本体装配边界。"""
import argparse
import json
import math
from pathlib import Path

from kicad_sexpr import parse, children, child


def check_dc(project):
    """@brief AI:按XKB DC-005-5A-2.0底视图独立核验顶视坐标、触点编号和孔槽。
    @param project KiCad工程目录。
    @return DC封装检查记录；不读取生成输入。
    """
    name="DC_XKB_DC005_5A_2_0"
    document=parse((project/"AI_MCUTOOL.pretty"/(name+".kicad_mod")).read_text("utf-8"))
    items=children(document,"pad")
    pads={p[1]:p for p in items}
    errors=[]
    # AI:厂家BOTTOM VIEW沿Y反射为元件面；1中心、2套筒、3常闭切换，插口朝左。
    expected={"1":(0,0,1,3.5),"2":(-6,0,1,3),"3":(-3,4.7,3,1)}
    if len(items)!=3 or set(pads)!=set(expected):
        errors.append("DC应仅有1/2/3三个编号通孔")
    for number,(x,y,dw,dh) in expected.items():
        if number not in pads:
            continue
        pad=pads[number]
        xy=tuple(map(float,child(pad,"at")[1:3]))
        drill=child(pad,"drill")
        if xy!=(x,y):
            errors.append(number+"元件面孔位错误或镜像")
        if pad[2]!="thru_hole" or not drill or drill[1]!="oval" or tuple(map(float,drill[2:]))!=(dw,dh):
            errors.append(number+"金属化槽孔尺寸不符厂家图")
        w,h=map(float,child(pad,"size")[1:3])
        if min((w-dw)/2,(h-dh)/2)<0.4-1e-6:
            errors.append(number+"铜环小于本项目选定的0.4mm")
    return {"footprint":name,"passed":not errors,"errors":errors}


def check_typec(project):
    """@brief AI:独立按HRO 2020-12-08图检查电气铜盘顺序、槽孔和定位孔。
    @param project KiCad工程目录。
    @return Type-C检查记录，不读取生成器输入文件。
    """
    name="USB_C_HRO_TYPE_C_31_M_12"
    document=parse((project/"AI_MCUTOOL.pretty"/(name+".kicad_mod")).read_text("utf-8"))
    pads=children(document,"pad")
    numbered={p[1]:p for p in pads if p[1]}
    errors=[]
    row=["A1B12","A4B9","B8","A5","B7","A6","A7","B6","A8","B5","B4A9","B1A12"]
    xs=[-3.2,-2.4,-1.75,-1.25,-0.75,-0.25,0.25,0.75,1.25,1.75,2.4,3.2]
    expected={number:(x,-1.07,0.6 if i in (0,1,10,11) else 0.3,1.14) for i,(number,x) in enumerate(zip(row,xs))}
    expected.update({"1":(-4.325,-0.5,0.9,2.0),"2":(4.325,-0.5,0.9,2.0),
                     "3":(-4.325,3.68,0.9,1.7),"4":(4.325,3.68,0.9,1.7)})
    if set(numbered)!=set(expected) or len(pads)!=18:
        errors.append("Type-C应为16个编号铜盘和2个定位孔")
    for number,values in expected.items():
        if number not in numbered:
            continue
        pad=numbered[number]
        actual=tuple(map(float,child(pad,"at")[1:3]+child(pad,"size")[1:3]))
        if any(abs(a-b)>1e-6 for a,b in zip(actual,values)):
            errors.append(number+"铜盘尺寸/位置不符厂家图")
        if number in row:
            if pad[2]!="smd" or child(pad,"layers")[1:]!=["F.Cu","F.Paste","F.Mask"]:
                errors.append(number+"应为正面贴片铜盘")
        else:
            drill=child(pad,"drill")
            expected_drill=["oval","0.6","1.7" if number in ("1","2") else "1.4"]
            if pad[2]!="thru_hole" or not drill or list(map(str,drill[1:]))!=expected_drill:
                errors.append(number+"外壳固定脚金属化槽孔不符")
    holes=[p for p in pads if not p[1]]
    locations=sorted(tuple(map(float,child(p,"at")[1:3])) for p in holes)
    if locations!=[(-2.89,0.0),(2.89,0.0)]:
        errors.append("定位孔间距或基准错误")
    for pad in holes:
        if pad[2]!="np_thru_hole" or child(pad,"drill")[1:]!=["0.6"]:
            errors.append("定位孔应为0.60mm非金属化孔")
    if any(child(line,"layer")[1]=="Edge.Cuts" for line in children(document,"fp_line")):
        errors.append("封装板边参考不可创建实际板框")
    return {"footprint":name,"passed":not errors,"errors":errors}


def check_geometry(project):
    """@brief AI:独立检查输出封装几何，不读取生成器或来源库坐标。
    @param project KiCad工程目录，须包含AI_MCUTOOL.pretty。
    @return 二元组：逐封装检查记录、错误文本列表；不修改封装。
    """
    records = []
    errors = []
    # AI:相对方向按厂家顶视图及本项目固定放置方向定义；脚号齐全不能代替此检查。
    orders = {
        "N_FET": (["8", "7", "6", "5"], ["1", "2", "3", "4"]),
        "P_FET": (["8", "7", "6", "5"], ["1", "2", "3", "4"]),
        "PHOTO_PV": (["4", "3"], ["1", "2"]),
        "PHOTO_MOS": (["1", "6"], ["3", "4"]),
        "SHUNT4": (["1", "3"], ["2", "4"]),
        "SW4": (["1", "2"], ["3", "4"]),
    }
    for name, (upper, lower) in orders.items():
        document = parse((project / "AI_MCUTOOL.pretty" / (name + ".kicad_mod")).read_text("utf-8"))
        pads = {str(p[1]): p for p in children(document, "pad")}
        positions = {number: tuple(map(float, child(pad, "at")[1:3])) for number, pad in pads.items()}
        check = {"footprint": name, "errors": []}
        required = set(upper + lower)
        if not required.issubset(positions):
            check["errors"].append("缺少方向检查所需焊盘")
        else:
            for row in (upper, lower):
                if any(positions[a][0] >= positions[b][0] for a, b in zip(row, row[1:])):
                    check["errors"].append("左右脚号排列与已核顶视图不符")
            if max(positions[p][1] for p in upper) >= min(positions[p][1] for p in lower):
                check["errors"].append("上下脚号排列镜像或错位")
        if name == "SHUNT4":
            # AI:Vishay 30108第2页，0.005～0.2Ω档；外侧边齐平与0.51mm铜间隙独立核验。
            expected = {"1": (-2.985,-0.635,2.29,2.03), "2": (-3.28,1.27,1.70,0.76),
                        "3": (3.28,-1.27,1.70,0.76), "4": (2.985,0.635,2.29,2.03)}
            for number, values in expected.items():
                if number not in pads:
                    continue
                at = child(pads[number], "at")
                actual = (*positions[number], *map(float, child(pads[number], "size")[1:3]))
                if any(abs(a-b)>1e-6 for a,b in zip(actual,values)) or (len(at)>3 and float(at[3])%180):
                    check["errors"].append("WSK2512焊盘"+number+"不符合厂家推荐尺寸或位置")
        if name in ("N_FET", "P_FET", "PHOTO_PV", "SHUNT4"):
            # AI:TI第8页给出本方向MOS最大3.25×3.10mm；Vishay第5页的VOM外形按4.92最大及4.57+0.25mm。
            half_x,half_y = (2.46,2.41) if name == "PHOTO_PV" else (1.625,1.55)
            if name == "SHUNT4":
                half_x,half_y = 3.302,1.717
            corners = [(-half_x, -half_y), (half_x, half_y)]
            for pad in pads.values():
                at = child(pad, "at")
                x, y = map(float, at[1:3])
                angle = math.radians(float(at[3]) if len(at) > 3 else 0)
                width, height = map(float, child(pad, "size")[1:3])
                for dx in (-width / 2, width / 2):
                    for dy in (-height / 2, height / 2):
                        corners.append((x + dx * math.cos(angle) + dy * math.sin(angle),
                                        y - dx * math.sin(angle) + dy * math.cos(angle)))
            courtyard = [r for r in children(document, "fp_rect") if child(r, "layer")[1] == "F.CrtYd"]
            if len(courtyard) != 1:
                check["errors"].append("必须具有一个明确的矩形Courtyard")
            else:
                x1, y1 = map(float, child(courtyard[0], "start")[1:3])
                x2, y2 = map(float, child(courtyard[0], "end")[1:3])
                margins = [min(p[0] for p in corners) - x1, min(p[1] for p in corners) - y1,
                           x2 - max(p[0] for p in corners), y2 - max(p[1] for p in corners)]
                check["courtyardMm"] = [round(x2 - x1, 4), round(y2 - y1, 4)]
                check["minimumMarginMm"] = round(min(margins), 4)
                if min(margins) < 0.25 - 1e-6:
                    check["errors"].append("Courtyard未在最大本体和焊盘外保留至少0.25mm")
            if name in ("N_FET", "P_FET") and ("9" not in positions or positions["9"][1] >= 0):
                check["errors"].append("散热焊盘未处于5～8脚一侧")
            if not any(child(line, "layer")[1] == "F.Fab" for line in children(document, "fp_line")):
                check["errors"].append("缺少本体及1脚方向的Fab轮廓")
        check["passed"] = not check["errors"]
        errors.extend(name + ": " + message for message in check["errors"])
        records.append(check)
    typec=check_typec(project)
    records.append(typec)
    errors.extend(typec["footprint"]+": "+message for message in typec["errors"])
    dc=check_dc(project)
    records.append(dc)
    errors.extend(dc["footprint"]+": "+message for message in dc["errors"])
    return records, errors


def main():
    """@brief AI:执行封装几何检查，可将结果写入指定JSON文件。
    @return None；几何不符时以非零退出码结束。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1] / "kicad")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records, errors = check_geometry(args.project)
    report = {"passed": not errors, "checks": records, "errors": errors,
              "scope": "编号方向、MOS/VOM/SHUNT4装配边界、WSK2512及HRO推荐铜盘/孔位；不替代钢网及完整制造审查"}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
