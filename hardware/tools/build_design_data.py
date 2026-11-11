"""@brief AI:生成嘉立创原理图绘制所需的连接数据；不伪造原生EDA工程。"""

import hashlib
import json
from collections import defaultdict
from pathlib import Path


# AI:所有输出均保存在本工程硬件目录，原始依据仍为已确认的模块方案。
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "hardware" / "easyeda-pro" / "rev-a"
GND = "COMMON_GND"
VCC = "TOOL_3V3"
PAGES = [
    ("01", "工具五伏输入与三点三伏稳压"),
    ("02", "ESP32最小系统与共享总线"),
    ("03", "五路按键模拟"),
    ("04", "双路主供电选择"),
    ("05", "独立充电通路"),
    ("06", "电池端电流与电压采样"),
    ("07", "四路高阻电压检测"),
    ("08", "目标UART收发"),
]
PARTS = []


def add(ref, page, value, package, pins, *, mpn=None, note="", numbering="datasheet"):
    """@brief AI:登记器件及逐引脚连接，空网络表示明确不接。
    @param ref 唯一位号。
    @param page 所属图页编号。
    @param value 标称值或器件名称。
    @param package 已核封装名称或待核的封装方向，不是EDA库绑定。
    @param pins 引脚编号到名称、网络二元组的映射。
    @param mpn 已核完整料号；未选定时为None。
    @param note 选型、焊盘或电气验证说明。
    @param numbering 编号依据，区分厂商编号与逻辑端子。
    @return None；器件追加至PARTS。
    """
    PARTS.append({
        "ref": ref, "page": page, "value": value, "mpn": mpn,
        "package": package, "library_binding": "unbound",
        "footprint_verified": False, "pin_numbering": numbering, "note": note,
        "pins": [{"number": str(num), "name": name, "net": net}
                 for num, (name, net) in pins.items()],
    })


def resistor(number, page, value, a, b, *, package="0603", mpn=None, note="1%，额定≥0.1W初值"):
    """@brief AI:登记无极性两端电阻。
    @param number R位号数字。
    @param page 所属图页。
    @param value 阻值文本。
    @param a 1脚网络。
    @param b 2脚网络。
    @param package 封装方向。
    @param mpn 已选料号或None。
    @param note 精度、温漂或功率说明。
    @return None；追加器件。
    """
    add(f"R{number}", page, value, package, {1: ("1", a), 2: ("2", b)},
        mpn=mpn, note=note, numbering="symmetric-passive")


def capacitor(number, page, value, a, b=GND, *, note="陶瓷；具体料号、耐压及有效容量待核"):
    """@brief AI:登记无极性陶瓷电容，不假定标称容量等于有效容量。
    @param number C位号数字。
    @param page 所属图页。
    @param value 容量文本。
    @param a 1脚网络。
    @param b 2脚网络，默认公共地。
    @param note 电容选型条件。
    @return None；追加器件。
    """
    add(f"C{number}", page, value, "MLCC，尺寸待料号确定",
        {1: ("1", a), 2: ("2", b)}, note=note, numbering="symmetric-passive")


def header(number, page, name, nets):
    """@brief AI:登记已确认的朝上2.54mm单排接口。
    @param number J位号数字。
    @param page 所属图页。
    @param name 丝印端口名称。
    @param nets 按针号顺序排列的名称、网络二元组列表。
    @return None；追加接口，具体采购型号尚未绑定。
    """
    add(f"J{number}", page, name, f"2.54mm直排针1x{len(nets)}",
        dict(enumerate(nets, 1)), note="元件面1脚方焊盘；板端、线端及压降待选型核验",
        numbering="project-header-order")


def npn(number, page, base, collector):
    """@brief AI:登记已核B1/E2/C3的MMBT3904低侧驱动。
    @param number Q位号数字。
    @param page 所属图页。
    @param base 基极网络。
    @param collector 集电极网络。
    @return None；发射极固定接工具公共地。
    """
    add(f"Q{number}", page, "MMBT3904LT1G", "SOT-23",
        {1: ("B", base), 2: ("E", GND), 3: ("C", collector)}, mpn="MMBT3904LT1G")


