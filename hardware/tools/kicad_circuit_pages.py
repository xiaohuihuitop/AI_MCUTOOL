"""@brief AI:八个功能页的人工布局与明确走线；坐标单位统一为1.27mm。"""


def draw_power(Page):
    """@brief AI:绘制双五伏入口、理想二极管汇合及LDO。
    @param Page 原理图页类。
    @return 已布置且完成局部连接的电源页。
    """
    p=Page("01","01 工具电源","工具自身：DC / Type-C 二选一输入5V；外部电池和充电器正端不接入本页。")
    p.place("J1",25,45,value="DC 5V / 中心正")
    p.place("J2",25,105,value="USB-C / 仅5V")
    for u,r,c,y in [("U1","R1","C1",45),("U2","R2","C2",105)]:
        p.place(u,90,y,value="LM66100DCKR")
        p.place(r,48,y+13);p.place(c,60,y+13)
        vin=p.point(u+".1");vout=p.point(u+".6");ce=p.point(u+".3")
        if u=="U1":p.connect("J1.1",(60,43),(60,vin[1]),u+".1")
        else:p.connect("J2.A4B9",(60,95),(60,vin[1]),u+".1")
        rail=43 if u=="U1" else 95
        p.connect(r+".1",(48,rail));p.connect(c+".1",(60,vin[1]))
        p.connect(u+".3",(78,ce[1]),(78,y+20),(116,y+20),(116,vout[1]),u+".6")
        p.connect(u+".6",(140,vout[1]))
    p.connect((140,41),(140,101),net="LDO_VIN")
    p.place("R3",43,137);p.place("R4",55,137)
    p.link("J2.A5","R3.1");p.link("J2.B5","R4.1")
    p.place("U3",180,70,value="LDL1117S33R")
    p.connect("U3.3",(140,68))
    p.place("C3",160,86);p.connect("C3.1",(160,68))
    p.place("C4",220,86);p.connect("U3.2",(220,68),"C4.1")
    p.power((220,68),"TOOL_3V3",0)
    p.flag_at("J1.1");p.flag_at("J1.2");p.flag_at("J2.A4B9");p.flag_at("U3.3")
    p.text("输入隔离",75,30,1.4,True);p.text("3.3V稳压",165,45,1.4,True)
    p.text("CE接各自输出，构成理想二极管功能；ST及NC按已核方案接地。",75,155)
    p.text("LDO散热、输入掉电反流及实际输出电容稳定性需样机验证。\nType-C不做PD协商；CC1 / CC2各5.1kΩ下拉。",165,130)
    return p


def draw_controller(Page):
    """@brief AI:绘制主控、复位/启动、下载口、I2C上拉和指示电路。
    @param Page 原理图页类。
    @return 主控页。
    """
    p=Page("02","02 主控与总线","ESP32-S3-WROOM-1-N16R8模组；GPIO35/36/37被PSRAM占用，禁止用于业务接口。")
    p.place("U4",150,88,value="ESP32-S3-WROOM-1-N16R8",fields=((140,57),(176,57)))
    p.place("R5",95,50);p.place("C7",95,84);p.place("SW1",65,84,value="RESET")
    p.connect("R5.2",(95,70),"U4.3");p.connect("C7.1",(95,70));p.connect("SW1.1",(55,84),(55,70),(95,70),net="ESP_EN")
    p.connect((95,60),(100,60),net="ESP_EN");p.port("ESP_EN",(100,60),False)
    p.place("R6",105,125);p.place("SW2",115,142,value="BOOT")
    p.connect("R6.2",(128,128),(128,74),"U4.27");p.connect("SW2.1",(105,142),"R6.2")
    p.tag("R6.2",length=3,direction=(-1,0))
    p.place("R8",85,99);p.connect("R8.1",(85,80),"U4.15")
    p.place("R7",190,125);p.connect("U4.16",(190,102),"R7.1")
    p.place("J3",35,155,value="下载 / 调试 UART0")
    for key in ["J3.1","J3.2","J3.4","J3.5","U4.36","U4.37"]:p.tag(key)
    p.place("R81",205,55);p.place("R82",225,55)
    p.tag("R81.2",True,direction=(1,0));p.tag("R82.2",True,direction=(1,0))
    p.place("C5",190,40);p.place("C6",210,40);p.connect("C5.1","C6.1");p.power("C5.1")
    p.place("R9",228,89);p.place("SW3",240,107,value="CONFIG")
    p.connect("U4.10",(215,74),(215,107),(228,107),"R9.2");p.connect("R9.2",(228,107),"SW3.1")
    p.place("R10",275,145);p.place("LED1",275,158,90,value="PWR / 红")
    p.connect("R10.2","LED1.2")
    p.place("R11",275,91);p.place("LED2",275,104,90,value="STATUS / 绿")
    p.connect("R11.2","LED2.2");p.tag("R11.1",direction=(-1,0));p.tag("U4.9")
    p.text("复位 / 启动",65,36,1.4,True);p.text("共享I2C：仅一组上拉",195,31,1.4,True)
    p.text("DOWNLOAD针序：TX0、RX0、GND、BOOT、EN。\n下载口不参与工具供电；3.3V UART电平。",22,186)
    p.text("各电源通路与按键驱动的默认关闭由外部偏置保证。\n连接器方向、天线净空、LDO热源距离在PCB阶段复核。",180,193)
    return p


