# Portable SPARQL query relaxation

Code, data and frozen results for the paper

> Masato Hinooka and Mitsuharu Nagamori. *Toward Portable SPARQL Queries Across Linked Open Data: A Query Relaxation Approach to Cross-Dataset Rewriting.* In: Metadata and Semantic Research (MTSR 2026), Communications in Computer and Information Science, Springer. To appear.

The method rewrites a SPARQL query written for a source dataset into the vocabulary of a target dataset with an EDOAL alignment (strict rewriting). Only when the rewritten query returns no answer on the target does it run a cascade of relaxation phases (L1 to L5, see the name map below). Each phase generates candidate queries, and the one with the smallest non-zero result count below a threshold θ is kept and passed on. The repository contains the implementation (Python, with a small Apache Jena component for SPARQL parsing and serialisation), the OAEI Conference inputs of the evaluation (CQA-derived queries and the Manual 90 set), the frozen per-query results behind the tables, and `reproduce_tables.py`, which recomputes the tables and the numbers in the text from those results.

The repository was first shared anonymously for double-blind review. Its code and frozen results are unchanged since then; this README, `LICENSE` and `CITATION.cff` were updated for the published version of the paper.

## Contents

| Path | Role | Paper |
|---|---|---|
| `reproduce_tables.py` | recomputes Table 1 and Table 3 and the numbers in the text from the frozen results; `--check-paper` compares them with the printed values (standard library only; see [Claims](#claims) for which version of the paper it checks) | Sect. 4, Sect. 6–8 |
| `evaluate_full_pipeline.py` | evaluation driver for the CQA-derived queries: strict rewriting, execution on the target data, relaxation, precision/recall/F1 against the source-side answers | Sect. 6.1, Sect. 6.2, Table 3 |
| `evaluate_relaxation_test.py` | Manual 90 driver (the hand-crafted queries in `queries/relaxation/`) | Sect. 6.1, Sect. 6.2, Table 3 |
| `sparql_translator/src/parser/edoal_parser_ruthless.py` | EDOAL parser (simple and complex correspondences: union, composition, inverse, restrictions) | Sect. 2 |
| `sparql_translator/src/rewriter/` | strict rewriting on the query AST (`sparql_rewriter_ruthless.py`, `ast_walker.py`) and AST-to-SPARQL serialisation (`ast_serializer.py`) | Sect. 2, Sect. 6.1 |
| `sparql_translator/src/parser/sparql_ast_parser.py`, `src/main/java/`, `build/libs/sparql-translator-complex-alignment.jar` | SPARQL ↔ JSON AST with Apache Jena ARQ 4.10.0: Python wrappers, Java sources, prebuilt jar | Sect. 6.1 |
| `sparql_translator/src/relaxer/cascading_relaxer.py` | the six relaxation phases and the cascade | Sect. 5, Table 2, Algorithm 1 |
| `sparql_translator/src/relaxer/ontology_hierarchy.py` | direct superclasses and superproperties read from `data/datasets/*.schema.owl` (the hierarchy used by L4a/L4b) | Sect. 5 |
| `modules/data_loader.py`, `modules/config_loader.py` | loads each pair's datasets into in-memory rdflib graphs and runs the queries (60 s timeout per query) | Sect. 6.1 |
| `test_dir/test_data_retrieval.py` | translates and executes every query file of a pair (called by `evaluate_full_pipeline.py`) | Sect. 6.2 |
| `modules/translator_adapter.py` | alternative rewriting driver; `evaluate_full_pipeline.py` only instantiates it (it checks that `lib/*.jar` exist) | – |
| `modules/alignment_filter.py` | alignment-coverage rule (`AlignmentFilter.has_alignment`) that reproduces the selection of the CQA-derived queries; not called by the entry scripts, since the population is fixed by `data/populations/cqa_545.txt` | Sect. 6.1 |
| `modules/rdfs_materializer.py` | optional `--rdfs-materialize` (RDFS rules 5, 7, 9, 11); not used for the frozen results | Sect. 7.1 |
| `baseline_compare_generate_all_pairs_results.py` | wrapper for the third-party baseline translator, which is not bundled (`baseline_*` columns) | not reported |
| `data/alignment/<pair>/` | 20 directed OAEI Conference pairs: `alignment/<pair>.edoal`, `queries/*.sparql` (1,067 files), `queries/relaxation/*.sparql` (Manual 90, 9 pairs), `alignment.json` | Sect. 6.1 |
| `data/datasets.tar.gz`, `data/datasets/` | Conference v3.0 populated datasets (8.6 MB compressed, 116.4 MB extracted by `scripts/setup_data.py`), OntoFarm ontologies (`*.schema.owl`), dataset registry | Sect. 6.1 |
| `data/populations/cqa_545.txt` | the 545 (pair, query) entries of the CQA evaluation population | Sect. 6.1 |
| `results/paper/` | frozen per-query results with `SHA256SUMS`; `results/paper/README.md` gives the provenance of each directory | Table 1, Table 3 |
| `scripts/setup_data.py`, `scripts/fetch_data.py` | extract and verify the datasets; optional download of the same files from the upstream repository | – |
| `build.gradle`, `settings.gradle`, `gradle.properties`, `gradlew`, `gradlew.bat`, `gradle/` | Gradle build (wrapper 9.2.0) | – |
| `lib/jena.jar`, `lib/arq.jar`, `lib/gson.jar` | third-party jars whose presence `modules/translator_adapter.py` checks; not on any class path | – |
| `LICENSE`, `LICENSES/`, `THIRD_PARTY_NOTICES.md` | licences and third-party notices | – |
| `CITATION.cff` | citation metadata for this repository and the paper | – |

Code comments, log messages and the Markdown summaries in `results/paper/` are partly in Japanese, the language used during development. The scripts and result files call the CQA evaluation "Experiment 1".

## Relaxation phases: paper names and code names

| Paper (Table 2) | Operation | `relaxation_phase` in the result CSVs | `--phases` key | Method in `sparql_translator/src/relaxer/cascading_relaxer.py` |
|---|---|---|---|---|
| L1 | delete every triple pattern that still contains a source-ontology URI; the candidate is rebuilt from the remaining patterns, so FILTER clauses and OPTIONAL blocks are dropped with them | `Phase1_ResidualDeletion` | `L1` | `_phase1_remove_residual_triples` (line 532) |
| L2 | remove all FILTER clauses | `Phase2_FilterRemoval` | `L2` | `_phase2_remove_filter` (line 781) |
| L3 | make one triple pattern, or a pair of them inside one OPTIONAL block, optional (first 20 candidates; projected variables are not excluded); candidates are rebuilt the same way, so FILTERs are dropped | `Phase3_Optionalization` | `L3` | `_phase3_optionalize_triples` (line 824) |
| L4a | replace a class by its direct superclass | `Phase4a_ClassHierarchy` | `L4a` | `_phase4a_class_hierarchy_relaxation` (line 884) |
| L4b | replace a property by its direct superproperty | `Phase4b_PropertyHierarchy` | `L4b` | `_phase4b_property_hierarchy_relaxation` (line 1068) |
| L5 | remove all `rdf:type` triple patterns | `Phase5_TypeRemoval` | `L5` | `_phase5_remove_rdf_type` (line 1184) |

Algorithm 1 corresponds to `CascadingRelaxer.relax_query` (line 244), which runs the phases in the order of the table and hands each phase's best candidate to the next, together with `_execute_phase` (line 438), which executes the candidates of one phase and keeps the smallest result count `n` with `0 < n < θ`. θ is the `max_results_threshold` argument of `relax_query`; its default is 100000 and no caller overrides it. An empty `relaxation_phase` means that no phase produced a non-empty result. The `--phases` option of `evaluate_full_pipeline.py` and `evaluate_relaxation_test.py` restricts the cascade to the listed phases (ablation); the frozen results use all phases. `evaluate_relaxation_test.py` rejects unknown phase keys, `evaluate_full_pipeline.py` does not: a typo there is ignored silently and the run then recovers nothing.

## Tested environment

- Windows 11. Python 3.10's `platform` module reports this system as `Windows 10`, and that is the value recorded in `run_config.json`.
- Python 3.10.6 with the pinned packages of `requirements.txt` (rdflib 7.1.3).
- JDK 21 (21.0.9 when the repository was assembled). The authors' classes in the prebuilt jar are byte-identical to `javac -g` output of `src/main/java` under that JDK.
- Gradle wrapper 9.2.0 (`gradle/wrapper/gradle-wrapper.properties`).
- The frozen results were produced on Windows: `results/paper/exp1/run_config.json` records the operating system; the older result files do not record it. The repository was assembled and smoke-tested on Windows only; it has not been run on macOS or Linux.
- Character encoding: the Python code decodes the output of the Java parser and serializer as UTF-8 (`errors='replace'`), while the Java side writes it in the JVM's platform stdout encoding (`stdout.encoding` = `MS932` on the machine on which the repository was assembled); typical macOS and Linux setups use UTF-8. Non-ASCII characters in a query body can therefore be rewritten differently on different platforms. No CQA-derived or Manual 90 query has non-ASCII characters outside `#` comment lines, which the parser drops.
- Query execution: each query against the in-memory graphs has a 60 s timeout (thread-based, so it applies on every platform). A query whose first execution on the target fails or times out is recorded with `initial_status` `error` or `timeout` and is not relaxed; timeouts depend on machine speed. In `results/paper/exp1/`, 5 of the 545 queries have such a status (timeout: 5).
- Memory: `per_pair_diagnostics` in `results/paper/exp1/run_config.json` records a resident set size of up to 15.1 GB for the evaluation process.

## Setup

```sh
python -m venv .venv
. .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/setup_data.py      # extracts data/datasets/*.ttl from data/datasets.tar.gz and checks SHA-256
# The CQA evaluation needs about 16 GB of free RAM: graphs accumulate across pairs in one
# process (the frozen run peaked at 15.1 GB). With less memory, run a few pairs per
# invocation. reproduce_tables.py needs almost none.
chmod +x gradlew                  # macOS/Linux, only if Gradle is used
```

`reproduce_tables.py` needs only Python (standard library). Everything else needs a Java 21 runtime:

- Install a JDK 21, set `JAVA_HOME` to it and put its `bin` directory first on `PATH`; `java -version` must report 21. The Python code starts `java` itself: on Windows it uses `C:\Program Files\Java\jdk-21\bin\java.exe` if that file exists and `java.exe` from `PATH` otherwise; on macOS and Linux it uses `java` from `PATH`. Gradle reads `JAVA_HOME`.
- The prebuilt jar `build/libs/sparql-translator-complex-alignment.jar` is used as is. Run `./gradlew build` (Windows: `gradlew.bat build`) only to rebuild it from `src/main/java`; the first Gradle run downloads Gradle 9.2.0 and the Maven Central dependencies.
- Network access is not needed for the CQA evaluation, the Manual 90 set or the data setup from the bundled archive. It is needed for Gradle and for `scripts/fetch_data.py`, which downloads the same datasets from the upstream repository and checks their SHA-256 instead of using the archive.

## Reproducing the results

Commands referred to as `R`, `E1` and `M90` in [Claims](#claims):

### `R`: recompute the tables from the frozen results

```sh
python reproduce_tables.py --check-paper
```

Without input arguments the script reads the frozen files listed below. It prints the tables, the numbers used in the text and a set of definition cross-checks, and then, with `--check-paper`, one `PASS`/`FAIL` line per checked number (exit status 1 if any number differs). The definitions it applies (population, strict success, recovery, macro-averaged P/R/F1, half-up rounding) are documented at the top of the script. The script uses the table numbering of the version of the paper submitted for review: what it prints as Table 3 and Table 4 are the left and right halves of Table 3 in the published paper. Each part can be run on its own, and the paths can point to fresh output instead:

```sh
python reproduce_tables.py --check-paper \
    --table1-csv    results/paper/table1/query_failure_classification_v3.csv \
    --cqa-csv       results/paper/exp1/full_pipeline_results.csv \
    --cqa-allowlist data/populations/cqa_545.txt \
    --manual-csv    results/paper/manual90/relaxation_query_results.csv
```

| Part | Input options |
|---|---|
| T1 | `--table1-csv` |
| CQA | `--cqa-csv` and `--cqa-allowlist` |
| M90 | `--manual-csv` |

### `E1`: OAEI Conference, 545 CQA-derived queries

```sh
python evaluate_full_pipeline.py \
    cmt-confOf cmt-conference cmt-edas cmt-ekaw confOf-cmt \
    confOf-conference confOf-edas confOf-ekaw conference-cmt conference-confOf \
    conference-edas edas-cmt edas-confOf edas-conference edas-ekaw \
    ekaw-cmt ekaw-confOf ekaw-conference ekaw-edas \
    --query-list data/populations/cqa_545.txt --config-name cqa_545
```

Output goes to `output/runs/<timestamp>_cqa_545/` (`full_pipeline_results.csv`, `relaxation_phase_analysis.csv`, `FULL_PIPELINE_SUMMARY.md`, `run_config.json`, per-pair checkpoints in `pairs/`); compare with `results/paper/exp1/`, for example with `python reproduce_tables.py --cqa-csv output/runs/<run>/full_pipeline_results.csv --cqa-allowlist data/populations/cqa_545.txt`. `results/paper/exp1/` comes from the run `final545_lowload` started 2026-09-12. When the repository was assembled, all 31 shipped code files were compared with the development commit recorded in the `run_config.json` of that run (the commit id is not included in the shipped copy) and found identical apart from line endings. Afterwards, comments, docstrings and command-line help texts in five of them were edited to remove internal development notes (task labels, dates and references to internal documents); an AST comparison confirms that no code changed.

- The pair names are required: without them (and without `--all`) the script evaluates `cmt-conference` only.
- For each side of a pair, `<ontology>_100.ttl`, `<ontology>_eswc.ttl` and `<ontology>.schema.owl` are loaded into one in-memory rdflib graph, as listed in the pair's `alignment.json`.
- The script re-executes itself with `PYTHONHASHSEED=0` and evaluates pairs sequentially (`--workers 1`, the default; `--query-list` cannot be combined with parallel workers); the rows are written in (pair, query) order.
- For every listed pair, all of its query files are first translated and executed by `DataRetrievalTester.test_pair`; `--query-list` is applied afterwards, so run time grows with the pair's full query set.
- The population covers 19 of the 20 directed pairs; it has no entries for `conference-ekaw`, so the command does not list it.
- An interrupted run can be continued with `--resume output/runs/<run directory>`; completed pairs are read from `pairs/`.
- The `baseline_*` columns need the third-party baseline translator, which is not bundled. Without it the script prints a warning, `baseline_error` reads `Baseline not available` and the other `baseline_*` columns keep their default values (zero / `False`); the columns of the proposed method are unaffected.

### `M90`: Manual 90 set

```sh
python evaluate_relaxation_test.py --all
```

Evaluates `data/alignment/<pair>/queries/relaxation/*.sparql` for 9 pairs (cmt-confOf, cmt-conference, cmt-edas, cmt-ekaw, confOf-cmt, confOf-conference, conference-confOf, conference-edas, conference-ekaw; the script evaluates the pairs that have a `queries/relaxation/` directory, which is 9 of the 20; its `EXCLUDED_PAIRS` list names five further pairs, none of which has such a directory here; without `--all` or pair names it evaluates `cmt-conference` only). Output goes to `output/relaxation_test/` (`relaxation_query_results.csv`, `RELAXATION_QUERY_SUMMARY.md`, `run_config.json`). For each ontology the script loads the first existing file among `<ontology>_eswc.ttl`, `<ontology>_100.ttl`, … (`load_dataset_priority`); with the shipped data this is `<ontology>_eswc.ttl`. `results/paper/manual90/` comes from a run dated 2026-09-12, checked against the code in the same way as `results/paper/exp1/`.

### Recorded runtimes

Only times recorded in files of this repository are given; nothing here is an estimate.

- CQA evaluation (`results/paper/exp1/run_config.json`): per-pair wall-clock times of 21 pairs sum to 5,395 s (from 1 s for `gbo-gmo` to 1,182 s for `cmt-edas`). Each pair's time covers translating and executing all of its query files and evaluating and relaxing the listed ones. `wall_clock_sec_total` is 1742.51 s because the run was interrupted by an out-of-memory condition and resumed from its per-pair checkpoints: that field covers the second invocation only, while the per-pair times cover the whole run. Two of the 21 pairs (`gbo-gmo`, `conference-ekaw`) contribute no evaluated query.
- Manual 90 (`results/paper/manual90/`): 330.0 s for 90 queries.
- The recorded files do not describe the hardware beyond the operating system.

## Claims

Each row maps a table, figure or group of numbers in the published paper to the frozen file it comes from (paths under `results/paper/` unless given in full), the command that produced that file (`E1`, `M90`) and how it is checked. "`R`" means that `reproduce_tables.py --check-paper` checks the printed values; "computed" means that the value was recomputed from the frozen file when this README was written, outside `R`.

| Paper item | Printed values | Frozen file | Produced by → checked by |
|---|---|---|---|
| Table 1 (Sect. 4) | n = 53; A 8 (15.1%), B 4 (7.5%), C 26 (49.1%), D 0 (0.0%), E 2 (3.8%), F 1 (1.9%), G 12 (22.6%), H 0 (0.0%) | `table1/query_failure_classification_v3.csv` | manual classification (script not included) → `R` (T1) |
| Fig. 1 (Sect. 4, Sect. 5) | 4,300 answers on the source data; 5,966 answers after L1 | `exp1/full_pipeline_results.csv`, `cmt-conference/query_3.sparql` (`query_12.sparql` gives the same counts) | `E1` → computed |
| CQA population (Sect. 6.1) | 549 CQA-filtered queries, 4 with an empty source answer removed, n = 545 | `data/populations/cqa_545.txt` (its header lists the removed queries), `exp1/full_pipeline_results.csv` | `R` (CQA) checks n = 545; the other two values describe how the population was built |
| Table 3, left half (Sect. 6.2) | CQA: non-empty 471 → 493, initially failing 69, recovered 22, recovery rate 31.9%, mean F<sub>1</sub> of recovered 0.477, timeout 5. Manual: 2 → 82, 88, 80, 90.9%, 0.776, 0 | `exp1/full_pipeline_results.csv` + `data/populations/cqa_545.txt`; `manual90/relaxation_query_results.csv` | `E1`, `M90` → `R` (CQA, M90); `R` prints the two rates to two decimals (31.88%, 90.91%) |
| Table 3, right half (Sect. 6.2, Sect. 7) | CQA / Manual: L1 19 (0.454) / 42 (0.747), L2 0 / 32 (0.907), L3 2 (0.691) / 5 (0.154), L4a 1 (0.482) / 1 (0.891), L4b 0 / 0, L5 0 / 0 | as above | `E1`, `M90` → `R` (CQA, M90) |
| Sect. 6.2 text | non-empty rate 86.4% → 90.5%; mean F<sub>1</sub> 0.676 → 0.696; precision 0.741 → 0.768; recall 0.731 → 0.751; queries answered without relaxation F<sub>1</sub> 0.783 | `exp1/full_pipeline_results.csv` | `E1` → `R` (CQA; it prints precision and recall as percentages) |
| Sect. 6.2 text | recovered vs. answered without relaxation: recall 0.492 vs. 0.846, precision 0.680 vs. 0.857 | `exp1/full_pipeline_results.csv` | `E1` → computed |
| Sect. 6.2 text | of the 19 CQA recoveries credited to L1, 14 delete a class restriction copied from a complex correspondence and 5 a pattern with a source property without correspondence | `exp1/full_pipeline_results.csv` (`custom_output_query`) | manual analysis of the 19 rewritten queries (not automated) |
| Sect. 6.2 text | with L1 disabled, L3 recovers 18 of the 19 with the same result count and F<sub>1</sub> | `ablation_noL1/` | see [Proposition 1 check](#proposition-1-check-l1-disabled) |
| Sect. 6.2 text | 2 of the 42 Manual L1 recoveries also depend on dropping the FILTERs (`confOf-conference/relaxation_1.sparql`, `relaxation_10.sparql`) | `manual90/relaxation_query_results.csv` | manual analysis (not automated) |
| Sect. 6.2 text | three failing rewritings contain UNION (1 CQA, 2 Manual), and no phase recovers them | `exp1/full_pipeline_results.csv`, `manual90/relaxation_query_results.csv` | `E1`, `M90` → computed |
| Sect. 7.1 | recoveries per targeted cause: 19, 2 and 1 of 22 (CQA); 42, 37 and 1 of 80 (Manual) | as for Table 3 | sums of Table 3 rows; `R` prints them as percentages |
| Sect. 7.1 | materializing RDFS entailment before execution leaves every recovery unchanged | – | the run behind this statement is not part of `results/paper/`; it can be repeated with `--rdfs-materialize` |
| Fig. 3 (Sect. 7.2) | after L3, 619 rows, 58 of them matching a source answer, F<sub>1</sub> = 0.171 | `manual90/relaxation_query_results.csv`, `confOf-conference/relaxation_5.sparql` | `M90` → computed |
| Wall-clock cost (Sect. 6.1) | 5,395 s for the 545 CQA queries (9.9 s per query), 330 s for the 90 manual queries (3.7 s per query) | `exp1/run_config.json`, `manual90/RELAXATION_QUERY_SUMMARY.md` | recorded by `E1` and `M90`; see [Recorded runtimes](#recorded-runtimes) |
| Table 2, Algorithm 1, L3 candidate cap, θ (Sect. 5, Sect. 7.3) | – | – | implementation, see the name map above |

`reproduce_tables.py --check-paper` compares 80 numbers with the values printed in the version of the paper submitted for review (September 2026); its line references (`l.NNN`) point into that version's LaTeX source. When this repository was assembled, all 80 matched (T1: 20, CQA: 34, M90: 26). The published version no longer prints some of them: C+G ≈ 72% and E+G 26.4% (Table 1), the F<sub>1</sub> of the L1 example (0.838), the shares of recoveries per phase and per cause (86.4%, 52.5%, 40.0%; 9.1%, 4.5%; 46.25%, 1.25%) and the non-empty rates of the Manual set (2.2%, 91.1%).

## Data provenance and licences

Details, versions and hashes are in `THIRD_PARTY_NOTICES.md`.

- Conference v3.0 populated datasets, the 20 EDOAL alignments and the 1,038 `q_*.sparql` source queries come from the upstream repository of the Conference v3.0 dataset (Thiéblin and Trojahn), under the GNU LGPL (text in `LICENSES/LGPL-2.1.txt`).
- The `*.schema.owl` files are the cmt, confOf, conference, edas and ekaw ontologies of the OntoFarm collection (schema only), as used in the OAEI Conference track.
- The 29 `query_*.sparql` files and the Manual 90 queries were written by the authors (MIT).
- The prebuilt jar bundles Apache Jena, Gson, SLF4J and their dependencies under their own licences; `lib/*.jar` and the Gradle wrapper are Apache-2.0.
- The baseline translator of Thiéblin et al. (an extension of the INRIA Alignment API, LGPL) is not redistributed. To fill the `baseline_*` columns, place `SparqlTranslator.jar` and its `lib/` folder in `baseline/thieblin-sparql-translator/jar utiles/`.

## Known limitations

- No RDFS inference is applied in the runs behind the frozen results (`rdfs_inference: false` in `run_config.json`). rdflib evaluates the queries under simple entailment: the `rdfs:subClassOf` and `rdfs:subPropertyOf` triples of the ontologies are loaded as data but not used to derive new triples, and L4a/L4b take direct superclasses and superproperties from an XML reading of `*.schema.owl`. The optional `--rdfs-materialize` flag (rules rdfs5, rdfs7, rdfs9, rdfs11) was not used for the frozen results.
- θ is the default `max_results_threshold` of `relax_query`, 100000, in every run; a candidate is kept only if `0 < n < θ`. L3 generates at most 20 candidates.
- The comparison baseline is not bundled, so in a re-run `baseline_error` reads `Baseline not available` and the other `baseline_*` columns keep default values; the paper does not report baseline numbers.
- Relaxation is triggered only when the first execution of the rewritten query succeeds with zero results; queries that fail or time out are not relaxed.
- Table 1 cannot be regenerated: the classification script is not included, and 15 of the 70 rows of the frozen classification belong to pairs whose data are not part of this repository (agro-dbpedia: 5, gbo-gmo: 10). `reproduce_tables.py` recounts the frozen classification.
- In the `run_config.json` files under `results/paper/`, the development commit id reads "redacted for double-blind review". These files are kept byte for byte so that `results/paper/SHA256SUMS` holds.

Every `alignment.json` still names an `expected_output/` directory. Those files
are not part of this repository and no script needs them; the per-pair log then
reads `期待出力: なし` (no expected output).

## Proposition 1 check (L1 disabled)

The paper states that deleting an unmatched triple pattern and making it OPTIONAL
return the same answers, so L1's candidate coincides with one of L3's. The check:

```
python evaluate_full_pipeline.py --all \
    --query-list data/populations/cqa_l1_recovered_19.txt \
    --phases L2,L3,L4a,L4b,L5 --config-name ablation_noL1
python evaluate_relaxation_test.py --all --phases L2,L3,L4a,L4b,L5 \
    --output output/runs/ablation_noL1_manual90 --config-name ablation_noL1_manual90
```

Recorded outcome (`results/paper/ablation_noL1/`, `results/paper/ablation_noL1_manual90/`):
L3 recovers 18 of the 19 CQA queries credited to L1, each with the same result
count and F1. The miss, `cmt-conference/query_7.sparql`, has three unmatched
patterns, and L3 makes at most two optional at once.

On the manual set, 41 of 42 are recovered and 34 of those are identical; the
other 7 differ because L3's minimum-count rule prefers a pair candidate that
also makes a matched pattern optional. The one that is not recovered,
`confOf-conference/relaxation_10.sparql`, needs the unmatched pattern and a
FILTER dropped together: L2 removes the FILTER but keeps the unmatched pattern,
L3 makes the pattern optional but keeps the FILTER, whose `strstarts` test no
target URI satisfies, and only L1 drops both.

## Citation

If you use this code or data, please cite the paper. `CITATION.cff` holds the same information in machine-readable form.

```bibtex
@inproceedings{hinooka2026portable,
  author    = {Hinooka, Masato and Nagamori, Mitsuharu},
  title     = {Toward Portable {SPARQL} Queries Across Linked Open Data: A Query
               Relaxation Approach to Cross-Dataset Rewriting},
  booktitle = {Metadata and Semantic Research (MTSR 2026)},
  series    = {Communications in Computer and Information Science},
  publisher = {Springer},
  note      = {To appear}
}
```

## Licence

The authors' code and files are released under the MIT licence (`LICENSE`). Third-party material keeps its own licence; see `THIRD_PARTY_NOTICES.md` and `LICENSES/`.

## Verifying file integrity

`data/SCHEMAS.sha256` covers the five `*.schema.owl` files and the dataset
registry (`cd data && sha256sum -c SCHEMAS.sha256`).

```sh
sha256sum -c data/DATASETS.sha256              # after scripts/setup_data.py
(cd results/paper && sha256sum -c SHA256SUMS)
```