def power_mos(number, page, mpn, drain, gate, source):
    """@brief AI:登记两类MOS的全部焊盘，保留不同底盘电气定义。
    @param number Q位号数字。
    @param page 所属图页。
    @param mpn 已确认的N-MOS或P-MOS料号。
    @param drain 漏极网络。
    @param gate 栅极网络。
    @param source 源极网络。
    @return None；未知料号直接报错，不按相似封装自动替代。
    """
    if mpn == "CSD17577Q3A":
        drains, sources = (5, 6, 7, 8, 9), (1, 2, 3)
        note = "底部9脚为D；不得与共源铜混接"
    elif mpn == "CSD25402Q3A":
        drains, sources = (1, 2, 3), (5, 6, 7, 8, 9)
        note = "底部9脚为S；与主通路N-MOS的底盘定义不同"
    else:
        raise ValueError(f"未定义MOS引脚: {mpn}")
    pins = {n: ("D", drain) for n in drains}
    pins.update({n: ("S", source) for n in sources})
    # AI:按TI可见顶视图核对，两个型号的Gate均为4脚，不能沿用错位的PDF文本层。
    pins[4] = ("G", gate)
    add(f"Q{number}", page, mpn, "SON Q3A，3.3x3.3mm", dict(sorted(pins.items())),
        mpn=mpn, note=note)


