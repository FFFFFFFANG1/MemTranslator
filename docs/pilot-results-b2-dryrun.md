# Pilot results — run `b2-dryrun`

n = 20 instances (20 positive, 0 negative)

## Adherence (positive set)

| tier | arm | n | adherence [95% CI] |
|---|---|---|---|
| downstream_strong | A0_none | 20 | 20.0% [5.0%, 40.0%] |
| downstream_strong | A1_system | 20 | 100.0% [100.0%, 100.0%] |
| downstream_strong | A2_inject | 20 | 100.0% [100.0%, 100.0%] |
| downstream_strong | A3_translator | 20 | 75.0% [55.0%, 95.0%] |
| downstream_weak | A0_none | 20 | 5.0% [0.0%, 15.0%] |
| downstream_weak | A1_system | 20 | 80.0% [60.0%, 95.0%] |
| downstream_weak | A2_inject | 20 | 85.0% [70.0%, 100.0%] |
| downstream_weak | A3_translator | 20 | 70.0% [50.0%, 90.0%] |

## Paired deltas: A3 vs injection arms

| tier | comparison | delta [95% CI] |
|---|---|---|
| downstream_strong | A3 − A1_system | -25.0% [-45.0%, -5.0%] |
| downstream_strong | A3 − A2_inject | -25.0% [-45.0%, -5.0%] |
| downstream_weak | A3 − A1_system | -10.0% [-35.0%, +15.0%] |
| downstream_weak | A3 − A2_inject | -15.0% [-40.0%, +10.0%] |

## False application rate (negative set)

| tier | arm | n | FAR [95% CI] |
|---|---|---|---|
| downstream_strong | A0_none | 0 | nan% [nan%, nan%] |
| downstream_strong | A1_system | 0 | nan% [nan%, nan%] |
| downstream_strong | A2_inject | 0 | nan% [nan%, nan%] |
| downstream_strong | A3_translator | 0 | nan% [nan%, nan%] |
| downstream_weak | A0_none | 0 | nan% [nan%, nan%] |
| downstream_weak | A1_system | 0 | nan% [nan%, nan%] |
| downstream_weak | A2_inject | 0 | nan% [nan%, nan%] |
| downstream_weak | A3_translator | 0 | nan% [nan%, nan%] |

## Translator behavior

- P(apply | positive) = 14/20 = 70.0%
- P(noop | negative) = 0/0 = 0.0%  ← 判据 G3
- parse errors: 0
- preservation: core-task changed 0, over-reach beyond memories 0 (of 20 positives)

## Downstream input tokens (mean per instance)

| tier | arm | mean input tokens |
|---|---|---|
| downstream_strong | A0_none | 41 |
| downstream_strong | A1_system | 326 |
| downstream_strong | A2_inject | 302 |
| downstream_strong | A3_translator | 58 |
| downstream_weak | A0_none | 29 |
| downstream_weak | A1_system | 238 |
| downstream_weak | A2_inject | 221 |
| downstream_weak | A3_translator | 39 |
