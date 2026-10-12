# Frozen results

Result files produced before this artifact was built, copied byte for byte,
except in the `run_config.json` files: the `git_commit` value is redacted, the
`os` value is normalised to `Windows 11`, free-text `note` fields are rewritten
in English (the one in `manual90/` described the wrong run), absolute build
paths are replaced by the artifact-relative path they refer to, and clock
times are truncated to the date. The same truncation is applied to the evaluation
time (評価日時) in the Markdown summaries. This `README.md` is a note added for the artifact.
`SHA256SUMS` lists the SHA-256 of every file here
(`cd results/paper && sha256sum -c SHA256SUMS`). Nothing in this artifact
regenerates these files; re-running the evaluation scripts writes fresh output
under `output/` instead.

| Directory | Produced by | Content |
|---|---|---|
| `exp1/` | `evaluate_full_pipeline.py` (run `final545_lowload`) | Experiment 1, OAEI Conference, CQA population of 545 queries. Pinned re-run of the code in this artifact. |
| `manual90/` | `evaluate_relaxation_test.py --all` (run dated 2026-09-12) | Manual 90 set: 10 hand-crafted relaxation queries for each of 9 pairs. |
| `ablation_noL1/` | `evaluate_full_pipeline.py --all --query-list data/populations/cqa_l1_recovered_19.txt --phases L2,L3,L4a,L4b,L5` (run `ablation_noL1_cqa19`, 2026-09-12) | Proposition 1 check: the 19 CQA queries credited to L1, re-run with L1 disabled. |
| `ablation_noL1_manual90/` | `evaluate_relaxation_test.py --all --phases L2,L3,L4a,L4b,L5` (run `manual90_noL1`, 2026-09-12) | Proposition 1 check on the Manual 90 set. |
| `table1/` | failure-classification analysis (script not included; files dated 2026-01-18) | Classification of 70 failing queries into failure patterns (Table 1). 15 of the 70 rows belong to pairs whose data are not part of this artifact (agro-dbpedia: 5, gbo-gmo: 10), so this table cannot be regenerated from the artifact. |

Column names, log messages and the Markdown summaries are partly in Japanese
(the language used during development).