def build():
    """@brief AI:按八个功能页构建已确认连接及明确标出的外围初值。
    @return None；写入内存PARTS，不操作EDA或云端工程。
    """
    PARTS.clear()
    # AI:DC/Type-C尚未选完整型号，使用逻辑端子，禁止冒充真实焊盘号。
    add("J1", "01", "DC_IN_5V", "DC5.5x2.1mm中心正，料号待定",
        {"POS": ("正端", "DC_IN_5V"), "NEG": ("负端", GND)},
        note="实际插座的切换脚和机械焊盘需按料号补齐", numbering="logical-terminal")
    add("J2", "01", "TYPEC_IN_5V", "Type-C受电座，料号待定",
        {"VBUS": ("VBUS", "TYPEC_IN_5V"), "GND": ("GND", GND),
         "CC1": ("CC1", "TYPEC_CC1"), "CC2": ("CC2", "TYPEC_CC2")},
        note="仅逻辑接口；具体VBUS/GND重复焊盘及外壳焊盘须按所选连接器展开",
        numbering="logical-terminal")
    for idx, net in ((1, "DC_IN_5V"), (2, "TYPEC_IN_5V")):
        add(f"U{idx}", "01", "LM66100DCKR", "SC-70-6 / DCK",
            {1: ("VIN", net), 2: ("GND", GND), 3: ("CE", "LDO_VIN"),
             4: ("NC", GND), 5: ("ST", GND), 6: ("VOUT", "LDO_VIN")},
            mpn="LM66100DCKR", note="CE接本颗VOUT；不使用ST建立优先级")
        resistor(idx, "01", "4.7k", net, GND)
        capacitor(idx, "01", "1uF", net, note="≥10V/X7R方向；就近VIN")
    resistor(3, "01", "5.1k", "TYPEC_CC1", GND)
    resistor(4, "01", "5.1k", "TYPEC_CC2", GND)
    add("U3", "01", "LDL1117S33R", "SOT223",
        {1: ("GND", GND), 2: ("OUT", VCC), 3: ("IN", "LDO_VIN")},
        mpn="LDL1117S33R", note="Tab与OUT同网；散热、启动稳定性和掉电反流待验证")
    capacitor(3, "01", "4.7uF", "LDO_VIN", note="16V/X7R；有效容量≥1uF")
    capacitor(4, "01", "4.7uF", VCC, note="10V/X7R；与模组及所有输出去耦联合验证")

    # AI:模组焊盘来自官方v1.8表3-1；不能按GPIO编号顺序生成。
    mcu = {
        1: ("GND", GND), 2: ("3V3", VCC), 3: ("EN", "ESP_EN"),
        4: ("IO4", "KEY1_CTRL"), 5: ("IO5", "KEY2_CTRL"),
        6: ("IO6", "KEY3_CTRL"), 7: ("IO7", "KEY4_CTRL"),
        8: ("IO15", "DUT_UART_RX"), 9: ("IO16", "STATUS_LED"),
        10: ("IO17", "CONFIG_KEY"), 11: ("IO18", "CURRENT_ALERT"),
        12: ("IO8", "KEY5_CTRL"), 13: ("IO19", None), 14: ("IO20", None),
        15: ("IO3", "ESP_IO3_STRAP"), 16: ("IO46", "ESP_IO46_STRAP"),
        17: ("IO9", "I2C_SDA"), 18: ("IO10", "I2C_SCL"),
        19: ("IO11", "BAT_PATH_EN"), 20: ("IO12", "EXT_PATH_EN"),
        21: ("IO13", "CHARGE_PATH_EN"), 22: ("IO14", "DUT_UART_TX"),
        23: ("IO21", None), 24: ("IO47", None), 25: ("IO48", None),
        26: ("IO45", None), 27: ("IO0", "ESP_BOOT"),
        28: ("IO35", None), 29: ("IO36", None), 30: ("IO37", None),
        31: ("IO38", "UART_TX_nOE"), 32: ("IO39", None),
        33: ("IO40", None), 34: ("IO41", None), 35: ("IO42", None),
        36: ("RXD0", "UART0_RX"), 37: ("TXD0", "UART0_TX"),
        38: ("IO2", None), 39: ("IO1", None), 40: ("GND", GND), 41: ("EPAD", GND),
    }
    add("U4", "02", "ESP32-S3-WROOM-1-N16R8", "官方WROOM-1模组封装", mcu,
        mpn="ESP32-S3-WROOM-1-N16R8", note="GPIO21预留但不接ADC_READY；35/36/37被PSRAM占用")
    header(3, "02", "DOWNLOAD", [("TX0", "UART0_TX"), ("RX0", "UART0_RX"),
                                  ("GND", GND), ("BOOT", "ESP_BOOT"), ("EN", "ESP_EN")])
    for idx, net in ((5, "ESP_EN"), (6, "ESP_BOOT"), (9, "CONFIG_KEY")):
        resistor(idx, "02", "10k", VCC, net)
    resistor(7, "02", "10k", "ESP_IO46_STRAP", GND)
    resistor(8, "02", "10k", "ESP_IO3_STRAP", GND)
    for idx, name, net in ((1, "RESET", "ESP_EN"), (2, "BOOT", "ESP_BOOT"), (3, "CONFIG", "CONFIG_KEY")):
        add(f"SW{idx}", "02", name, "常开轻触按键，料号待定",
            {"A": ("A", net), "B": ("B", GND)}, numbering="logical-terminal",
            note="若选四焊盘按键，需按真实内部并接关系展开封装映射")
    # AI:LED的1k仅是本次画图初值，亮度及实际料号仍需核验。
    for idx, ref, net in ((10, "LED1", VCC), (11, "LED2", "STATUS_LED")):
        resistor(idx, "02", "1k", net, f"{ref}_A", note="本轮普通低电流LED限流初值，亮度待核")
        add(ref, "02", "电源指示" if ref == "LED1" else "状态指示", "普通LED，料号待定",
            {"A": ("A", f"{ref}_A"), "K": ("K", GND)}, numbering="logical-terminal")
    capacitor(5, "02", "22uF", VCC, note="模组入口；最终偏压下有效容量及LDO启动共同核验")
    capacitor(6, "02", "100nF", VCC)
    capacitor(7, "02", "1uF", "ESP_EN", note="EN复位RC；10k/1uF是初值，实际上电时序须验证")
    resistor(81, "02", "4.7k", VCC, "I2C_SDA", note="唯一一组共享上拉；初值，按总线电容和速率核上升沿")
    resistor(82, "02", "4.7k", VCC, "I2C_SCL", note="唯一一组共享上拉；初值，按总线电容和速率核上升沿")

    for ch in range(1, 6):
        led, collector, base = f"KEY{ch}_LED_A", f"KEY{ch}_LED_K", f"KEY{ch}_BASE"
        add(f"U{ch+4}", "03", "TLP176AM", "SO6-4",
            {1: ("A", led), 3: ("K", collector),
             4: ("CONTACT_A", f"KEY{ch}_A"), 6: ("CONTACT_B", f"KEY{ch}_B")},
            mpn="TLP176AM(TPL,E", note="2/5位置无引脚；准确采购包装后缀待核")
        npn(ch, "03", base, collector)
        start = 12 + (ch-1)*3
        resistor(start, "03", "240", VCC, led)
        resistor(start+1, "03", "680", f"KEY{ch}_CTRL", base)
        resistor(start+2, "03", "10k", base, GND)
        header(ch+3, "03", f"KEY{ch}", [("A", f"KEY{ch}_A"), ("B", f"KEY{ch}_B")])

    for idx, label in enumerate(("BAT", "EXT")):
        scom, gcom = f"SCOM_{label}", f"GCOM_{label}"
        led, collector, base = f"{label}_PV_A", f"{label}_PV_K", f"{label}_BASE"
        add(f"U{10+idx}", "04", "VOM1271T", "SOP-4",
            {1: ("LED_A", led), 2: ("LED_K", collector),
             3: ("PV_NEG", scom), 4: ("PV_POS", gcom)}, mpn="VOM1271T",
            note="光伏输出以本路共源为参考，不接公共地，不外加100k栅源下拉")
        npn(6+idx, "04", base, collector)
        start = 27 + idx*3
        resistor(start, "04", "100", VCC, led, package="1206", note="1%，额定≥0.25W初值")
        resistor(start+1, "04", "330", f"{label}_PATH_EN", base)
        resistor(start+2, "04", "10k", base, GND)
        power_mos(8+idx*2, "04", "CSD17577Q3A", f"{label}_IN_P", gcom, scom)
        power_mos(9+idx*2, "04", "CSD17577Q3A", "VSEL_P", gcom, scom)
    header(9, "04", "BAT_IN", [("+", "BAT_IN_P"), ("GND", GND)])
    header(10, "04", "EXT_IN", [("+", "EXT_IN_P"), ("GND", GND)])
    header(11, "06", "DUT_PWR", [("+", "DUT_PWR_P"), ("GND", GND)])

    power_mos(12, "05", "CSD25402Q3A", "CHG_IN_P", "GCOM_CHG", "SCOM_CHG")
    power_mos(13, "05", "CSD25402Q3A", "DUT_CHG_P", "GCOM_CHG", "SCOM_CHG")
    npn(14, "05", "CHG_BASE", "CHG_GATE_SINK")
    resistor(33, "05", "10k", "GCOM_CHG", "SCOM_CHG")
    resistor(34, "05", "100", "GCOM_CHG", "CHG_GATE_SINK")
    resistor(35, "05", "4.7k", "CHARGE_PATH_EN", "CHG_BASE")
    resistor(36, "05", "10k", "CHG_BASE", GND)
    header(12, "05", "CHG_IN", [("+", "CHG_IN_P"), ("GND", GND)])
    header(13, "05", "DUT_CHG", [("+", "DUT_CHG_P"), ("GND", GND)])

    add("RSH1", "06", "20mOhm", "WSK2512专用四端封装，待库核对",
        {"I1": ("I1", "VSEL_P"), "E1": ("E1", "SHUNT_E1"),
         "I2": ("I2", "DUT_PWR_P"), "E2": ("E2", "SHUNT_E2")},
        mpn="WSK2512R0200BEA", numbering="manufacturer-terminal-name",
        note="官方无数字焊盘号；数字库映射须结合机械图登记，不在器件外短接I/E")
    add("U12", "06", "INA228AIDGSR", "DGS-10 / VSSOP",
        {1: ("A1", GND), 2: ("A0", GND), 3: ("ALERT", "CURRENT_ALERT"),
         4: ("SDA", "I2C_SDA"), 5: ("SCL", "I2C_SCL"), 6: ("VS", VCC),
         7: ("GND", GND), 8: ("VBUS", "DUT_PWR_P"),
         9: ("IN-", "INA_IN_N"), 10: ("IN+", "INA_IN_P")}, mpn="INA228AIDGSR",
        note="7-bit地址0x40；固定宽档；VBUS取电经过分流器")
    resistor(37, "06", "10", "SHUNT_E1", "INA_IN_P")
    resistor(38, "06", "10", "SHUNT_E2", "INA_IN_N")
    resistor(39, "06", "10k", VCC, "CURRENT_ALERT")
    capacitor(8, "06", "100nF", "INA_IN_P", "INA_IN_N", note="芯片侧差模滤波，不对地")
    capacitor(9, "06", "100nF", VCC)

    add("U13", "07", "ADS1115IDGSR", "DGS-10 / VSSOP",
        {1: ("ADDR", GND), 2: ("ALERT/RDY", None), 3: ("GND", GND),
         4: ("AIN0", "ADC_CH1"), 5: ("AIN1", "ADC_CH2"),
         6: ("AIN2", "ADC_CH3"), 7: ("AIN3", "ADC_CH4"),
         8: ("VDD", VCC), 9: ("SDA", "I2C_SDA"), 10: ("SCL", "I2C_SCL")},
        mpn="ADS1115IDGSR", note="地址0x48；OS轮询，ALERT/RDY明确不连接")
    opa_pins = {4: ("V+", VCC), 11: ("V-", "VNEG")}
    for ch, (pos, neg, output) in enumerate(((3, 2, 1), (5, 6, 7), (10, 9, 8), (12, 13, 14)), 1):
        opa_pins.update({pos: (f"IN{ch}+", f"DIV{ch}"),
                         neg: (f"IN{ch}-", f"FB{ch}"), output: (f"OUT{ch}", f"BUF{ch}")})
        header(13+ch, "07", f"AIN{ch}", [("AIN", f"AIN{ch}"), ("GND", GND)])
        start = 40 + (ch-1)*9
        chain = [f"AIN{ch}"] + [f"AIN{ch}_DIV_TAP{k}" for k in range(1, 5)] + [f"DIV{ch}"]
        for k in range(5):
            resistor(start+k, "07", "2M", chain[k], chain[k+1], package="1206",
                     mpn="TNPW12062M00BEEA", note="0.1%，25ppm/℃；上臂5颗串联")
        resistor(start+5, "07", "1M", f"DIV{ch}", GND, package="0805",
                 mpn="TNPW08051M00BEEA", note="0.1%，25ppm/℃；下臂")
        resistor(start+6, "07", "499", f"BUF{ch}", f"FB{ch}", note="0.1%，≤25ppm/℃；反馈在100Ω隔离电阻之前")
        resistor(start+7, "07", "100k", f"FB{ch}", "VNEG", note="0.1%，≤25ppm/℃；接负轨，不能接地")
        resistor(start+8, "07", "100", f"BUF{ch}", f"ADC_CH{ch}")
        capacitor(10+(ch-1)*2, "07", "10nF", f"DIV{ch}", note="优先C0G/NP0；高阻节点漏电须核算")
        capacitor(11+(ch-1)*2, "07", "10nF", f"ADC_CH{ch}")
    add("U14", "07", "OPA4391PWR", "PW-14 / TSSOP", dict(sorted(opa_pins.items())),
        mpn="OPA4391PWR", note="单颗四运放；第11脚必须接VNEG，四通道共享电源")
    add("U15", "07", "LM7705MM/NOPB", "DGK-8 / VSSOP",
        {1: ("CF+", "LM_CF_P"), 2: ("VSS", GND), 3: ("SD", GND),
         4: ("VDD", VCC), 5: ("VSS", GND), 6: ("VOUT", "VNEG"),
         7: ("CRES", "LM_CRES"), 8: ("CF-", "LM_CF_N")}, mpn="LM7705MM/NOPB",
        note="SD接地常开；CRES与VNEG独立；正轨低端性能待验证")
    capacitor(18, "07", "100nF", VCC, note="ADS1115就近去耦")
    capacitor(19, "07", "100nF", VCC, "VNEG", note="OPA4391跨正负轨去耦")
    capacitor(20, "07", "100nF", VCC, note="LM7705就近输入去耦")
    capacitor(21, "07", "10uF", "LM_CF_P", "LM_CF_N", note="飞跨标称候选；按官方5uF有效容量条件核验具体料号")
    capacitor(22, "07", "22uF", "LM_CRES", note="独立储能；偏压、有效容量及ESR待核")
    capacitor(23, "07", "22uF", "VNEG", note="负轨输出；陶瓷无极性，不能使用反接极性电容")
    capacitor(24, "07", "100nF", "VNEG", note="负轨高频旁路")
    capacitor(25, "07", "100nF", VCC, note="OPA4391正轨对地就近去耦，与跨轨去耦统一核算")

    add("U16", "08", "SN74AUP1G125DBVR", "DBV-5 / SOT-23",
        {1: ("/OE", "UART_TX_nOE"), 2: ("A", "DUT_UART_TX"), 3: ("GND", GND),
         4: ("Y", "UART_TX_BUF"), 5: ("VCC", VCC)}, mpn="SN74AUP1G125DBVR")
    add("U17", "08", "74LVC1G17GV,125", "SOT753 / SC-74A",
        {1: ("NC", None), 2: ("A", "UART_RX_IN"), 3: ("GND", GND),
         4: ("Y", "DUT_UART_RX"), 5: ("VCC", VCC)}, mpn="74LVC1G17GV,125")
    resistor(76, "08", "10k", VCC, "UART_TX_nOE")
    resistor(77, "08", "100k", VCC, "DUT_UART_TX")
    resistor(78, "08", "470k", "UART_RX_IN", GND)
    resistor(79, "08", "100", "UART_TX_BUF", "TOOL_TX")
    resistor(80, "08", "100", "TOOL_RX", "UART_RX_IN")
    capacitor(26, "08", "100nF", VCC, note="TX缓冲器就近去耦")
    capacitor(27, "08", "100nF", VCC, note="RX缓冲器就近去耦")
    header(18, "08", "DUT_UART", [("TX", "TOOL_TX"), ("RX", "TOOL_RX"), ("GND", GND)])


