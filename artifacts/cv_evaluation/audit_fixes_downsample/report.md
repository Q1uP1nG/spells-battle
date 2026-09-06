# Gesture Evaluation

## Scope and limitations

This is a regression baseline on the current legacy corpus, not evidence of cross-user or cross-device generalization. `data_template` uses a template pack built from this bank and is therefore a resubstitution result. `real_template` uses sample-level leave-one-out DTW but is not yet session-grouped.

Dataset partition: `development`. `session_grouped_cv` with 5 folds; group IDs are kept entirely within one test fold.

## Corpus audit

- Canonical samples: 77
- Duplicate views merged: 27
- Latest reviews: 86 (27 accepted, 59 discarded)
- Corpus version: `sha256:e1568e2da0c5bf8f51a1d69a0624cfa8c7a78f54ba05555eb89faabb29fa40d3`

## Results

```text
Total labeled samples: 77

logged_primary: 43/77 (55.8%)
  macro_f1=0.710 rejection=36.4% error_acceptance=7.8%
  circle: 6/11 (54.5%)
  glacius: 10/12 (83.3%)
  incendio: 6/28 (21.4%)
  lumos: 11/14 (78.6%)
  overload: 10/12 (83.3%)

current_heuristic: 45/77 (58.4%)
  macro_f1=0.733 rejection=33.8% error_acceptance=7.8%
  latency_ms p50=0.064 p95=0.123
  circle: 7/11 (63.6%)
  glacius: 10/12 (83.3%)
  incendio: 5/28 (17.9%)
  lumos: 11/14 (78.6%)
  overload: 12/12 (100.0%)

normalized_heuristic_shadow: 47/77 (61.0%)
  macro_f1=0.758 rejection=32.5% error_acceptance=6.5%
  latency_ms p50=0.138 p95=0.211
  normalization_sources={'trajectory_span_fallback': 77}
  circle: 7/11 (63.6%)
  glacius: 11/12 (91.7%)
  incendio: 6/28 (21.4%)
  lumos: 12/14 (85.7%)
  overload: 11/12 (91.7%)

logged_shadow: 16/19 (84.2%)
  macro_f1=0.524 rejection=0.0% error_acceptance=15.8%
  circle: 0/1 (0.0%)
  glacius: 2/2 (100.0%)
  incendio: 10/10 (100.0%)
  lumos: 4/4 (100.0%)
  overload: 0/2 (0.0%)

real_template: 70/77 (90.9%)
  macro_f1=0.898 rejection=0.0% error_acceptance=9.1%
  margin p50=0.101 p95=0.211
  circle: 11/11 (100.0%)
  glacius: 12/12 (100.0%)
  incendio: 26/28 (92.9%)
  lumos: 14/14 (100.0%)
  overload: 7/12 (58.3%)

grouped_template: 41/77 (53.2%)
  macro_f1=0.531 rejection=0.0% error_acceptance=46.8%
  margin p50=0.060 p95=0.166
  circle: 3/11 (27.3%)
  glacius: 12/12 (100.0%)
  incendio: 10/28 (35.7%)
  lumos: 13/14 (92.9%)
  overload: 3/12 (25.0%)

grouped_cyclic_template_shadow: 0/0 (0.0%)
  macro_f1=0.000 rejection=0.0% error_acceptance=0.0%
  status=unavailable reason=fold 3 has too few Stupefy training samples for cyclic evaluation

data_template: 75/77 (97.4%)
  macro_f1=0.977 rejection=0.0% error_acceptance=2.6%
  latency_ms p50=3.492 p95=4.230
  circle: 11/11 (100.0%)
  glacius: 12/12 (100.0%)
  incendio: 28/28 (100.0%)
  lumos: 13/14 (92.9%)
  overload: 11/12 (91.7%)

cyclic_template_shadow: 73/77 (94.8%)
  macro_f1=0.957 rejection=2.6% error_acceptance=2.6%
  latency_ms p50=0.187 p95=19.539
  diagnostics={'ambiguous': 2, 'closure_gate_passed': 11, 'cyclic_top1': 9}
  circle: 9/11 (81.8%)
  glacius: 12/12 (100.0%)
  incendio: 28/28 (100.0%)
  lumos: 13/14 (92.9%)
  overload: 11/12 (91.7%)

fused: 73/77 (94.8%)
  macro_f1=0.950 rejection=1.3% error_acceptance=3.9%
  latency_ms p50=3.456 p95=4.346
  circle: 9/11 (81.8%)
  glacius: 12/12 (100.0%)
  incendio: 26/28 (92.9%)
  lumos: 14/14 (100.0%)
  overload: 12/12 (100.0%)

hybrid_1_0_0_2: 71/77 (92.2%)
  macro_f1=0.929 rejection=0.0% error_acceptance=7.8%
  circle: 10/11 (90.9%)
  glacius: 12/12 (100.0%)
  incendio: 23/28 (82.1%)
  lumos: 14/14 (100.0%)
  overload: 12/12 (100.0%)

Real-template confusion:
  circle: {'stupefy': 11}
  glacius: {'glacius': 12}
  incendio: {'lumos': 2, 'incendio': 26}
  lumos: {'lumos': 14}
  overload: {'overload': 7, 'incendio': 2, 'glacius': 3}

Circle/Overload focus:
  circle -> stupefy:
    current_heuristic: 7/11 (63.6%)
    normalized_heuristic_shadow: 7/11 (63.6%)
    grouped_template: 3/11 (27.3%)
    grouped_cyclic_template_shadow: 0/0 (0.0%)
    data_template: 11/11 (100.0%)
    cyclic_template_shadow: 9/11 (81.8%)
    fused: 9/11 (81.8%)
    real_template: 11/11 (100.0%)
  overload -> overload:
    current_heuristic: 12/12 (100.0%)
    normalized_heuristic_shadow: 11/12 (91.7%)
    grouped_template: 3/12 (25.0%)
    grouped_cyclic_template_shadow: 0/0 (0.0%)
    data_template: 11/12 (91.7%)
    cyclic_template_shadow: 11/12 (91.7%)
    fused: 12/12 (100.0%)
    real_template: 7/12 (58.3%)

Current/template misses:
  #2 attempt=None label=circle method=current_heuristic pred=overload points=34 top=['circle:0.116', 'overload:0.237', 'incendio:0.238']
  #2 attempt=None label=circle method=cyclic_template_shadow pred=None points=34 top=['circle:0.116', 'overload:0.237', 'incendio:0.238']
  #2 attempt=None label=circle method=fused pred=overload points=34 top=['circle:0.116', 'overload:0.237', 'incendio:0.238']
  #5 attempt=None label=circle method=current_heuristic pred=overload points=16 top=['circle:0.155', 'lumos:0.224', 'incendio:0.234']
  #6 attempt=None label=circle method=cyclic_template_shadow pred=None points=28 top=['circle:0.119', 'incendio:0.156', 'overload:0.180']
  #8 attempt=None label=circle method=current_heuristic pred=None points=25 top=['circle:0.147', 'overload:0.241', 'incendio:0.286']
  #9 attempt=None label=circle method=current_heuristic pred=None points=32 top=['circle:0.067', 'overload:0.206', 'incendio:0.250']
  #9 attempt=None label=circle method=fused pred=None points=32 top=['circle:0.067', 'overload:0.206', 'incendio:0.250']
  #21 attempt=121 label=glacius method=current_heuristic pred=None points=4 top=['glacius:0.032', 'overload:0.092', 'incendio:0.264']
  #22 attempt=21 label=glacius method=current_heuristic pred=None points=6 top=['glacius:0.015', 'overload:0.117', 'circle:0.309']
  #23 attempt=None label=incendio method=current_heuristic pred=lumos points=14 top=['lumos:0.012', 'circle:0.181', 'incendio:0.188']
  #23 attempt=None label=incendio method=real_template pred=lumos points=14 top=['lumos:0.012', 'circle:0.181', 'incendio:0.188']
  #24 attempt=None label=incendio method=current_heuristic pred=None points=19 top=['incendio:0.023', 'overload:0.163', 'circle:0.234']
  #26 attempt=None label=incendio method=current_heuristic pred=None points=14 top=['incendio:0.015', 'overload:0.138', 'circle:0.190']
  #28 attempt=None label=incendio method=current_heuristic pred=overload points=32 top=['incendio:0.027', 'overload:0.134', 'circle:0.223']
  #28 attempt=None label=incendio method=fused pred=overload points=32 top=['incendio:0.027', 'overload:0.134', 'circle:0.223']
  #29 attempt=None label=incendio method=current_heuristic pred=None points=22 top=['incendio:0.023', 'overload:0.148', 'circle:0.231']
  #30 attempt=None label=incendio method=current_heuristic pred=overload points=14 top=['incendio:0.052', 'overload:0.135', 'lumos:0.154']
  #30 attempt=None label=incendio method=fused pred=overload points=14 top=['incendio:0.052', 'overload:0.135', 'lumos:0.154']
  #31 attempt=None label=incendio method=current_heuristic pred=None points=22 top=['incendio:0.015', 'overload:0.142', 'circle:0.201']
  #32 attempt=None label=incendio method=current_heuristic pred=overload points=24 top=['incendio:0.052', 'lumos:0.126', 'circle:0.156']
  #33 attempt=10 label=incendio method=current_heuristic pred=None points=6 top=['incendio:0.000', 'overload:0.211', 'lumos:0.287']
  #35 attempt=11 label=incendio method=current_heuristic pred=None points=5 top=['incendio:0.000', 'overload:0.211', 'lumos:0.287']
  #36 attempt=12 label=incendio method=current_heuristic pred=None points=5 top=['incendio:0.000', 'overload:0.211', 'lumos:0.287']
  #38 attempt=15 label=incendio method=current_heuristic pred=None points=4 top=['lumos:0.179', 'circle:0.181', 'overload:0.213']
  #38 attempt=15 label=incendio method=real_template pred=lumos points=4 top=['lumos:0.179', 'circle:0.181', 'overload:0.213']
  #39 attempt=33 label=incendio method=current_heuristic pred=None points=4 top=['incendio:0.000', 'overload:0.200', 'lumos:0.257']
  #40 attempt=34 label=incendio method=current_heuristic pred=None points=4 top=['incendio:0.000', 'overload:0.200', 'lumos:0.257']
  #41 attempt=35 label=incendio method=current_heuristic pred=None points=4 top=['incendio:0.000', 'overload:0.200', 'lumos:0.257']
  #42 attempt=36 label=incendio method=current_heuristic pred=None points=4 top=['incendio:0.000', 'overload:0.200', 'lumos:0.257']
  #43 attempt=47 label=incendio method=current_heuristic pred=None points=18 top=['incendio:0.009', 'overload:0.218', 'circle:0.286']
  #44 attempt=52 label=incendio method=current_heuristic pred=None points=4 top=['incendio:0.005', 'overload:0.211', 'lumos:0.284']
  #45 attempt=53 label=incendio method=current_heuristic pred=None points=5 top=['incendio:0.047', 'overload:0.184', 'glacius:0.264']
  #46 attempt=7 label=incendio method=current_heuristic pred=None points=7 top=['incendio:0.001', 'overload:0.210', 'lumos:0.286']
  #47 attempt=78 label=incendio method=current_heuristic pred=None points=21 top=['incendio:0.018', 'overload:0.211', 'lumos:0.283']
  #49 attempt=8 label=incendio method=current_heuristic pred=None points=6 top=['incendio:0.000', 'overload:0.211', 'lumos:0.287']
  #50 attempt=9 label=incendio method=current_heuristic pred=None points=6 top=['incendio:0.000', 'overload:0.211', 'lumos:0.287']
  #57 attempt=None label=lumos method=data_template pred=incendio points=24 top=['lumos:0.011', 'incendio:0.050', 'circle:0.182']
  #57 attempt=None label=lumos method=cyclic_template_shadow pred=incendio points=24 top=['lumos:0.011', 'incendio:0.050', 'circle:0.182']
  #61 attempt=31 label=lumos method=current_heuristic pred=None points=5 top=['lumos:0.000', 'incendio:0.012', 'circle:0.181']
  #62 attempt=32 label=lumos method=current_heuristic pred=None points=5 top=['lumos:0.000', 'incendio:0.012', 'circle:0.181']
  #64 attempt=76 label=lumos method=current_heuristic pred=None points=6 top=['lumos:0.059', 'incendio:0.064', 'circle:0.186']
  #66 attempt=None label=overload method=real_template pred=incendio points=26 top=['incendio:0.125', 'overload:0.130', 'circle:0.185']
  #66 attempt=None label=overload method=data_template pred=incendio points=26 top=['incendio:0.125', 'overload:0.130', 'circle:0.185']
  #66 attempt=None label=overload method=cyclic_template_shadow pred=incendio points=26 top=['incendio:0.125', 'overload:0.130', 'circle:0.185']
  #72 attempt=None label=overload method=real_template pred=glacius points=48 top=['glacius:0.164', 'overload:0.170', 'circle:0.267']
  #73 attempt=None label=overload method=real_template pred=glacius points=48 top=['glacius:0.083', 'overload:0.149', 'incendio:0.300']
  #74 attempt=None label=overload method=real_template pred=incendio points=48 top=['incendio:0.200', 'circle:0.261', 'lumos:0.273']
  #76 attempt=58 label=overload method=real_template pred=glacius points=23 top=['glacius:0.128', 'overload:0.167', 'circle:0.358']
```
