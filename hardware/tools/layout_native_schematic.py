"""@brief AI:对编辑器真实源码调整版面、重复标签和NC坐标，不改变引脚网络。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "hardware/easyeda-pro/rev-a"


def rows(source):
    """@brief AI:解析编辑器导出的逐行原生记录。
    @param source 实际getDocumentSource结果。
    @return 记录头及载荷的列表。
    """
    return [(json.loads(h), json.loads(b.rstrip("|"))) for h, b in (line.split("||", 1) for line in source.splitlines())]


def main():
    """@brief AI:按已有图元ID生成仅供本工程使用的版面修正脚本。
    @return None；源文件及前后记录可回查，运行脚本后仍需重导网表。
    """
    # AI:固定使用第一次布局前的回读，避免再次翻转已校正的NC坐标或累加平移。
    report = json.loads((DATA / "native-verification-before-layout.json").read_text("utf-8"))
    binding = json.loads((DATA / "binding.json").read_text("utf-8"))
    record_map = {}
    for filename in ["library-records.json", "passives-connectors.json", "passive-records.json"]:
        record_map.update({r["name"]: r for r in json.loads((DATA / filename).read_text("utf-8"))["records"]})
    by_ref = {c["ref"]: c for c in binding["components"]}
    plans = []
    for page in report["pages"]:
        number = page["name"][:2]
        parsed = rows(page["source"])
        comps = page["components"]
        column_count = 8 if number == "07" else 5
        last_row = (len(comps) - 1) // column_count
        shift_up = 200 - (220 - last_row * 260)
        paper = "A1" if number in ["03", "07"] else "A2"
        deltas = {}
        comp_deltas = {}
        for index, comp in enumerate(comps):
            x = 260 + index % column_count * 350
            y = 220 - index // column_count * 260 + shift_up
            delta = (x - comp["x"], -(y - comp["y"]))
            comp_deltas[comp["primitiveId"]] = delta
            deltas[comp["primitiveId"]] = delta

        def nearest(x, y):
            """@brief AI:短导线/端口按原始局部器件归组，不按网络名跨器件移动。
            @param x 原生横坐标。
            @param y 原生向下纵坐标。
            @return 该局部器件的平移向量。
            """
            owner = min(comps, key=lambda c: (x - c["x"]) ** 2 + (y + c["y"]) ** 2)
            return comp_deltas[owner["primitiveId"]]

        sheet_ids = {b["parentId"] for h, b in parsed if h["type"] == "ATTR" and b["key"] == "Border"}
        # AI:先给所有实体及导线组归属，再处理它们的属性，防止标签与连接点分离。
        for head, body in parsed:
            if head["type"] == "COMPONENT" and head["id"] not in deltas:
                if head["id"] not in sheet_ids:
                    deltas[head["id"]] = nearest(body["x"], body["y"])
            elif head["type"] == "LINE":
                deltas[body["lineGroup"]] = nearest(body["startX"], body["startY"])
        name_defaults = {}
        for comp in comps:
            ref = comp["designator"]
            if ref != "RSH1":
                name_defaults[comp["primitiveId"]] = record_map[by_ref[ref]["library_name"]]["device"]["property"].get("otherProperty", {}).get("Name", "")
        for head, body in parsed:
            typ = head["type"]
            if typ == "COMPONENT":
                dx, dy = deltas.get(head["id"], (0, 0))
                body["x"] += dx
                body["y"] += dy
            elif typ == "LINE":
                dx, dy = deltas[body["lineGroup"]]
                for key in ["startX", "endX"]:
                    body[key] += dx
                for key in ["startY", "endY"]:
                    body[key] += dy
            elif typ == "ATTR":
                parent = body.get("parentId", "")
                if body["key"] == "NO_CONNECT":
                    # AI:V4.1.78的pin.modify把API向上Y原样写入向下源码；只校正已核该属性。
                    body["y"] = -body["y"]
                    parent = parent.split("-", 1)[0]
                dx, dy = deltas.get(parent, (0, 0))
                if isinstance(body.get("x"), (int, float)):
                    body["x"] += dx
                if isinstance(body.get("y"), (int, float)):
                    body["y"] += dy
                if body["key"] == "NET":
                    body["valueVisible"] = False
                elif body["key"] == "Name" and parent in name_defaults:
                    body["value"] = name_defaults[parent]
            elif typ == "TEXT":
                body["y"] -= shift_up
        # AI:保留库默认名称以维持料号属性匹配；接口用途作为独立说明文字显示。
        ticket = max(h.get("ticket", 0) for h, _ in parsed)
        for comp in comps:
            ref = comp["designator"]
            if not (ref.startswith(("J", "SW", "LED")) or ref == "U4"):
                continue
            dx, dy = comp_deltas[comp["primitiveId"]]
            ticket += 1
            parsed.append(({"type": "TEXT", "ticket": ticket, "id": "ai_function_" + ref},
                           {"x": comp["x"] + dx - 70, "y": -comp["y"] + dy - (190 if ref == "U4" else 100),
                            "rotation": 0, "color": None, "fontFamily": None, "fontSize": 12,
                            "fontWeight": True, "italic": False, "underline": False, "align": "LEFT_BOTTOM",
                            "value": by_ref[ref]["value"], "fillColor": None, "zIndex": ticket}))
        text = "\n".join(json.dumps(h, ensure_ascii=False, separators=(",", ":")) + "||" + json.dumps(b, ensure_ascii=False, separators=(",", ":")) + "|" for h, b in parsed) + "\n"
        plans.append({"uuid": page["uuid"], "name": page["name"], "paper": paper, "source": text})
    script = "const PAGES = " + json.dumps(plans, ensure_ascii=False) + ";\n" + r'''
/**
 * @brief AI:应用已从真实原生源码生成的版面修正，保留元件、网络和图元ID。
 * @returns {Promise<void>} 保存八页，结果仍须重新导出网表与DRC核验。
 */
async function main() {
  const project = await eda.dmt_Project.getCurrentProjectInfo();
  if (project?.uuid !== "57a0364c842149baada4fb3ca7ccf03f") throw new Error("工程不匹配");
  for (const page of PAGES) {
    await eda.dmt_EditorControl.openDocument(page.uuid);
    if (!await eda.sys_FileManager.setDocumentSource(page.source)) throw new Error("源码应用失败: " + page.name);
    if (!await eda.dmt_Schematic.modifySchematicPageTitleBlock(true, {
      Size: {showTitle: false, showValue: false, value: page.paper},
      Border: {showTitle: false, showValue: false, value: "1"},
      "Title Block": {showTitle: false, showValue: false, value: "1"},
      Version: {showTitle: true, showValue: true, value: "A-DRAFT"},
    })) throw new Error("图纸尺寸应用失败: " + page.name);
    await eda.sch_Document.save();
  }
  eda.sys_Dialog.showInformationMessage("图面、NC标记及器件名称已修正；请重新导出核对。", "版面修正完成", "关闭");
}
main().catch(error => eda.sys_Dialog.showInformationMessage(String(error), "版面修正失败", "关闭"));
'''
    (ROOT / "hardware/easyeda-pro/scripts/11-layout-schematic.js").write_text(script, "utf-8")
    print("已生成八页版面修正脚本；未直接修改工程。")


if __name__ == "__main__":
    main()