def check():
    """@brief AI:检查连接数据的结构和关键跨模块关系，不替代EDA电气规则检查。
    @return 字典：器件、网络、明确不接引脚及已执行检查的数量。
    @raises ValueError 位号重复、未定义页面或关键网络与方案不符。
    """
    refs = [p["ref"] for p in PARTS]
    if len(refs) != len(set(refs)):
        raise ValueError("存在重复位号")
    pages = {p[0] for p in PAGES}
    parts = {p["ref"]: p for p in PARTS}
    pins = {(p["ref"], pin["number"]): pin["net"] for p in PARTS for pin in p["pins"]}
    for part in PARTS:
        if part["page"] not in pages:
            raise ValueError(f"未定义页面: {part['ref']}")
        numbers = [pin["number"] for pin in part["pins"]]
        if len(numbers) != len(set(numbers)):
            raise ValueError(f"引脚号重复: {part['ref']}")
    expected = {
        ("U1", "3"): "LDO_VIN", ("U2", "3"): "LDO_VIN", ("U3", "2"): VCC,
        ("U4", "8"): "DUT_UART_RX", ("U4", "12"): "KEY5_CTRL",
        ("U4", "17"): "I2C_SDA", ("U4", "18"): "I2C_SCL", ("U4", "31"): "UART_TX_nOE",
        ("U4", "23"): None, ("U4", "28"): None, ("U4", "29"): None, ("U4", "30"): None,
        ("Q8", "9"): "BAT_IN_P", ("Q9", "9"): "VSEL_P",
        ("Q10", "9"): "EXT_IN_P", ("Q11", "9"): "VSEL_P",
        ("Q12", "9"): "SCOM_CHG", ("Q13", "9"): "SCOM_CHG",
        ("Q8", "4"): "GCOM_BAT", ("Q8", "1"): "SCOM_BAT", ("Q8", "5"): "BAT_IN_P",
        ("Q10", "4"): "GCOM_EXT", ("Q10", "1"): "SCOM_EXT", ("Q10", "5"): "EXT_IN_P",
        ("Q12", "4"): "GCOM_CHG", ("Q12", "1"): "CHG_IN_P", ("Q12", "5"): "SCOM_CHG",
        ("U12", "8"): "DUT_PWR_P", ("RSH1", "E1"): "SHUNT_E1", ("RSH1", "E2"): "SHUNT_E2",
        ("U13", "2"): None, ("U14", "11"): "VNEG", ("U15", "7"): "LM_CRES",
        ("U15", "6"): "VNEG", ("U16", "1"): "UART_TX_nOE", ("U17", "1"): None,
    }
    for key, net in expected.items():
        if pins.get(key, "MISSING") != net:
            raise ValueError(f"关键连接不符: {key}, 应为{net}")
    if len(parts["U4"]["pins"]) != 41:
        raise ValueError("ESP32模组必须保留41个焊盘条目")
    for ch in range(1, 6):
        for terminal in ("A", "B"):
            net = f"KEY{ch}_{terminal}"
            endpoints = {(p["ref"], pin["number"]) for p in PARTS for pin in p["pins"] if pin["net"] == net}
            want = {(f"U{ch+4}", "4" if terminal == "A" else "6"),
                    (f"J{ch+3}", "1" if terminal == "A" else "2")}
            if endpoints != want:
                raise ValueError(f"按键触点不再独立: {net}")
    for ch in range(1, 5):
        if pins[(f"J{ch+13}", "1")] != f"AIN{ch}" or pins[(f"J{ch+13}", "2")] != GND:
            raise ValueError(f"电压接口针序错误: AIN{ch}")
    for net in ("I2C_SDA", "I2C_SCL"):
        pullups = [p for p in PARTS if p["ref"].startswith("R")
                   and {pin["net"] for pin in p["pins"]} == {net, VCC}]
        if len(pullups) != 1:
            raise ValueError(f"共享总线上拉数量错误: {net}")
    headers = [p for p in PARTS if p["ref"].startswith("J") and p["pin_numbering"] == "project-header-order"]
    if len(headers) != 16 or sum(len(p["pins"]) for p in headers) != 36:
        raise ValueError("排针用量与已确认16组36针不符")
    nets = {pin["net"] for p in PARTS for pin in p["pins"] if pin["net"] is not None}
    return {"components": len(PARTS), "nets": len(nets),
            "pins": len(pins), "no_connect_pins": sum(net is None for net in pins.values()),
            "headers": len(headers), "header_pins": 36, "eda_erc_run": False,
            "native_import_verified": False}