def draw_keys(Page):
    """@brief AI:以五个完整重复电路绘制隔离按键模拟。
    @param Page 原理图页类。
    @return 按键页。
    """
    p=Page("03","03 五路按键模拟","触点独立、无极性；被测按键≤6V、≤20mA。触点不接工具公共地。")
    for i in range(5):
        x=0 if i%2==0 else 155;y=40+(i//2)*58
        u,q,j=f"U{i+5}",f"Q{i+1}",f"J{i+4}"
        rled,rbase,rdown=[f"R{12+3*i+k}" for k in range(3)]
        p.text(f"KEY{i+1}",x+17,y-8,1.4,True)
        p.place(u,x+84,y+16,value="TLP176AM")
        p.place(q,x+50,y+22,value="MMBT3904")
        p.place(rled,x+65,y+3);p.place(rbase,x+30,y+22,90);p.place(rdown,x+40,y+36)
        p.place(j,x+112,y+16,value=f"KEY{i+1}")
        p.connect(rled+".2",(x+65,y+13),u+".1")
        p.connect(rbase+".2",q+".1");p.connect(rdown+".1",(x+40,y+22))
        p.connect(q+".3",(x+52,y+19),u+".3")
        p.connect(u+".4",(x+104,y+13),(x+104,y+16),j+".1")
        p.connect(u+".6",(x+100,y+19),(x+100,y+18),j+".2")
    p.text("240Ω为PhotoMOS LED限流；680Ω为基极电阻；10kΩ保证控制悬空时关闭。",165,200)
    return p


def draw_sources(Page):
    """@brief AI:绘制真实电池与外部模拟电源的两套背靠背MOS开关。
    @param Page 原理图页类。
    @return 主供电选择页。
    """
    p=Page("04","04 主供电选择","BAT_IN与EXT_IN互斥，切换先断后通，允许被测设备断电。不得同时开启两路。")
    for x,u,q,qa,qb,j,rs,label in [(0,"U10","Q6","Q8","Q9","J9",27,"真实电池"),(155,"U11","Q7","Q10","Q11","J10",30,"外部模拟电源")]:
        p.text(label,x+24,32,1.5,True)
        p.place(j,x+25,45,value="BAT_IN" if x==0 else "EXT_IN")
        p.place(qa,x+107,55,value="CSD17577Q3A")
        p.place(qb,x+107,75,mirror="x",value="CSD17577Q3A")
        p.place(u,x+75,65,value="VOM1271T")
        p.place(q,x+40,72,value="MMBT3904")
        rled,rbase,rdown=[f"R{rs+i}" for i in range(3)]
        p.place(rled,x+54,57,value="100 / 1206");p.place(rbase,x+24,72,90);p.place(rdown,x+32,88)
        p.tag(rbase+".1",True,length=1)
        p.connect(j+".1",(x+109,45),qa+".5")
        p.connect(qa+".1",qb+".1")
        p.connect(qa+".4",(x+97,55),(x+97,75),qb+".4")
        p.connect(u+".4",(x+92,62),(x+92,55),(x+97,55))
        p.connect(u+".3",(x+88,68),(x+88,65),(x+109,65))
        p.connect(rled+".2",(x+54,62),u+".1")
        p.connect(u+".2",q+".3")
        p.connect(rbase+".2",q+".1");p.connect(rdown+".1",(x+32,72))
        p.connect(qb+".5",(x+130,79),(x+130,115))
    p.connect((130,115),(285,115),net="VSEL_P");p.port("VSEL_P",(285,115))
    p.text("背靠背共源结构：两只N-MOS的S相连；9脚散热焊盘属于D。\n光伏驱动的PV-参考共源点，PV+驱动两只MOS的G。\nMOS选型、栅极建立/释放时间及双向关断仍需样机验收。",30,153)
    p.text("共地边界：电池、模拟电源、工具与DUT共地；高侧开关只切正端。\n输出汇合后，串联四端分流器进入DUT_PWR。",180,174)
    return p


def draw_charger(Page):
    """@brief AI:绘制独立5V充电器的背靠背P-MOS插拔模拟。
    @param Page 原理图页类。
    @return 充电页。
    """
    p=Page("05","05 独立充电输入","独立外接5V充电器；验证充电时选择真实电池。充电输入与工具自身5V正端分开。")
    p.place("J12",45,50,value="CHG_IN / 5V")
    p.place("Q12",140,60,value="CSD25402Q3A");p.place("Q13",140,80,mirror="x",value="CSD25402Q3A")
    p.place("J13",240,84,value="DUT_CHG")
    p.connect("J12.1",(142,50),"Q12.1");p.connect("Q12.5","Q13.5")
    p.connect("Q13.1",(220,84),"J13.1")
    p.connect("Q12.4",(128,60),(128,80),"Q13.4")
    p.place("R33",135,70,90);p.connect("R33.1",(128,70));p.connect("R33.2",(142,70))
    p.place("R34",105,80,270);p.connect("R34.1",(128,80))
    p.place("Q14",80,84,value="MMBT3904");p.connect("R34.2","Q14.3")
    p.place("R35",55,84,90);p.place("R36",68,100)
    p.connect("R35.2","Q14.1");p.connect("R36.1",(68,84))
    p.text("共源P-MOS：5～9脚为S；1～3脚为D；4脚为G。\nR33把G拉回共源点，控制悬空时关闭。\n不增加主动放电；关闭后DUT端电压的下降由实际负载决定。",80,135)
    return p


def draw_current(Page):
    """@brief AI:绘制四端分流、差分滤波、总线及DUT电源接口。
    @param Page 原理图页类。
    @return 电流测量页。
    """
    p=Page("06","06 电池端电流与电压","双向电流测量；I1/I2为载流端，E1/E2为Kelvin采样端，PCB上不得提前短接。")
    p.place("RSH1",110,65,value="20mΩ / 0.1% / 4端")
    p.tag("RSH1.4",True,length=18)
    p.place("J11",260,62,value="DUT_PWR")
    p.connect("RSH1.1","J11.1")
    p.place("U12",185,105,value="INA228AIDGSR",fields=((176,88),(197,88)))
    p.place("R37",128,105,90);p.place("R38",128,120,90);p.place("C8",155,114)
    p.connect("RSH1.3",(102,105),"R37.1")
    p.connect("RSH1.2",(118,120),"R38.1")
    p.connect("R37.2",(154,105),(154,107),"U12.10")
    p.connect("R38.2",(162,120),(162,109),"U12.9")
    p.connect("C8.1",(155,107));p.connect("C8.2",(155,120))
    p.connect("U12.8",(169,99),(169,62))
    p.connect("U12.1",(203,99),(203,101),"U12.2")
    p.connect((203,100),(207,100),net="COMMON_GND");p.helper("COMMON_GND",207,100,90)
    p.place("R39",220,96);p.connect("R39.2",(220,111),"U12.3")
    p.connect((220,111),(235,111),net="CURRENT_ALERT");p.port("CURRENT_ALERT",(235,111))
    p.place("C9",280,100)
    p.flag_at("J11.1")
    p.text("I2C地址：A1=A0=GND。\n10Ω + 100nF为差分输入滤波；采样线成对靠近，远离大电流回路。\n输出为电池端总电流与DUT_PWR接口电压，合格判定由被测项目定义。",35,158)
    return p


def draw_voltage(Page):
    """@brief AI:绘制四条真实分压/缓冲链，以及ADC和负轨电荷泵。
    @param Page 原理图页类。
    @return 四路电压测量页。
    """
    p=Page("07","07 四路高阻电压检测","四路0～15V输入、各自AIN/GND；每路5×2MΩ串联 + 1MΩ下拉。负压输入不支持。")
    op_pins=[(1,2,3),(7,6,5),(8,9,10),(14,13,12)]
    for i,y in enumerate([45,88,131,174]):
        first=40+i*9;j=f"J{14+i}"
        p.place(j,18,y,value=f"AIN{i+1}")
        for k in range(5):p.place(f"R{first+k}",35+k*14,y,90)
        p.connect(j+".1",f"R{first}.1")
        for k in range(4):p.connect(f"R{first+k}.2",f"R{first+k+1}.1")
        rd,rf,rb,rs=[f"R{first+k}" for k in [5,6,7,8]]
        cf,ca=f"C{10+2*i}",f"C{11+2*i}"
        p.place(rd,105,y+13);p.place(cf,119,y+13)
        p.place("U14",140,y,unit=i+1,value="OPA4391",fields=((142,y-7),(142,y-4.5)))
        out,neg,pos=op_pins[i]
        p.connect(f"R{first+4}.2",(130,y),(130,y-2),f"U14.{pos}")
        p.connect(rd+".1",(105,y));p.connect(cf+".1",(119,y))
        p.place(rf,157,y+10,value="499 / 0.1%");p.place(rb,157,y+24,value="100k / 0.1%")
        p.place(rs,180,y,90);p.connect(f"U14.{out}",rs+".1")
        p.connect(rf+".1",(157,y));p.connect(rf+".2",rb+".1")
        p.connect(f"U14.{neg}",(127,y+2),(127,y+17),(157,y+17))
        p.place(ca,195,y+10);p.connect(rs+".2",(206,y));p.connect(ca+".1",(195,y))
        p.port(f"ADC_CH{i+1}",(206,y),False)
    p.place("U13",270,70,value="ADS1115IDGSR",fields=((258,53),(283,53)))
    for pin in [4,5,6,7]:p.tag("U13."+str(pin),length=8)
    p.connect("U13.1",(285,74),(285,90));p.power((285,90),"COMMON_GND",0)
    p.place("C18",295,55);p.place("C25",310,55);p.connect("C18.1","C25.1");p.power("C18.1")
    p.place("U14",255,128,unit=5,value="OPA4391",fields=((286,125),(286,128)))
    p.place("C19",270,128)
    p.connect("U14.4",(270,122),"C19.1");p.connect("U14.11",(270,134),"C19.2")
    p.power("U14.4");p.power("U14.11")
    p.place("U15",265,157,value="LM7705",fields=((281,146),(299,146)))
    p.place("C21",241,158)
    p.connect("U15.1",(249,157),(249,155),"C21.1")
    p.connect("U15.8",(252,159),(252,161),"C21.2")
    p.place("C22",285,171);p.place("C23",310,171);p.place("C24",299,171);p.place("C20",235,175)
    p.connect("U15.7",(285,157),"C22.1")
    p.connect("U15.6",(318,153),(318,159));p.power((318,159),"VNEG",0)
    p.connect("C23.1",(310,153));p.connect("C24.1",(299,153))
    p.text("ADC_CH1～4：同页缓冲输出到ADC的测量接口。\n分压精度、近零偏置、PCB清洁与漏电共同决定误差。",230,108,0.95)
    p.text("高阻节点不可随意增加泄漏较大的保护元件；\n负轨及前端近零误差须标定与样机验证。",230,195,0.95)
    return p


def draw_uart(Page):
    """@brief AI:绘制有独立发送高阻控制的3.3V UART接口。
    @param Page 原理图页类。
    @return UART页。
    """
    p=Page("08","08 目标UART接口","仅3.3V电平；TOOL_TX接DUT_RX，TOOL_RX接DUT_TX。接收路径持续有效，发送可独立置高阻。")
    p.place("U16",115,70,value="SN74AUP1G125",fields=((110,48),(132,48)))
    p.place("R77",85,54);p.connect("R77.2",(85,70),"U16.2")
    p.connect((65,70),(85,70),net="DUT_UART_TX");p.port("DUT_UART_TX",(65,70),direction=-1)
    p.place("R76",115,36);p.connect("R76.2","U16.1")
    p.connect((115,50),(145,50),net="UART_TX_NOE");p.port("UART_TX_NOE",(145,50))
    p.place("R79",160,70,90);p.connect("U16.4","R79.1")
    p.place("J18",255,100,value="DUT_UART")
    p.connect("R79.2",(205,70),(205,100),"J18.1")
    p.place("U17",115,130,mirror="y",value="74LVC1G17",fields=((103,115),(83,118)))
    p.place("R80",190,130,270);p.connect("J18.2",(225,102),(225,130),"R80.1")
    p.connect("R80.2","U17.2")
    p.place("R78",160,148);p.connect("R78.1",(160,130))
    p.place("C26",155,92);p.place("C27",135,160)
    p.connect("J18.3",(251,114));p.power((251,114),"COMMON_GND",0)
    p.text("TX使能低有效；10kΩ上拉保证复位时高阻。\nRX使用施密特缓冲；470kΩ使悬空输入有确定电平。\n两侧100Ω用于隔离、限制瞬态电流，不代表5V容限。",175,175)
    return p


def draw_pages(Page):
    """@brief AI:按确定的功能顺序生成八页电路。
    @param Page 页对象类。
    @return 页对象列表。
    """
    return [fn(Page) for fn in [draw_power,draw_controller,draw_keys,draw_sources,draw_charger,draw_current,draw_voltage,draw_uart]]
