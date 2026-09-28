# PRD: AIOps — AI-Driven Anomaly Detection & Predictive Maintenance for IT Infrastructure

**Department:** Information Technology
**Team Size:** 4 Members
**Academic Year:** 2026–27

---

## 1. Abstract

Modern IT infrastructure, built predominantly on distributed microservice architectures, generates vast volumes of logs, metrics, and traces, yet most organizations continue to rely on static, threshold-based monitoring systems that are reactive in nature, detect failures only after they occur, and lack the ability to identify root causes across interdependent services. This project proposes the design and implementation of an integrated Artificial Intelligence for IT Operations (AIOps) platform that unifies anomaly detection, root-cause analysis, failure prediction, capacity forecasting, automated remediation, and explainable AI into a single, cohesive system for proactive infrastructure management. The proposed approach combines unsupervised anomaly detection using Isolation Forest and LSTM Autoencoder models with a graph-based root-cause correlation engine, a severity-aware failure-prediction module, a Prophet/LSTM-based capacity forecasting component, and a human-in-the-loop automated remediation engine, further supported by a SHAP/LIME-based explainability layer to ensure transparent, interpretable decision-making. The system is implemented using Python-based machine learning frameworks (scikit-learn, PyTorch/TensorFlow), an OpenTelemetry-based observability pipeline, a TimescaleDB backend, a Node.js/Express REST API layer, and a React-based real-time dashboard, containerized using Docker for deployment. Its effectiveness is validated through controlled fault-injection experiments on a simulated microservice environment, benchmarking detection speed, false-positive rate, and remediation success against conventional threshold-based monitoring.

---

## 2. Background & Problem Statement

Modern software systems have shifted from monolithic applications to **microservice architectures**, where an application is decomposed into dozens or hundreds of small, independently deployable services communicating over a network. This improves scalability and deployment flexibility but introduces significant operational complexity: a single failure can cascade across multiple interdependent services, and the volume of logs, metrics, and traces generated is far beyond what any human team can manually monitor.

Most organizations still rely on **static, threshold-based monitoring** (e.g., Nagios, Zabbix, basic Prometheus rules), which suffers from:

- **Inability to adapt** to dynamic, context-dependent system behavior — fixed thresholds can't distinguish expected traffic spikes from genuine anomalies.
- **Purely reactive detection** — alerts fire only after a threshold has already been breached.
- **Fragmented visibility** — logs, metrics, and traces are viewed through separate, siloed tools.
- **No automated root-cause identification** — when multiple services alert simultaneously, there's no way to distinguish the root cause from downstream symptoms.
- **Entirely manual remediation** — even well-understood, recurring issues require manual intervention every time.
- **Alert fatigue** — high false-positive rates cause engineers to ignore or delay responding to alerts.

There is a clear need for an **integrated, intelligent, and explainable system** capable of continuously monitoring distributed IT infrastructure, detecting anomalies with minimal false positives, automatically identifying root causes, predicting failures before they escalate, forecasting resource needs, and autonomously remediating known issues — all with transparent, human-interpretable reasoning.

---

## 3. Objectives

1. Design and implement a **unified data ingestion pipeline** that collects, parses, and correlates logs, performance metrics, and distributed traces from a simulated microservice-based IT infrastructure into a single, structured observability dataset.
2. Develop an **unsupervised anomaly detection module** (Isolation Forest + LSTM Autoencoder) capable of learning normal system behavior and identifying deviations in real time with a lower false-positive rate than static threshold-based monitoring.
3. Build an **automated root-cause analysis engine** that models inter-service dependencies as a graph structure and automatically traces a detected fault back to its originating service.
4. Design a **failure-prediction model** that analyzes historical incident patterns and current anomaly trends to estimate the likelihood of an impending failure, coupled with a severity/impact scoring mechanism.
5. Implement a **capacity forecasting module** that predicts future resource utilization trends (CPU, memory, storage) using time-series forecasting techniques.
6. Develop an **automated remediation engine** capable of executing corrective actions for known, recurring failure patterns, with a human-in-the-loop approval mechanism.
7. Incorporate an **explainability layer** (SHAP/LIME) that provides interpretable, human-readable justifications for the system's anomaly flags and failure predictions.
8. Build a **unified, real-time monitoring dashboard** consolidating live system health, root-cause visualizations, capacity forecasts, remediation logs, and model explanations.
9. **Evaluate** the system's effectiveness through controlled fault-injection experiments, benchmarking MTTD, false-positive rate, diagnostic accuracy, and remediation success rate against a conventional threshold-based baseline.