def write_outputs(result):
    """@brief AI:输出可审阅的JSON、元件表与逐引脚网络表，明确原生导入状态。
    @param result check返回的本地静态检查结果。
    @return None；仅覆盖本工具生成的rev-a数据产物。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    model = {"schema": "ai-mcutool-connectivity/1", "revision": "A-draft",
             "date": "2026-10-23", "target_editor": "嘉立创EDA专业版V4.1.78网页版",
             "status": "connectivity-data-only", "native_project": False,
             "source_documents": ["docs/MCU开发辅助工具硬件方案.md", "docs/排针接口与丝印定义.md",
                                  "docs/整板原理图关键引脚核对.md"],
             "pages": [{"id": number, "title": title} for number, title in PAGES],
             "components": PARTS}
    encoded = json.dumps(model, ensure_ascii=False, indent=2) + "\n"
    (OUT / "design.json").write_text(encoded, encoding="utf-8")
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    page_lines = ["# 原理图分页面与位号", "", "状态：连接数据初稿，尚未创建或导入嘉立创原生工程。", "",
                  "| 图页 | 功能 | 位号 |", "| --- | --- | --- |"]
    for number, title in PAGES:
        refs = "、".join(p["ref"] for p in PARTS if p["page"] == number)
        page_lines.append(f"| {number} | {title} | {refs} |")
    page_lines += ["", "每个器件只归属一个图页；跨页同名网络必须在EDA中建立真实电气连接，不能只放说明文字。",
                   "OPA4391可用多单元符号显示，但始终只计一颗U14，电源单元的11脚接VNEG。",
                   "", "位号为本次统一初稿。导入真实库后按引脚号和语义核对，禁止按图形位置或名称相似度自动猜测连接。", ""]
    (OUT / "原理图分页面与位号.md").write_text("\n".join(page_lines), encoding="utf-8")
    bom = ["# 原理图元件清单", "", f"本清单为{len(PARTS)}个器件实例的连接准备数据，不是采购定版。没有嘉立创库UUID、供应商编码、已验证封装或价格。",
           "具体实例数量以末尾统计和design.json为准；全部器件的EDA库绑定仍为unbound。", "",
           "| 位号 | 页 | 名称/标称值 | 已核料号 | 封装方向 | 备注 |",
           "| --- | --- | --- | --- | --- | --- |"]
    for p in PARTS:
        bom.append(f"| {p['ref']} | {p['page']} | {p['value']} | {p['mpn'] or '待选'} | {p['package']} | {p['note']} |")
    bom += ["", f"合计：{len(PARTS)}个器件实例。电源入口两个连接器是逻辑端子模型；真实连接器的重复电源脚、外壳脚及按键并接脚须在选库后展开。", ""]
    (OUT / "原理图元件清单.md").write_text("\n".join(bom), encoding="utf-8")
    net_lines = ["# 逐引脚网络连接表", "", "本表是逻辑连接依据，不是已通过EDA检查的网表。",
                 "空连接以NC标明；J1/J2、LED和SW暂用逻辑端子，RSH1使用厂商I1/E1/I2/E2名称，不假造数字封装号。", "",
                 "| 位号 | 页 | 引脚/端子 | 信号 | 网络 |", "| --- | --- | --- | --- | --- |"]
    for p in PARTS:
        for pin in p["pins"]:
            net_lines.append(f"| {p['ref']} | {p['page']} | {pin['number']} | {pin['name']} | {pin['net'] or 'NC（明确不接）'} |")
    (OUT / "逐引脚网络连接表.md").write_text("\n".join(net_lines) + "\n", encoding="utf-8")
    by_net = defaultdict(list)
    for p in PARTS:
        for pin in p["pins"]:
            if pin["net"] is not None:
                by_net[pin["net"]].append({"ref": p["ref"], "pin": pin["number"], "page": p["page"]})
    (OUT / "nets.json").write_text(json.dumps(by_net, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = ["# 连接数据检查结果", "", f"源数据SHA-256：`{digest}`", "",
              f"8个页面，{result['components']}个器件，{result['pins']}个端子条目，{result['nets']}个网络，{result['no_connect_pins']}个明确不接引脚。", "",
              "已通过：位号/引脚编号唯一性、图页归属、41个模组焊盘、PSRAM脚保留、GPIO21不接ADC_READY、两类MOS底盘、LDO/隔离器关键接线、Kelvin端子分离、运放负轨、CRES独立、五路触点独立、四组AIN/GND针序、共享I²C单组上拉、16组36针用量。", "",
              "未执行：原生工程生成、器件库绑定、实际封装与焊盘映射、EDA导入回读、电气规则检查、页面渲染及样机验证。", "",
              "检查对象是本地连接数据，不是完整电路模拟。器件内部路径、保护行为、上电毛刺、互锁时序、温升和测量精度仍按方案验证。", ""]
    (OUT / "连接数据检查结果.md").write_text("\n".join(report), encoding="utf-8")


def main():
    """@brief AI:生成数据并检查，检查失败直接抛错，不产出伪造的EDA工程。
    @return None；成功时打印器件、网络等统计。
    """
    build()
    result = check()
    write_outputs(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
