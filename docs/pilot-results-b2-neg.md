# Pilot results — run `b2-neg`

n = 5 instances (0 positive, 5 negative)

## Adherence (positive set)

| tier | arm | n | adherence [95% CI] |
|---|---|---|---|
| downstream_strong | A0_none | 0 | nan% [nan%, nan%] |
| downstream_strong | A1_system | 0 | nan% [nan%, nan%] |
| downstream_strong | A2_inject | 0 | nan% [nan%, nan%] |
| downstream_strong | A3_translator | 0 | nan% [nan%, nan%] |
| downstream_weak | A0_none | 0 | nan% [nan%, nan%] |
| downstream_weak | A1_system | 0 | nan% [nan%, nan%] |
| downstream_weak | A2_inject | 0 | nan% [nan%, nan%] |
| downstream_weak | A3_translator | 0 | nan% [nan%, nan%] |

## Paired deltas: A3 vs injection arms

| tier | comparison | delta [95% CI] |
|---|---|---|

## False application rate (negative set)

| tier | arm | n | FAR [95% CI] |
|---|---|---|---|
| downstream_strong | A0_none | 5 | 0.0% [0.0%, 0.0%] |
| downstream_strong | A1_system | 5 | 60.0% [20.0%, 100.0%] |
| downstream_strong | A2_inject | 5 | 60.0% [20.0%, 100.0%] |
| downstream_strong | A3_translator | 5 | 20.0% [0.0%, 60.0%] |
| downstream_weak | A0_none | 5 | 0.0% [0.0%, 0.0%] |
| downstream_weak | A1_system | 5 | 40.0% [0.0%, 80.0%] |
| downstream_weak | A2_inject | 5 | 40.0% [0.0%, 80.0%] |
| downstream_weak | A3_translator | 5 | 20.0% [0.0%, 60.0%] |

## Translator behavior

- P(apply | positive) = 0/0 = 0.0%
- P(noop | negative) = 4/5 = 80.0%  ← 判据 G3
- parse errors: 0
- preservation: core-task changed 0, over-reach beyond memories 0 (of 0 positives)

## Downstream input tokens (mean per instance)

| tier | arm | mean input tokens |
|---|---|---|
| downstream_strong | A0_none | 53 |
| downstream_strong | A1_system | 338 |
| downstream_strong | A2_inject | 314 |
| downstream_strong | A3_translator | 64 |
| downstream_weak | A0_none | 37 |
| downstream_weak | A1_system | 246 |
| downstream_weak | A2_inject | 229 |
| downstream_weak | A3_translator | 44 |
