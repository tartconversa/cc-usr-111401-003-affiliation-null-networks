# 资料与现有计算约定

## 修订快照

schema_version为整数1，metadata为业务方案字典，collections为业务集合字典。每条记录有非空字符串id和正整数revision。
同集合相同id取最高revision；同id同revision内容不同即冲突，即便存在更高修订也拒绝。deleted=true为撤回，之后更高修订可恢复。
撤回记录不要求携带业务字段。输入顺序与相同记录重试不改变语义；非有限数字拒绝。
Snapshot.rows返回独立副本；input_digest绑定有效修订和全部metadata。输出data_version沿用metadata，不由程序自造资料版本。
既有摘要入口为app.service.inspect(payload)，输出schema_version、input_digest、data_version和summary。

## 业务资料

events 含 layer 和 members，成员为团队键集合；同一团队在同一活动只计一次。teams 含 kind、village 和有效层列表。forbidden 是禁止的[layer,event,team]，frozen 是冻结的同结构三元组。baseline.analyze 返回按时间层、团队对汇总的共同活动数；不把此数解释为独立样本量。

各集合必要字段：{"events": ["layer", "members"], "teams": ["kind", "village", "layers"]}。

## 禁配与冻结三元组

metadata.forbidden 与 metadata.frozen 为[层,活动,团队]三元组数组，缺省为空。
机会校正分析中：forbidden 声明结构性禁配，参照状态不得出现；frozen 声明已冻结参与，
参照状态必须保留且交换不可移除。校验规则：三元组指向的活动、团队必须存在且层一致；
禁配与已观察参与冲突、冻结未在资料中出现、冻结与禁配相交均为输入错误；
禁配指向本无该层参与资格的团队按空转处理并在报告中披露。

## 当前能力

app.baseline.analyze(snapshot)产生已有摘要，app.service.inspect负责绑定输入身份；
app.opportunity.inspect(payload, config=None)为机会校正网络分析入口，
输出固定参与机会的二部参照下各统计量的观察值、参照分布、经验与精确p值、
BH校正q值、具体结构明细（含对应活动）、拒绝原因台账与混合诊断；
方法论与配置项见 docs/opportunity.md。已有接口及上述数据语义保持兼容。
