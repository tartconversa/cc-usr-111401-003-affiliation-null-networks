# 机会校正网络分析方法论

`app.opportunity` 回答的问题是：跨村、跨类型协作与团队经纪位置，是否超出
团队活动机会（参与次数、活动规模）所能解释的水平。大团队天然参加更多活动、
大活动天然连出更多关系，因此原始计数不能直接当作"桥梁"证据。

## 参照模型

对每个时间层独立建立二部参照：

- 状态：该层团队—活动参与关系的全部可行二部图；
- 固定量：每个团队的参与次数、每个活动的规模（即二部图两侧度序列）；
- 约束：forbidden 三元组声明的结构性禁配不得出现；frozen 三元组声明的
  已冻结参与必须保留且不可被交换移除；团队只能出现在其 layers 列出的层内；
- 分布：满足上述条件的全部状态上的均匀分布。抽样链实际覆盖从已观察状态
  经合法交换可达的连通部分；当精确枚举可行时，报告显式比较可达集与全空间，
  碎片化（`space_fragmented`）会被披露而非静默忽略。

团队类型与村庄归属按活动发生层取值：当前资料模型中属性由快照钉住的团队记录
给出，层资格由 layers 列表界定；`statistics.attribute_of` 是唯一取值入口，
未来引入按层变化的属性时只需替换它。

## 投影不作为独立观测

统计量（共同活动对、闭合三元组、经纪对）定义在团队投影上，但推断全部在
二部参照上进行：同一活动投影出的多条团队对共享一次抽样实现，不被当作独立
观测。报告中不存在"每条边的显著性"，只有整网统计量在参照分布下的位置。

## 内置统计量

- `cross_village_pairs` / `cross_kind_pairs`：跨村庄/跨类型共同活动团队对数
  （二值投影对，增量更新实现）；
- `cross_kind_triads` / `cross_village_triads`：投影中两两相连且属性不唯一的
  闭合三元组数，明细列出每个三元组三条边的支撑活动；
- `brokerage_village` / `brokerage_kind`：Gould–Fernandez 经纪——团队连接的
  两两未直接相连邻居对数，按属性分组分为 coordinator / consultant /
  liaison / gatekeeper_representative，明细列出每个经纪位置的两段支撑活动。

所有统计量的 `details` 在已观察网络上给出具体结构与对应活动键，
供研究者逐条核查，而非只有中心性排行榜。

## 抽样与诊断

- 棋盘交换：每次从可动边（非冻结）有序抽取两条，目标位置均非现有边且非禁配
  则接受；提议矩阵对称，平稳分布为可达类上的均匀分布，拒绝构成自环；
- 拒绝按原因计数（`rejected_degenerate` / `rejected_duplicate` /
  `rejected_forbidden` / `rejected_no_movable`）并随报告披露；
- 按接受的交换计 burn-in 与 thinning；每条链独立随机流；
- 有效样本量：初始正序列自相关估计（ESS），低于 `min_ess` 标记
  `low_effective_samples`；
- 混合诊断：链内首尾段均值 z（Geweke 式，未做谱密度校正，仅作警示）与
  多链均值一致性 z，超阈分别标记 `geweke_unstable` / `chains_disagree`；
- 经验 p 值用 (k+1)/(n+1) 校正，主方向为 high（超出参照），同时报告 p_low。

## 精确枚举与抽样校验

状态数不超过 `exact_state_cap`（且访问数不超过 `exact_visit_cap`）时，
枚举全部可行状态并逐一计算统计量，得到精确参照分布与精确 p 值；
同时从已观察状态 BFS 可达集，识别约束导致的碎片化。抽样分布与精确分布的
最大 CDF 差（KS）逐分量报告，超过 `ks_tolerance` 标记 `exact_mismatch`。
超限时显式报告 `enumeration_capped`，不以抽样冒充精确。

## 退化与失败模式（均显式报告，不产出虚假显著）

- `unique_state_proven`：精确枚举证明约束下只有一个可行状态；
- `no_exchangeable_states`：可动边不足或全部链未接受任何交换，无可交换状态；
- `zero_variance_reference`：参照样本方差为零，z 与显著性无定义；
- `insufficient_reference_samples`：样本总量低于 `min_total_samples`，
  p 值被抑制为 null——不允许用几次交换宣布显著；
- `attempt_cap_reached`：拒绝占比过高触及提议上限，样本低于配置。

退化分量不进入多重比较 family，而是以原因列入 `family.excluded`。

## 多重比较

一次运行同时筛查多团队、多结构。`family` 块披露：范围（默认 run 内全部层
全部非退化分量合并）、方法（Benjamini–Hochberg）、方向、检验数与分量清单；
每个分量报告 q_high。解读时以 q 为准，p 仅供参照。

## 复算

报告携带：`input_digest`（有效修订与全部 metadata 的哈希）、`data_version`
（沿用 metadata，程序不自造）、`analysis_version`、全部生效配置、随机种子与
派生规则 `random.Random(f"{seed}|{layer}|chain{i}")`。给定同一资料与配置，
输出逐字节确定（含跨 PYTHONHASHSEED 稳定，见测试）。

## 解释边界

结论只能表述为"在给定参照（固定参与机会、保留禁配与冻结的均匀二部参照）下，
某结构统计量异常高/低"。它不排除未观测的混杂，不支持"某团队导致了产业增长"
一类的因果归因；`scope_note` 随每份报告输出。

## 扩展指南

新增统计量：实现 `components(ctx)`、`full(ctx, proj)`、`details(ctx, proj)`，
在 `statistics.REGISTRY` 登记后即可进入配置、抽样、精确枚举与多重比较流程。
高频统计量可实现增量接口（`incremental = True`，`attach` / `on_swap` /
`current`）；抽样器 `verify_incremental=True` 会在每个采样点校验增量结果与
完整重算一致，测试中有对应保障。新增参照生成方式：实现与 `run_chain` 相同的
样本接口即可替换抽样器，诊断与报告层无需改动。
