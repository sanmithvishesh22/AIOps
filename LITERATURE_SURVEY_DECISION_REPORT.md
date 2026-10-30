# AIOps capstone: literature landscape and research-positioning decision report

**Prepared:** 17 September 2026  
**Scope:** A skeptical, evidence-led survey of the proposed AIOps platform: multimodal observability, anomaly detection, root-cause localization (RCL), failure prediction, capacity forecasting/autoscaling, remediation, and explainability.  
**Search status:** **Mostly saturated for the capstone decision; not exhaustive in the database-systematic-review sense.** The supplied corpus was read as evidence, terminology variants and adjacent areas were searched, and the two proposed gaps were actively challenged. Full forward/backward citation-network screening in Scopus/Web of Science/IEEE Xplore, and a PRISMA-style duplicate-screening protocol, remain necessary before making a publishable claim of exhaustive coverage.

## Executive decision

The proposed seven-module platform is a credible **engineering capstone**, but is not a novel system concept. Detection, localization, prediction, forecasting/autoscaling, remediation and explanations have each been studied, and systems already combine substantial subsets. The project must not claim that it is the first AIOps platform, the first to predict failures in autoscaling microservices, or the first to show that proactive autoscaling can improve SLA/SLO outcomes.

The strongest defensible contribution is instead a controlled, reproducible experiment:

> **We evaluate when forecast-assisted Kubernetes autoscaling improves service-level-objective outcomes over a tuned reactive autoscaler in a Sock Shop fault-and-load testbed, and identify the workload/fault conditions in which it fails or incurs unacceptable resource and churn costs.**

That is an empirical contribution only if it uses predeclared SLOs, repeated paired trials, time-respecting training/validation, comparable policies, and reports negative as well as positive cases. The dashboard, API, database and normal model integration remain useful deliverables, but are engineering rather than scientific novelty.

## 1. Project facts versus literature findings

### Supplied project facts

The project is *AIOps: AI-Driven Anomaly Detection & Predictive Maintenance for IT Infrastructure*. It proposes OpenTelemetry ingestion of logs, metrics and traces from Sock Shop; Isolation Forest plus an LSTM autoencoder; graph-based RCL; failure likelihood and severity; Prophet and/or LSTM capacity forecasting; human-approved remediation; SHAP/LIME; TimescaleDB, Express and React. Evaluation is proposed on Sock Shop with Chaos Mesh, against threshold monitoring, using MTTD, false positives, RCL accuracy and remediation success.

The project information does **not** yet define a failure, a prediction horizon, an SLO, severity labels, workload generator, scaling policy, or the relation between the broad seven-module prototype and the narrower autoscaling research claims. These are unresolved design requirements, not literature facts.

### Literature-derived position

