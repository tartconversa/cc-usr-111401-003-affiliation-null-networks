# 青年跨村合作网络的机会校正与经纪结构检验

本项目提供时态二部活动及合法机会域相关资料的现有业务摘要，以及机会校正的网络分析：
在固定各时间层团队参与次数与活动规模、保留禁配与冻结参与的均匀二部参照下，
检验跨村/跨类型协作、跨类型闭合与团队经纪位置是否超出活动机会所能解释的水平。

app/catalog.py 按集合和记录键解析修订，拒绝同修订冲突；app/baseline.py 承载当前业务计算；
app/service.py 输出摘要及输入摘要哈希；app/opportunity/ 承载机会校正网络分析
（交换链抽样、精确枚举校验、多重比较校正与诊断报告）。
数据字段及现有接口见 [资料契约](docs/data-contract.md)，分析方法论见
[机会校正方法论](docs/opportunity.md)。fixtures/ 是合成小数据，不对应真实村庄或个人。
运行环境为 Python 3.14，现有模块仅使用标准库。

读取并计算当前摘要：

    python -m app.service fixtures/sample.json

运行机会校正网络分析（第二参数为可选配置JSON）：

    python -m app.opportunity fixtures/opportunity.json

运行当前模块检查：

    python -m unittest discover -s tests -v

检查源码编译：

    python -m compileall -q app tests
