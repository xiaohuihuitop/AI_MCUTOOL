Type: task
Status: resolved

# 调整统计位置与列距

按../spec.md完成样式、布局、构建及本机查看。

## Answer

仅调整Trend.vue样式：游标组280px靠左，统计组220px靠右；首列分别124px/56px，数值左对齐。时长在左、净电量在右，窄屏上下排列。

生产构建和既有电池图表测试通过，真实本机窗口核对统计组右边距接近0，内部列距124px/56px，窄屏无溢出。新网页资产已部署到本机安装目录；当前窗口即时应用同一构建样式，保留既有历史和A/B游标，没有刷新页面。旧网页资产备份于docs/temp/analysis-layout-backup；截图与检查结果在docs/temp/analysis-layout。