AIOps is not one algorithm but a lifecycle spanning failure-data processing, failure perception/diagnosis and remediation. The recent ACM survey by Zhang et al. reviewed 183 LLM4AIOps articles from 2020–2024 and identifies data sources, tasks, methods and evaluation as separate dimensions; it also emphasizes real-time cost, generalization under system evolution and integration with toolchains as unresolved deployment challenges ([Zhang et al., 2025](https://doi.org/10.1145/3746635)). The project belongs in cloud-native reliability engineering/AIOps, not traditional physical predictive maintenance.

## 2. Terminology map used to challenge false gaps

| Project term | Also searched as | Boundary that matters |
|---|---|---|
| Anomaly detection | outlier detection, KPI anomaly detection, dynamic baselining, failure perception | An anomaly is not automatically a failure or SLO breach. |
| Root cause analysis | root cause localization, failure diagnosis, fault localization, causal diagnosis | A high-ranked service is not proof of causal root cause. |
| Failure prediction | fault forecasting, incident prediction, early warning, prognostics, predictive failure management, disruptive-failure prediction | Prediction of an error state, a user-visible failure, RUL and ticket severity are different targets. |
| Severity | impact, criticality, priority, risk, consequence, SLO-breach duration | Must be operationalized from service impact, not invented from fault type. |
| Capacity forecasting | workload/resource forecasting, predictive/proactive autoscaling, anticipatory scaling, elasticity control | Forecast accuracy does not establish SLO or cost benefit. |
| Remediation | self-healing, autonomic computing, closed-loop operations, MAPE-K, recovery orchestration | A recommendation is not an executed, safe remediation. |
| Multimodal observability | logs-metrics-traces, telemetry fusion, cross-signal correlation | More signals may add cost/noise; their incremental value requires ablation. |

## 3. Field evolution and current state

Classical log and KPI anomaly detection established sequence-, invariant-, PCA- and statistical-baseline approaches. DeepLog introduced an online LSTM workflow model trained on normal log execution, plus incremental adaptation and log-driven diagnosis ([Du et al., 2017](https://doi.org/10.1145/3133956.3134015)). Modern research includes multimodal and topology-aware RCL; for example, TraceDiag uses trace-derived dependency-graph pruning followed by causal RCA and was evaluated/deployed in Microsoft Exchange ([Ding et al., 2023](https://doi.org/10.1145/3611643.3613864)).

For microservice RCL, the strongest current pattern is not a universally winning model: it is a match between available signals, topology dynamism, fault class and evaluation setup. Fu et al.'s 2025 ACM survey identifies multimodal collection, relationship characterization, localization effectiveness and overhead as central issues, and cautions that many studies remain closed-world and emphasize effectiveness over resource overhead ([Fu et al., 2025](https://doi.org/10.1145/3736755)).

Forecast-driven scaling is also established. Guruge and Priyadarshana propose a Prophet+LSTM MAPE-loop design, but evaluate forecasting on NASA and 1998 FIFA workload data rather than a live end-to-end application/SLO experiment; the paper itself lists Kubernetes-agent/KEDA integration as future work ([Guruge & Priyadarshana, 2025](https://doi.org/10.3389/fcomp.2025.1509165)). That limitation supports a need for better operational evaluation, not a claim that no such evaluation exists.

Most importantly, Denaro et al.'s peer-reviewed 2024 paper **Preface** predicts and localizes failures in autoscaling Kubernetes applications using rectified variable-size KPI sets and an autoencoder. It evaluates one commercial LMS and TrainTicket, including injected failures, and reports result ranges that depend on the scenario; it is a direct counterexample to any claim that failure prediction for autoscaling applications has no precedent ([Denaro et al., 2024](https://doi.org/10.1145/3660794); [full paper](https://star.inf.usi.ch/media/papers/2024-fse-ketai-preface.pdf)).

## 4. Module-by-module assessment

| Module | Established methods and strongest fit | Important constraints / failure conditions | Project classification |
|---|---|---|---|
| Ingestion | OpenTelemetry-correlated metrics, logs and traces; stable service/pod/trace identifiers | Missing identifiers, sampling, clock skew, high-cardinality cost and schema drift can invalidate correlation | Engineering implementation |
| Anomaly detection | Robust/statistical baselines and Isolation Forest for low-label tabular KPIs; sequence autoencoders/transformers for temporal or log sequences | Class imbalance, changing workload/seasonality, training on contaminated “normal,” and alert threshold choice dominate results | Established-method application |
| RCL | Causal/dependency graphs, random walk/ranking, trace methods, Bayesian/graph learning; topology-aware methods when deployment changes | Cascades make symptom/root labels ambiguous; injected faults can leak labels; overhead and unseen faults are under-evaluated | Established-method application; possible empirical ablation |
| Failure prediction | Temporal anomaly-to-failure predictors, autoencoders, LSTMs and feature rectification for variable pod count | Label definition, horizon, class imbalance and temporal leakage determine validity; prediction is not prevention | Established-method application |
| Capacity forecasting/autoscaling | Seasonal naive, HPA thresholds, Prophet/ARIMA, gradient boosting/LSTM; hybrid reactive-proactive policies | Forecast error, cold start, scale latency, nonstationarity, resource limits and bad fault classes (e.g. memory leak) can make scaling harmful | Empirical contribution if operational effect is measured |
| Remediation | Runbooks, policy gates, rollback/restart/scale actions, MAPE-K and human approval | Wrong or repeated action can widen blast radius; action safety needs constraints and auditability | Engineering/safety contribution |
| Explainability | SHAP for tabular feature attributions; local explanations/ranked evidence; trace/causal paths for diagnosis | Post-hoc attribution is not causation and does not by itself demonstrate operator trust or better decisions | Engineering feature unless evaluated with users |

The supplied anomaly survey is a useful broad taxonomy but is an arXiv preprint ([Zhong et al., 2023](https://arxiv.org/abs/2308.00393)). The supplied DEEPCASE paper is a security-event triage study, so it provides adjacent evidence about contextual event correlation but is not a valid direct benchmark for microservice SLO anomaly detection. Similarly, the supplied maritime and IoT XAI studies support the portability of SHAP-style explanation, not evidence of AIOps operational benefit.

## 5. Data, benchmark and testbed landscape

Public datasets are heterogeneous and usually answer only part of the system question. LogHub supports log methods; AIOps Challenge data, GAIA and TrainTicket variants offer different combinations of logs, metrics, traces and topology; many are either production data with restricted labels or testbed fault injections. A recent failure-diagnosis survey catalogs this fragmentation and specifically lists Sock Shop and TrainTicket as microservice testbeds, while warning through its taxonomy that data modalities and environments vary ([Zhang et al., *Failure Diagnosis in Microservice Systems*](https://nkcs.iops.ai/wp-content/uploads/2025/01/Failure_Diagnosis_Survey_to_TOSEM2.pdf)).

Sock Shop plus Chaos Mesh is therefore a valid reproducible testbed, but not a substitute for production external validity. It is no longer unusual: RCAEval contains 735 labelled fault cases across Online Boutique, Sock Shop and TrainTicket, with 11 fault types and metrics/logs/traces in its multimodal subsets ([RCAEval](https://doi.org/10.5281/zenodo.14590730)). It should be used as an external RCL benchmark or at least as a comparability reference—not merely cited as justification for creating a private dataset.

**Dataset implications.**

- Use a normal-operations period only for unsupervised fit; use chronologically later, fault-injected data for test. Do not random-split time windows.
- Keep fault-injection manifests and seed/configuration separate from model inputs. They are ground truth, not telemetry features.
- Label three different outcomes: (1) injected fault/root service, (2) observable anomaly, and (3) user-facing SLO breach. Do not collapse them.
- Use workload traces that contain seasonality only if diagnostics support it. Include seasonal-naive and reactive HPA baselines; Prophet is not a default winner.
- Record pod counts, provisioning/ready latency, CPU/memory requests and limits, SLO indicators, and all scaling events. Otherwise operational benefit cannot be measured.

## 6. Claim–evidence matrix

| Project claim | Supporting evidence | Counter-evidence / limitation | Verdict |
|---|---|---|---|
| Static thresholds are inadequate for all monitoring | Learning-based methods address drift and multidimensional patterns | Thresholds can be transparent, cheap and effective for known SLOs; they are indispensable baselines | **Supported, conditional** |
| Metrics, logs and traces should be unified | Complementary signals can support diagnosis; modern RCL surveys frame multimodal collection as central | Added modalities add synchronization, volume and missing-data problems; incremental value is rarely isolated | **Supported, not demonstrated for this platform** |
| Isolation Forest + LSTM AE is a strong anomaly detector | Both are established practical methods for unlabeled and temporal data | No evidence makes their unweighted combination generally superior to robust, forecasting or modern multimodal methods | **Suggested** |
| Graph correlation yields root cause | TraceDiag and related work show strong context-dependent RCL | Correlation/ranking can confuse propagated symptoms with causes; topology and labels matter | **Supported, conditional** |
| Better forecast accuracy reduces SLO breaches | Scaling can act before demand peaks; proactive studies report benefits in particular setups | Forecast-quality metrics do not prove control benefit; inaccurate forecasts create waste/churn | **Assumed until tested in the chosen setting** |
| The complete seven-module platform is novel | No exact same component names were found | Prior closed-loop/self-healing AIOps, detection+RCL, prediction+localization, and proactive scaling systems overlap substantially | **Contradicted** |
| GAP-1: no one has tested proactive scaling against reactive baselines for SLA impact | Guruge & Priyadarshana did not complete such an operational evaluation | FLAS explicitly evaluates forecasted scaling against performance requirements; further recent Kubernetes work also reports reactive comparisons. Exact testbeds vary, but the general claim is false ([Fazio et al., 2021](https://doi.org/10.1016/j.future.2020.06.042)) | **Already addressed / actively researched** |
| GAP-2: no precedent exists for failure occurrence plus severity prediction in a live autoscaler | Exact joint target in a Sock Shop/Kubernetes/Chaos Mesh setting was not identified in this search | Autoscaling failure prediction exists (Preface); IT incident severity prediction exists; PHM jointly models occurrence/consequence/risk under different names. The stated combination is underdefined, so absence cannot be inferred | **Insufficient evidence; terminology risk high** |

## 7. Negative literature review — why the project may not be novel

1. The **architecture** is a conventional AIOps pipeline. The supplied 2026 hybrid-RCA manuscript even combines Isolation Forest, LSTM, graph networks and SHAP, although its venue/evaluation claims should not be relied on as strong evidence.
2. **Deep learning from logs** and online adaptation are established in DeepLog. The proposed LSTM is not novel.
3. **Large-scale microservice RCL** with traces, dependency graphs, causal reasoning and deployment evidence exists in TraceDiag. A simplified service-dependency graph is not novel.
4. **Failure prediction for autoscaling Kubernetes** is directly addressed by Preface, which also localizes responsible microservices.
5. **Proactive/reactive hybrid autoscaling** has been evaluated for performance/SLA objectives (e.g. FLAS); “we used forecasting to scale pods” is not a research contribution.
6. **Self-healing and human-in-the-loop remediation** are established autonomy/safety patterns. A restart/scale runbook with approval is an appropriate engineering design, not a scientific discovery.
7. **SHAP/LIME integration** is a standard post-hoc explanation step. Without a study of explanation fidelity or operator decision quality, it should not be called trust improvement.

## 8. Research gaps that survive adversarial search

| Candidate gap | Evidence supporting it | Strongest counter-evidence | Status and confidence |
|---|---|---|---|
| Exact **Sock Shop + Chaos Mesh** comparison of forecast-assisted versus tuned reactive HPA across predeclared fault classes, reporting SLO, cost and churn | Exact configuration not identified; RCAEval makes the testbed realistic and comparable | Exact testbed difference is not a general scientific gap | **Feasible empirical setting, not a novelty claim** — High |
| Conditions under which forecast-assisted scaling helps or harms during combined workload change and fault injection | Forecast papers commonly emphasize forecast metrics or selected performance outcomes; Guruge does not run an end-to-end live SLO study | FLAS and later work establish that proactive/hybrid approaches can help, so the binary question is closed | **Probable conditional gap** — Medium |
| Incremental operational value of metrics/logs/traces in the same RCL pipeline and fault suite | Multimodal work is common, but controlled modality ablations are less common than end-to-end accuracy reports | RCAEval and modern multimodal studies already facilitate this; a one-testbed result will be local | **Potential empirical gap** — Medium |
| Safe remediation policy for different diagnosed fault classes | Safety/closed-loop autonomy remains an active topic | A capstone can only test a narrow, allow-listed action set | **Active research; engineering contribution** — High |
| Joint occurrence-and-severity prediction in a live autoscaler | Can be made precise as probability of SLO breach plus expected breach duration | Closely related work exists under incident risk/priority, FMEA/FMECA and PHM terminology; no exhaustive exact-architecture proof completed | **Not usable as a novelty claim yet** — Low |

## 9. Recommended research question and hypotheses

### Primary RQ

**Under predeclared nonstationary workloads and capacity-responsive injected faults in Sock Shop, does a forecast-assisted hybrid Kubernetes scaling policy reduce SLO-breach duration and SLO-breaching requests relative to a tuned reactive HPA without unacceptable resource cost or scaling churn?**

This deliberately excludes pure code/configuration/network faults for which adding pods is not a plausible remedy. Those faults belong in detection/RCL evaluation or in an explicit “scaling should not help” negative-control stratum.

### Secondary RQs

1. How do seasonal-naive, Prophet, and an LSTM/other selected forecaster differ in forecast error, inference time, and resulting control outcomes?
2. Does the hybrid safety rule reduce overprovisioning and oscillation compared with forecast-only scaling?
3. Does metrics-only versus metrics+traces versus metrics+logs+traces improve top-*k* root-service localization under the same fault suite, and at what telemetry/compute cost?
4. For allow-listed remediation actions, does human approval change time-to-mitigation, false-action rate, or recovery success?

### Testable hypotheses

- **H1:** The hybrid policy lowers paired SLO-breach duration versus tuned HPA for predictable load spikes and capacity-responsive faults.
- **H2:** Forecast-only scaling has higher pod-minutes or scaling churn than the hybrid policy under forecast error or abrupt workload changes.
- **H3:** Multimodal RCL raises top-1/top-3 localization accuracy for at least some fault classes, but its gain is fault- and modality-dependent.
- **H4:** An approved allow-list has a lower false-remediation rate than an unconstrained action policy; this is a safety property, not proof of autonomy.

## 10. Experiment design required for a defensible result

### Arms

1. **Reactive baseline:** Kubernetes HPA, tuned once using a predeclared procedure.
2. **Forecast-only policy:** chosen forecast-to-replica mapping.
3. **Hybrid policy:** forecast scaling plus reactive HPA safety net, cooldown and min/max-replica guardrails.
4. **Optional diagnosis/remediation arm:** same controller with RCL-informed, human-approved allow-listed action; keep it separate from the autoscaling causal comparison.

Use the same cluster, image versions, resource requests/limits, workload trace, fault start time, SLO, warm-up period and replica bounds within every paired block. Randomize policy order within each block to reduce time/environment confounding.

### Factors and scenarios

- **Workload:** stationary baseline, predictable diurnal/periodic trace, abrupt spike, bursty/non-periodic trace.
- **Capacity-responsive faults:** CPU stress/saturation, temporary resource exhaustion only where scaling is logically capable of helping.
- **Negative controls:** network delay/loss, code-level error, dependency failure, memory leak. Report these separately; do not advertise a failed scale-up as a forecasting failure.
- **Load/fault interaction:** no fault, fault only, load only, load+fault. This factorial design isolates whether autoscaling benefit comes from load prediction or accidentally masks a fault.

### Targets, metrics and statistics

Define before collection:

| Layer | Measures |
|---|---|
| Forecast/model | MAE/RMSE or MASE versus seasonal-naive, bias, prediction latency, calibration if predicting breach probability |
| Detection/RCL | event precision/recall, false alerts per fault-free hour, MTTD from fault onset, top-1/top-3 root-service accuracy, time to correct localization |
| Operations (primary) | SLO-breach duration, count/proportion of SLO-breaching requests, time to recovery, pod-minutes/CPU-seconds, scaling actions, oscillations, remediation latency, false-remediation rate |

For every scenario-policy pairing, run at least **20 independent repetitions** if practical; if capacity only permits fewer, report that constraint and do not overclaim. Report raw paired values, median/mean, spread, 95% bootstrap confidence intervals and effect sizes. Use paired tests selected after checking distributional assumptions (for example, Wilcoxon signed-rank for non-normal paired results) and correct planned multiple comparisons. Fix all hyperparameters from validation data before the final chronological test period.

### Required ablations and audits

- forecast-only vs reactive-only vs hybrid;
- seasonal-naive vs chosen forecaster;
- metrics-only vs each added modality for RCL;
- with/without topology features;
- forecast horizon, HPA cooldown and replica-mapping sensitivity;
- contamination test: train only on the pre-fault period;
- unseen fault/service or held-out workload segment where feasible;
- telemetry, inference and controller-overhead measurement;
- blind/manifest-isolated ground-truth scoring.

Release manifests, Helm/Kubernetes versions, Chaos Mesh scenarios, traffic traces, seeds, dashboards/query definitions, feature schemas, hyperparameters, raw anonymized results and analysis code. Without these, the result is a demonstration rather than a reproducible experiment.

## 11. What the report and viva should say—and avoid

**Safe positioning:** “We build an integrated AIOps prototype and empirically evaluate a forecast-assisted scaling policy under a controlled microservice fault-and-load matrix. Our contribution is evidence about conditions, trade-offs and failure cases in this testbed.”

**Do not say:**

- “the first integrated AIOps platform”; 
- “the first use of Isolation Forest, LSTM, graphs, SHAP or Prophet in AIOps”; 
- “no prior autoscaling work measures SLA violations”; 
- “forecast accuracy proves reliability improvement”; 
- “root-cause ranking proves causality”; 
- “human approval makes remediation safe”; or
- “Sock Shop results generalize to production.”

## 12. Final literature matrix

| Paper/source | Year | Contribution and evidence | Dataset/testbed | Main limitation / gap impact | Tier |
|---|---:|---|---|---|---|
| Zhang et al., *A Survey of AIOps in the Era of LLMs* | 2025 | Maps 183 LLM4AIOps articles, tasks, sources and evaluation | Survey | Broad survey; not a model benchmark | 1 |
| Zhong et al., *Time Series AD in AIOps* | 2023 | Taxonomy of KPI time-series AD | Survey | arXiv, not microservice-RCL evaluation | 3 |
| Du et al., DeepLog | 2017 | Online LSTM log anomaly detection/diagnosis | Large system logs | Log-centric; cross-system correlation listed as future work | 1 |
| Fu et al., *Intelligent RCL in MicroService Systems* | 2025 | RCL workflow, methods and evaluation concerns | Survey | Shows scope is well established | 1 |
| Ding et al., TraceDiag | 2023 | RL graph pruning + causal trace RCA; deployed evidence | Microsoft Exchange traces | Single production domain and incident range | 1 |
| Moens et al., dynamic knowledge graphs | 2026 | Topology-aware anomaly detection and benchmark framework | Microservice fault-injection benchmark | Newer specific method, needs independent replication | 1 |
| Denaro et al., Preface | 2024 | Failure prediction/localization in autoscaling Kubernetes apps | Alemira, TrainTicket, injected failures | Does not establish optimal remediation/SLO policy | 1 |
| Guruge & Priyadarshana | 2025 | Prophet+LSTM proactive-scaling design | NASA/FIFA workload datasets | Forecast evaluation, no completed live operational integration | 2 |
| Fazio et al., FLAS | 2021 | Forecasted, hybrid reactive-proactive autoscaling | Distributed-service tests | Directly weakens broad GAP-1 | 2 |
| RCAEval | 2024 | Open labelled microservice RCA benchmark | Sock Shop, Online Boutique, TrainTicket | Testbed data; still valuable external reference | 2 |
| Baldoni et al., CASPER | 2012 | Online black-box CEP+HMM failure prediction | Air-traffic-control stress tests | Older, technical report status in supplied copy | 3 |
| Zhang et al. (NEC), IT failure prediction | 2017 | Log patterns + LSTM early-warning prediction | Two enterprise log traces | Does not imply autoscaling/SLO control | 2 |
| Johnphill et al., self-healing CPS review | 2023 | Critical review of detection-alert-remediation | Survey | CPS, not direct cloud evidence | 2 |
| Kim et al., explainable anomaly detection | 2021 | Isolation Forest + SHAP interpretation | Maritime engine data | Domain transfer; no AIOps operational outcome | 2 |
| Ali et al., incident classification/prediction | 2021 | Active-learning/SVM incident work | Eclipse logs | Weak target/data framing for a live temporal predictor | 2, low suitability |

## 13. Source inventory and quality notes

**Foundational/major surveys:** Zhang et al. (2025 LLM4AIOps); Fu et al. (2025 RCL); Zhong et al. (2023 AD preprint); the failure-diagnosis survey linked above.  
**Strong primary empirical work:** DeepLog; TraceDiag; Preface; FLAS; RCAEval.  
**Useful supplied domain-adjacent work:** Guruge & Priyadarshana; CASPER; Johnphill et al.; Kim et al.  
**Discovery-only or do-not-anchor-novelty sources:** the supplied small journal/unverified-looking architecture papers, single-author broad observability paper, and recent arXiv-only network forecasting comparison. They may inform keywords but should not support strong performance, novelty or deployment claims until venue and full experimental methods are independently checked.

## 14. Compact search log

| Search area | Terminology challenged | Key outcome |
|---|---|---|
| Field map | AIOps, LLM4AIOps, observability, failure diagnosis | Recent surveys establish a mature, fragmented field and deployment/evaluation gaps. |
| AD | KPI/time-series/log anomaly detection, outlier detection | Classical and deep methods coexist; no universally best method. |
| RCL | root cause localization/analysis, causal diagnosis, traces | Trace/causal/topology methods and benchmarks are already extensive. |
| Autoscaling | predictive/proactive/forecasted/hybrid autoscaling, SLA/SLO, Kubernetes | Broad “no SLA comparison” gap disproved; setting-specific conditional questions remain. |
| Failure prediction | autoscaling distributed apps, fault anticipation, incident prediction | Preface directly refutes a no-precedent claim. |
| PHM/RUL and severity | prognosis, RUL, risk, criticality, incident severity | Terminology shows occurrence and severity are routinely separated; exact proposed joint target needs definition. |
| Benchmarks | Sock Shop, Chaos Mesh, TrainTicket, multimodal RCA | RCAEval makes the chosen testbed defensible but not novel. |
| Critical search | leakage, closed world, overhead, self-healing safety, forecast error | Main risks are evaluation validity and unsupported operational causality, not absence of models. |

## 15. Remaining searches before a thesis/paper submission

1. Screen IEEE Xplore, ACM DL, Scopus and Web of Science with the terminology map; deduplicate and record inclusion/exclusion decisions.
2. Complete forward/backward citations for Preface, FLAS, Guruge & Priyadarshana, TraceDiag, RCAEval and the 2025 RCL survey.
3. Independently verify venues, DOIs, peer-review status, data availability and complete methods for every supplied low-tier/preprint source before it enters the final bibliography.
4. Search exact policy terms after the SLO, forecast horizon, workload generator, fault taxonomy and severity definition are fixed. At present, the research target is not specific enough for an absolute gap claim.
5. Review control/autonomic-computing and Kubernetes safety literature if any non-allow-listed remediation will be executed.

## Bottom line

The project should proceed as a well-scoped AIOps engineering prototype with a narrow, rigorous operational evaluation. The platform is useful; its novelty is not the assembly. Its possible scholarly value is credible only as transparent evidence about forecast-assisted control under explicitly bounded workload and fault conditions, including when that control fails.
