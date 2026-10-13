# POS：5 个经复核的电力系统优化算例

本库从 OptiAgent / PowerSystemOptiSage（POS）的已有 50 个测试算例中筛选出 5 个，提供**问题描述、Excel 输入、参数、建模产物、原始求解代码、历史执行结果，以及新增独立复核结果**。

这是一组经过挑选的正确案例展示，不是随机样本，不代表整个测试集的正确率。原始求解代码未作修复或改写；未重新调用 LLM。

## 入选结果

| 算例 | 模型要求 | POS 复算目标值 | 与独立参考模型绝对差 |
|---|---|---:|---:|
| `ed_quadratic_case24` | 24 时段二次 ED、30% 爬坡、DC 网络、5% 备用 | 305150.722089291 | 2.75e-8 |
| `ed_quadratic_case30` | 24 时段二次 ED、30% 爬坡、DC 网络 | 326093.764504311 | 4.82e-7 |
| `ed_quadratic_case57` | 24 时段二次 ED、30% 爬坡、DC 网络 | 607777.584361661 | 5.67e-6 |
| `opf_load_shedding_case30` | 24 时段线性 OPF、35% 爬坡、削负荷惩罚 10000 | 336300.904821310 | 1.16e-10 |
| `opf_load_shedding_case57` | 24 时段线性 OPF、35% 爬坡、削负荷惩罚 10000 | 657272.649692301 | 1.98e-9 |

五例均返回 Gurobi `OPTIMAL (2)`。独立参考模型逐行检查 POS 解，最大约束残差低于 `1e-8`，变量边界违背为零；两例 OPF 的最优削负荷均为零。完整精度见 `verification/summary.json`。

## 为什么选择这 5 个

1. 已有单审查者评价中，这 5 个属于最高的 **10/10** 档次。
2. 再逐项对照 `desc.txt` 与 `solve_model.py`，检查变量、成本形式、机组出力上下界、相邻时段爬坡、节点平衡、双向线路容量、参考母线，以及各例要求的备用或削负荷。
3. 在发布副本运行未经改动的求解代码，再用只读取描述和 Excel 的独立确定性模型复算；不是拿同一份 `data.json` 自证正确。
4. 检查 Excel 到 JSON 的参数映射，重新计算目标函数，并将 POS 的所有决策变量映射到参考模型，核验每一条约束和变量边界。
5. 加入负对照：故意将第一台机组首时段出力增加 1 MW，确认约束核验能检出错误。

另外 4 个历史同为 10/10 的案例，历史目标值与标准值有差异，未优先入选；差异可能与 MIP 停止容差或建模口径有关，不直接等同于建模错误。详细选择证据见 `selection.json` 和 `REVIEW.md`。

## 文件结构

```text
cases/<case>/
  desc.txt + <case>.xlsx       原始问题描述和表格输入
  data.json + params.json      提取后的参数
  parameter_artifact.json      参数提取证据
  modeling_context.json        建模上下文
  model_artifact.json          公式、代码片段和组装产物
  solve_model.py               未修改的 POS 求解代码
  execution_report.json        历史执行输出
  stantard_value.json          原有确定性标准值（保留原文件拼写）
  *_log.json / batch_*.txt     历史建模和执行日志
baseline/summary.json          原始 CLI 复跑命令、完整输出、退出码
verification/<case>/
  solution.json               新增完整决策变量解与目标值
  model.lp                    新增 POS 模型导出
  verification.json           新增逐例独立复核结果
reference/solve_cases.py       项目已有确定性参考模型，未修改
verify_cases.py               本次新增复现与校验入口
source_manifest.json          来源文件与发布副本的 SHA-256
SHA256SUMS.json                发布包文件完整性校验表
```

`reference/README.md` 保留原参考程序说明；其中针对原项目的路径和全量运行命令不是本库入口，请使用下面的命令。

## 复现

验证环境：Python 3.13、Gurobi 12.0.3。需要自行配置有效 Gurobi 许可证；本库不包含许可证、API 密钥或 LLM 运行依赖。求解参数沿用原 POS 代码的默认设置与 `MIPGap=0.005`；入选五例均为连续凸 QP/LP，不受 MIP 停止间隙影响。参考模型使用更严格的数值容差。

```bash
python -m pip install -r requirements.txt
# 运行原始 CLI，记录 STATUS 2 与退出码
python verify_cases.py --baseline --output rerun-baseline
# 独立复算并核验，写入新的目录以保留发布时证据
python verify_cases.py --output rerun-verification
```

通过时最后一行是 `PASS: 5/5 cases`，退出码为 `0`。判定阈值：目标值绝对误差不超过 `1e-3` cost，约束/边界残差不超过 `1e-5`；本次实测远低于这两个阈值。这里的“正确”指给定输入和建模口径下，在明确数值容差内通过验证，不是符号精确证明。

## 建模边界与来源

- 这些具体输入中所有机组、线路均在线，母线编号连续，变压器 TAP 为 0（等效 1），SHIFT 为 0，RATE_A 为正。部分生成代码并非适用于任意改造后的网络；本库不宣称其已覆盖非单位变比、相移或任意停运拓扑。
- 第一段负荷对应第一个实际运行时段，未凭空施加首时段零出力或初始爬坡条件；ED/OPF 均无 UC 启停变量。
- 原生成过程的模型/provider 未在保留的逐案例元数据中明确记录，本库不根据当前项目配置倒推历史配置。历史执行状态、原始提示词与返回结果保留在案例产物中。
- 源目录是原项目 `problems/`，参考程序来自 `standard_calculation/`。本次仅创建发布副本，未修改原项目的源码、数据集、标准值或历史结果，也未改变原基准比较协议。
- 发布副本仅对历史日志/JSON 中的本机项目根路径、Gurobi 许可证编号作处理，并规范化 JSON 排版；数值和建模内容未改动。输入描述、Excel、求解代码的来源哈希与发布哈希可核对。

整理与复核日期：2026-10-13（Asia/Shanghai）。

## 下载

可直接下载仓库根目录的 `pos-five-cases.zip`。压缩包包含上列输入、输出、代码与证据；`pos-five-cases.zip.sha256` 记录归档校验值。`SHA256SUMS.json` 校验压缩包内的文件（不包含校验表自身及外层 ZIP）。
