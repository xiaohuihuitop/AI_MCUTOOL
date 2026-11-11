# PCB布局初稿说明

日期：2026-10-24。用户已授权开始PCB布局。本轮交付华秋KiCad 10可编辑的未布线布局，包含164颗器件、完整网络和原理图UUID关联。

## 当前入口与范围

- 工程：`hardware/kicad/AI_MCUTOOL.kicad_pro`。
- PCB：`hardware/kicad/AI_MCUTOOL.kicad_pcb`。
- 预览：`hardware/kicad/preview/PCB布局初稿.svg`、同名PNG。
- 检查：`hardware/kicad/verification/pcb-layout-check.json`及`pcb-drc.json`。

采用90×90mm矩形板框、四个铜层作为可调整初稿。当前仅建立铜层，尚未铺地、布线或确定制造叠层；拟采用顶层信号/器件、内层地、内层供电/低速信号、底层信号的组织方式。板厚和铜厚须在制造前确定，不从默认文件参数推导已满足承流或散热。

## 分区和接线

| 区域 | 布局安排 |
| --- | --- |
| 左上 | KEY1～KEY5依次排列，触点端朝排针，驱动端朝板内；每路单独A/B，不与地短接 |
| 上方中部 | 目标UART和工具下载口分开，TX/RX以工具为参照 |
| 右上 | ESP32-S3模组天线朝上、位于馈点靠右的板角方向；RESET、BOOT、CONFIG位于主体下方 |
| 左侧中部 | DC及Type-C水平出线，均标5V；LDO预留约25×25mm散热规划区域 |
| 下侧左部 | BAT_IN、EXT_IN、两路MOS和光伏驱动；分流器靠DUT_PWR，INA228及RC靠分流采样端 |
| 右侧中下部 | AIN1～AIN4按序独立两针，每路五颗串联2MΩ与下臂/输入滤波靠对应接口，运放和ADC靠板内 |
| 下侧右部 | 独立CHG_IN、充电MOS与DUT_CHG；正端与工具供电分开 |

布局不改变网络、GPIO、互锁或电气额定目标。所有排针保持2.54mm朝上直排针；未新增固定孔或外壳结构。主供电及充电导体宽度、回流和Kelvin采样线将在布线阶段落实。

## 天线与整机外形的待闭合项

模组原点相对板框为(76,6.75)mm，旋转0°；名义6mm天线段伸出上板边。保留标准库全部铜层的48×21mm禁布区，禁止铜、焊盘、走线、过孔及其他封装。项目专用模组封装只把原跨板边丝印轮廓移到Fab，未改变铜盘、中心接地孔或禁布规则。

裸板90×90mm，加伸出的天线及Type-C前沿后，主要名义平面包络约90.49×96mm；这不是包含公差和外壳的整机验收结果。乐鑫建议外壳各方向给天线至少15mm净空，90mm板长、6mm伸出和该外壳净空无法直接同时塞进100mm整机上限。**外壳尺寸尚未闭合，当前90mm板框只能作为布局初稿，不能据此制作最终外壳。** 布线定版前需通过减小板长、调整结构等方式解决，不以取消天线规则区来掩盖冲突。详见[天线核定](ESP32模组天线布局核定.md)。

## 初稿工艺约束及检查

规则明确采用最小铜间距0.15mm、最小通孔0.20mm、孔到铜0.20mm；普通信号线默认宽0.20mm，普通过孔默认0.6/0.3mm。前述较细工艺来自已选VSSOP封装、模组标准接地孔、Type-C定位孔邻接铜垫的实际需求，不是通过删除违规或排除DRC获得结果。投板前须按华秋实际层叠、铜厚和加工档位确认能力及价格。

原理图连接回归零差异、ERC零违规。PCB CLI运行包含`--schematic-parity --severity-all`，布局违规0、原理图一致性问题0。未连接项336，PCB没有走线或过孔，尚未铺铜，**不属于DRC全通过的可投板文件**。

LDO的OUT散热铜必须属于3.3V，不能接地；当前只有面积规划，未完成1.55W热验证。外部排针配套线材承流、接触压降、测量噪声和Wi-Fi工作下精度仍需样机验证。

## 维护

`hardware/tools/build_pcb_layout.py`使用显式摆放表，不给缺失器件自动找空位。默认拒绝覆盖现有PCB；只有加`--replace-draft`且文件哈希仍等于上次自动生成结果才允许重建，GUI修改后会拒绝覆盖。修改初稿可直接在华秋PCB编辑器中进行，后续不应覆盖手工摆放或布线。

验证命令：

```powershell
& 'D:\Application\kicad\install\bin\kicad-cli.exe' pcb drc --schematic-parity --format json --severity-all -o hardware/kicad/verification/pcb-drc.json hardware/kicad/AI_MCUTOOL.kicad_pcb
& 'D:\Application\kicad\install\bin\python.exe' hardware/tools/verify_pcb_layout.py
```