---

## 4. Existing System vs. Proposed System

| Capability | Existing System | Proposed System (This Project) |
|---|---|---|
| Detection | Fixed thresholds, high false positives | ML-based (Isolation Forest + LSTM Autoencoder), adapts to normal patterns |
| Timing | Reactive — after failure | Predictive — forecasts likely failures before they occur |
| Root cause | Manual correlation across siloed tools | Automated root-cause graph pinpoints originating service |
| Severity | Not assessed | Impact/severity scoring prioritizes alerts |
| Capacity planning | Manual, ad hoc | Automated forecasting of future resource needs |
| Remediation | Fully manual | Automated remediation for known patterns, human-approved |
| Trust/transparency | Black-box or no ML at all | Explainability layer (SHAP/LIME) shows why something was flagged |
| Data view | Logs, metrics, traces siloed | Unified observability pipeline correlating all three |

---

## 5. Proposed System — Modules

### Module 1: Unified Data Ingestion
Collects logs, metrics, and traces from a simulated microservice environment using OpenTelemetry, unifying the "three pillars of observability" into a single structured dataset for downstream analysis.

### Module 2: Unsupervised Anomaly Detection
Combines Isolation Forest (fast outlier isolation) with an LSTM Autoencoder (temporal pattern reconstruction) to flag deviations from learned normal system behavior, without requiring labeled failure data.

### Module 3: Automated Root-Cause Analysis
Builds a service-dependency graph and, upon detecting correlated anomalies across services, automatically traces the fault back to its originating component rather than merely listing all affected services.

### Module 4: Severity-Aware Failure Prediction
Analyzes sequences of anomalies and historical incident data to predict the likelihood of an impending failure, along with a severity score to prioritize the most business-critical predicted incidents.

### Module 5: Capacity Forecasting
Uses Prophet and/or LSTM-based forecasting on historical resource-utilization trends (CPU, memory, storage) to support proactive scaling decisions.

### Module 6: Automated Remediation (Human-in-the-Loop)
Executes corrective actions (e.g., service restart, resource scaling) for known, recurring failure patterns, with an approval step for safety before any action is taken autonomously.

### Module 7: Explainability Layer
Applies SHAP and LIME to anomaly and failure-prediction outputs, providing human-readable justification for every flagged event — addressing the black-box trust problem common in ML-based monitoring tools.

---

## 6. Technology Stack

| Layer | Technology |
|---|---|
| Machine Learning | Python, scikit-learn, PyTorch / TensorFlow, Prophet |
| Observability / Data Collection | OpenTelemetry (logs, metrics, traces) |
| Data Storage | TimescaleDB (PostgreSQL extension for time-series data) |
| Backend / REST API | Node.js with Express |
| Frontend Dashboard | React |
| Explainability | SHAP, LIME |
| Containerization / Deployment | Docker |
| Fault Injection (testing) | Chaos Mesh, on a Sock Shop / microservices-demo environment |

> **Note:** ML components are implemented in Python and write results (anomaly scores, predictions, root-cause outputs) directly into TimescaleDB. The Express REST API layer reads from the database and serves the React dashboard — keeping ML and full-stack layers cleanly separated for parallel team development.

---

## 7. Dataset Strategy

A hybrid data strategy combining public benchmark datasets with self-generated, fault-injected data:

