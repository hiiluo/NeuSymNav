# B0 run report: dev60-v3h

Run b0dev60v3h, policy b0, b0 config configs/objectnav/b0-policy-v3.json (sha 47a946aaf2…), git a1f6c50 (dirty), max_sim_s 500.0.

## Overall

| Episodes | SR [95% CI] | SPL [95% CI] | SoftSPL | DTG end (m) | STOP rate | invalid |
|---|---|---|---|---|---|---|
| 60 | 0.283 [0.183, 0.400] | 0.064 [0.036, 0.099] | 0.114 | 3.48 | 0.62 | 0 |

## By category

| Category | Episodes | SR | SPL | SoftSPL | DTG end (m) |
|---|---|---|---|---|---|
| bed | 8 | 0.500 | 0.115 | 0.162 | 0.61 |
| chair | 9 | 0.556 | 0.137 | 0.142 | 1.18 |
| plant | 9 | 0.111 | 0.017 | 0.090 | 3.15 |
| sofa | 16 | 0.125 | 0.026 | 0.123 | 5.57 |
| toilet | 12 | 0.250 | 0.032 | 0.056 | 3.89 |
| tv_monitor | 6 | 0.333 | 0.129 | 0.132 | 4.83 |

## By scene

| Scene | Episodes | SR | SPL |
|---|---|---|---|
| LT9Jq6dN3Ea | 10 | 0.200 | 0.059 |
| TEEsavR23oF | 10 | 0.200 | 0.032 |
| bCPU9suPUw9 | 10 | 0.200 | 0.053 |
| k1cupFYWXJ6 | 10 | 0.300 | 0.062 |
| qyAac8rV8Zk | 10 | 0.600 | 0.101 |
| wcojb4TFT35 | 10 | 0.200 | 0.080 |

## Failure modes (scorer, with offline evidence)

| Mode | Episodes |
|---|---|
| never_seen | 26 |
| budget_exhausted | 6 |
| wrong_object_stop | 5 |
| stopped_too_far | 3 |
| seen_not_detected | 2 |
| stopped_elsewhere | 1 |

## Funnel (episodes)

| Step | Episodes |
|---|---|
| episodes | 60 |
| target seen (<= 3 m) | 30 |
| target detected (IoU >= 0.1) | 29 |
| a goal instance confirmed | 26 |
| STOP called | 37 |
| STOP on a goal instance | 19 |
| success | 17 |

## How episodes ended

| End reason | Episodes |
|---|---|
| policy_stop:confirmed_target | 23 |
| max_sim_time | 23 |
| policy_stop:stuck | 7 |
| policy_stop:frontiers_exhausted | 4 |
| policy_stop:fallback_target | 3 |

Policy events: {'arrived': 19, 'reject:approach_goal_reached_far': 11, 'fallback_best_unconfirmed': 9, 'arrived_far': 7, 'reject:approach_no_path': 7, 'reject:approach_timeout': 5, 'fallback_target': 3}.

Wrong objects B0 stopped at (semantic name): {'armchair': 5, 'chair': 1}.

Floor measurement methods: {'measured-downward-depth-center-patch-v1': 47, 'measured-downward-depth-near-pose-v1': 10, 'measured-downward-depth-mode-v1': 3}.

## Cost

Wall time 320.0 min total, 320.0 s per episode; simulated 315.2 s per episode; 177 detection frames per episode.

| Stage | Wall s per episode | Share |
|---|---|---|
| mapper | 143.2 | 45 % |
| perception | 51.3 | 16 % |
| guard | 49.5 | 15 % |
| capture_nav | 24.4 | 8 % |
| policy | 17.8 | 6 % |
| capture_primary | 14.9 | 5 % |
| execute | 8.8 | 3 % |
| probe | 0.0 | 0 % |