- **NAB (Numenta Anomaly Benchmark)** — labeled real/synthetic time-series data for anomaly detection benchmarking.
- **LogHub** — real system log datasets (HDFS, OpenStack, etc.) for log-based anomaly detection, consistent with the DeepLog methodology.
- **Google Cluster Trace / Azure Public Dataset** — real production workload traces for realistic resource-usage patterns and capacity forecasting.
- **Backblaze Hard Drive Stats** — supplementary real-world hardware failure data for the failure-prediction module.
- **Self-generated data via fault injection** — a simulated microservice environment (Sock Shop / microservices-demo) with Chaos Mesh is used to deliberately inject faults and generate ground-truth labeled incidents for root-cause analysis, failure prediction, and evaluation, since labeled root-cause/remediation data isn't available publicly.

---

## 8. System Architecture Overview

1. Microservices (Sock Shop demo) emit logs, metrics, and traces, collected via OpenTelemetry.
2. The ingestion pipeline normalizes and writes this data into TimescaleDB.
3. The anomaly detection module (Isolation Forest + LSTM Autoencoder) continuously scores incoming data and flags deviations.
4. Flagged anomalies are passed to the root-cause engine, which correlates them against the service-dependency graph to identify the originating service.
5. The failure-prediction module estimates the likelihood and severity of an impending incident based on anomaly trends and historical patterns.
6. The capacity forecasting module runs in parallel on resource-utilization data to project future needs.
7. For known, recurring issue patterns, the remediation engine proposes (and, with approval, executes) a corrective action.
8. All outputs — anomalies, root causes, predictions, forecasts, remediation actions — are accompanied by SHAP/LIME explanations and surfaced on the React dashboard via the Express REST API.
9. Fault injection (Chaos Mesh) is used throughout development to generate test scenarios and, at evaluation time, to benchmark the system against a threshold-based baseline.

---

## 9. Evaluation Methodology

Since production incident data isn't available for an academic project, the system is evaluated using **controlled fault-injection experiments** on the simulated Sock Shop microservice environment. Chaos Mesh deliberately induces failures — killing a service, spiking memory or CPU usage, introducing network latency — creating ground-truth labeled incidents.

The system is benchmarked against a conventional threshold-based monitoring baseline on:

- **Mean Time to Detect (MTTD)** — how quickly each system identifies an injected fault.
- **False-positive rate** — how often each system raises an alert with no genuine underlying issue.
- **Root-cause accuracy** — whether the system correctly identifies the originating service versus a downstream symptom.
- **Remediation success rate** — the proportion of known-pattern faults successfully auto-remediated.

---

## 10. Expected Outcomes

1. A functional, end-to-end AIOps prototype capable of ingesting real-time logs, metrics, and traces and producing actionable anomaly, root-cause, and failure-risk insights.
2. Measurable reduction in Mean Time to Detect (MTTD) and false-positive alert rates, validated through fault-injection experiments, compared to conventional threshold-based monitoring.
3. Automated root-cause identification, reducing the manual diagnostic effort required to trace a failure to its originating service.
4. A proactive failure-prediction and partial self-healing capability, warning operators of impending failures and automatically resolving known, recurring issues.
5. An interpretable, trustworthy system, where every anomaly flag and prediction is accompanied by a human-readable explanation, supported by a documented benchmark comparing the system against traditional monitoring.

---

## 11. Team Roles and Ownership

| Team Member | Core Responsibility |
|---|---|
| Person A | Data pipeline (OpenTelemetry ingestion) + root-cause graph support |
| Person B | Dataset integration (NAB/LogHub) + Isolation Forest + evaluation |
| Person C | Architecture/TimescaleDB schema + LSTM Autoencoder |
| Person D | Chaos Mesh fault injection + root-cause correlation logic + remediation engine + dashboard |

---

## 12. References

A total of 20 papers were surveyed, spanning all seven core modules of the proposed system (general AIOps overview, data ingestion/observability, anomaly detection, root-cause analysis, failure prediction, capacity forecasting, automated remediation/self-healing, and explainability). Full titles, authors, and direct access links are maintained in the accompanying reference spreadsheet (`AIOps_Reference_List.xlsx`).
