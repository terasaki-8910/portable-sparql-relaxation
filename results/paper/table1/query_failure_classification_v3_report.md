# 失敗クエリ分類レポート v2（複数パターン分類対応版）

生成日時: 2026年1月18日

## 1. 全体サマリー

**総クエリ数**: 70件
- **input_count > 0**: 53件（変換評価可能）
- **input_count = 0**: 17件（元クエリで結果なし）

## 2. Primary Category 分布

### 2.1 全71クエリ

| Category | 名称 | 件数 | 割合 |
|----------|------|------|------|
| A | システムエラー | 8 | 11.4% |
| B | 変換システム不整合 | 4 | 5.7% |
| C | 部分的語彙欠損 | 43 | 61.4% |
| D | 制約不整合 | 0 | 0.0% |
| E | 複合トリプル不整合 | 2 | 2.9% |
| F | 概念階層不整合 | 1 | 1.4% |
| G | 述語不整合 | 12 | 17.1% |
| H | 構造不整合 | 0 | 0.0% |
| **合計** | - | **70** | **100.0%** |

### 2.2 input_count > 0 のクエリ（53件）

| Category | 名称 | 件数 | 割合 |
|----------|------|------|------|
| A | システムエラー | 8 | 15.1% |
| B | 変換システム不整合 | 4 | 7.5% |
| C | 部分的語彙欠損 | 26 | 49.1% |
| D | 制約不整合 | 0 | 0.0% |
| E | 複合トリプル不整合 | 2 | 3.8% |
| F | 概念階層不整合 | 1 | 1.9% |
| G | 述語不整合 | 12 | 22.6% |
| H | 構造不整合 | 0 | 0.0% |
| **合計** | - | **53** | **100.0%** |

## 3. 複数パターン分類統計（重複カウント）

各クエリに該当するすべてのパターン（C,D,E,F）を重複カウント。
Pattern A, B は終了パターンのため、複数分類の対象外。

### 3.1 パターン別該当件数（全71クエリ）

| Pattern | 名称 | 該当件数 | 割合 |
|---------|------|----------|------|
| C | 部分的語彙欠損 | 43 | 61.4% |
| D | 制約不整合 | 8 | 11.4% |
| E | 複合トリプル不整合 | 45 | 64.3% |
| F | 概念階層不整合 | 44 | 62.9% |
| G | 述語不整合 | 12 | 17.1% |

### 3.2 パターン別該当件数（input_count > 0 のクエリ）

| Pattern | 名称 | 該当件数 | 割合 |
|---------|------|----------|------|
| C | 部分的語彙欠損 | 26 | 49.1% |
| D | 制約不整合 | 1 | 1.9% |
| E | 複合トリプル不整合 | 28 | 52.8% |
| F | 概念階層不整合 | 28 | 52.8% |
| G | 述語不整合 | 12 | 22.6% |

### 3.3 all_categories パターン分布

複数パターンの組み合わせ分布:

| パターン組み合わせ | 件数 |
|-------------------|------|
| C;E;F | 34 |
| (なし: A or B) | 12 |
| G | 12 |
| C;D;E;F | 8 |
| F | 1 |
| E | 1 |
| E;F | 1 |
| C;E | 1 |

## 4. 複数パターン該当クエリ詳細

**複数パターン該当クエリ数**: 44件

| ペア | クエリ | input_count | primary | all_categories | トリプル数 |
|------|--------|-------------|---------|----------------|------------|
| agro-dbpedia | query_1.sparql | 0 | C | C;D;E;F | 5 |
| agro-dbpedia | query_2.sparql | 0 | C | C;D;E;F | 4 |
| agro-dbpedia | query_3.sparql | 0 | C | C;D;E;F | 6 |
| agro-dbpedia | query_4.sparql | 0 | C | C;D;E;F | 6 |
| agro-dbpedia | query_5.sparql | 0 | C | C;D;E;F | 5 |
| cmt-confOf | q_30.sparql | 4357 | C | C;E;F | 2 |
| cmt-conference | q_19.sparql | 1248 | C | C;E;F | 2 |
| cmt-conference | q_29.sparql | 1248 | C | C;E;F | 2 |
| cmt-conference | q_30.sparql | 4357 | C | C;E;F | 2 |
| cmt-conference | query_11.sparql | 6 | C | C;E;F | 4 |
| cmt-conference | query_12.sparql | 4300 | C | C;E;F | 3 |
| cmt-conference | query_15.sparql | 953 | C | C;E;F | 4 |
| cmt-conference | query_16.sparql | 1406 | C | C;E;F | 4 |
| cmt-conference | query_17.sparql | 10000 | C | C;E;F | 2 |
| cmt-conference | query_24.sparql | 0 | C | C;D;E;F | 3 |
| cmt-conference | query_25.sparql | 0 | C | C;E;F | 2 |
| cmt-conference | query_3.sparql | 4300 | C | C;E;F | 3 |
| cmt-conference | query_30.sparql | 0 | C | C;E;F | 3 |
| cmt-conference | query_4.sparql | 953 | C | C;E;F | 2 |
| cmt-conference | query_5.sparql | 2150 | C | C;E;F | 5 |
| cmt-conference | query_6.sparql | 10000 | C | C;E;F | 3 |
| cmt-conference | query_7.sparql | 6 | C | C;E;F | 7 |
| cmt-conference | query_9.sparql | 0 | C | C;E;F | 2 |
| conference-cmt | q_2.sparql | 10000 | C | C;E;F | 2 |
| conference-cmt | q_58.sparql | 10000 | C | C;E;F | 3 |
| conference-edas | q_2.sparql | 10000 | C | C;E;F | 2 |
| conference-edas | q_58.sparql | 10000 | C | C;E;F | 2 |
| conference-ekaw | q_59.sparql | 10000 | C | C;E;F | 2 |
| edas-cmt | q_30.sparql | 10000 | C | C;E;F | 2 |
| ekaw-cmt | q_11.sparql | 10000 | C | C;E;F | 3 |
| ekaw-cmt | q_51.sparql | 10000 | C | C;E;F | 3 |
| ekaw-cmt | q_52.sparql | 10000 | C | C;E;F | 2 |
| ekaw-confOf | q_61.sparql | 8 | E | E;F | 2 |
| ekaw-conference | q_25.sparql | 989 | C | C;E;F | 2 |
| gbo-gmo | query_1.sparql | 0 | C | C;E;F | 4 |
| gbo-gmo | query_10.sparql | 0 | C | C;E | 7 |
| gbo-gmo | query_11.sparql | 0 | C | C;E;F | 3 |
| gbo-gmo | query_12.sparql | 0 | C | C;E;F | 4 |
| gbo-gmo | query_13.sparql | 0 | C | C;E;F | 3 |
| gbo-gmo | query_14.sparql | 5 | C | C;E;F | 4 |
| gbo-gmo | query_17.sparql | 0 | C | C;E;F | 3 |
| gbo-gmo | query_2.sparql | 1 | C | C;D;E;F | 4 |
| gbo-gmo | query_5.sparql | 0 | C | C;E;F | 4 |
| gbo-gmo | query_7.sparql | 0 | C | C;D;E;F | 3 |

## 5. ペア別統計（Primary Category）

| ペア名 | A | B | C | D | E | F | G | H | 合計 |
|--------|---|---|---|---|---|---|---|---|------|
| agro-dbpedia | 0 | 0 | 5 | 0 | 0 | 0 | 0 | 0 | 5 |
| cmt-confOf | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| cmt-conference | 0 | 0 | 17 | 0 | 0 | 0 | 0 | 0 | 17 |
| cmt-ekaw | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| confOf-cmt | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| confOf-conference | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| confOf-edas | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| confOf-ekaw | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| conference-cmt | 2 | 1 | 2 | 0 | 0 | 0 | 0 | 0 | 5 |
| conference-confOf | 0 | 1 | 0 | 0 | 0 | 0 | 2 | 0 | 3 |
| conference-edas | 0 | 0 | 2 | 0 | 0 | 1 | 0 | 0 | 3 |
| conference-ekaw | 0 | 0 | 1 | 0 | 0 | 0 | 2 | 0 | 3 |
| edas-cmt | 2 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 4 |
| edas-conference | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 |
| edas-ekaw | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 2 |
| ekaw-cmt | 2 | 1 | 3 | 0 | 0 | 0 | 0 | 0 | 6 |
| ekaw-confOf | 0 | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 2 |
| ekaw-conference | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 2 |
| ekaw-edas | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| gbo-gmo | 0 | 0 | 10 | 0 | 0 | 0 | 0 | 0 | 10 |

## 6. カテゴリ別詳細

### Category A: システムエラー (8件)

| ペア | クエリ | input_count | all_categories | 理由 |
|------|--------|-------------|----------------|------|
| cmt-ekaw | q_1.sparql | 1245 | - | WHERE句が空 |
| conference-cmt | q_47.sparql | 1406 | - | WHERE句が空 |
| conference-cmt | q_7.sparql | 953 | - | WHERE句が空 |
| edas-cmt | q_1.sparql | 953 | - | WHERE句が空 |
| edas-cmt | q_31.sparql | 1406 | - | WHERE句が空 |
| edas-ekaw | q_34.sparql | 2847 | - | WHERE句が空 |
| ekaw-cmt | q_23.sparql | 1406 | - | WHERE句が空 |
| ekaw-cmt | q_42.sparql | 953 | - | WHERE句が空 |

### Category B: 変換システム不整合 (4件)

| ペア | クエリ | input_count | all_categories | 理由 |
|------|--------|-------------|----------------|------|
| conference-cmt | q_21.sparql | 2359 | - | 単一トリプルに残留URI: <http://conference#Submitt... |
| conference-confOf | q_25.sparql | 2359 | - | 単一トリプルに残留URI: <http://conference#Reviewe... |
| ekaw-cmt | q_44.sparql | 2359 | - | 単一トリプルに残留URI: <http://ekaw#Submitted_Pap... |
| ekaw-confOf | q_16.sparql | 2359 | - | 単一トリプルに残留URI: <http://ekaw#Evaluated_Pap... |

### Category C: 部分的語彙欠損 (43件)

| ペア | クエリ | input_count | all_categories | 理由 |
|------|--------|-------------|----------------|------|
| agro-dbpedia | query_1.sparql | 0 | C;D;E;F | 5トリプル中に残留URI: <http://ontology.irstea.fr... |
| agro-dbpedia | query_2.sparql | 0 | C;D;E;F | 4トリプル中に残留URI: <http://ontology.irstea.fr... |
| agro-dbpedia | query_3.sparql | 0 | C;D;E;F | 6トリプル中に残留URI: <http://ontology.irstea.fr... |
| agro-dbpedia | query_4.sparql | 0 | C;D;E;F | 6トリプル中に残留URI: <http://ontology.irstea.fr... |
| agro-dbpedia | query_5.sparql | 0 | C;D;E;F | 5トリプル中に残留URI: <http://ontology.irstea.fr... |
| cmt-confOf | q_30.sparql | 4357 | C;E;F | 2トリプル中に残留URI: <http://cmt#Conference> |
| cmt-conference | q_19.sparql | 1248 | C;E;F | 2トリプル中に残留URI: <http://cmt#ProgramCommitt... |
| cmt-conference | q_29.sparql | 1248 | C;E;F | 2トリプル中に残留URI: <http://cmt#ProgramCommitt... |
| cmt-conference | q_30.sparql | 4357 | C;E;F | 2トリプル中に残留URI: <http://cmt#Conference> |
| cmt-conference | query_11.sparql | 6 | C;E;F | 4トリプル中に残留URI: <http://cmt#>, cmt:Confere... |
| cmt-conference | query_12.sparql | 4300 | C;E;F | 3トリプル中に残留URI: cmt:title, <http://cmt#> |
| cmt-conference | query_15.sparql | 953 | C;E;F | 4トリプル中に残留URI: cmt:Acceptance, <http://cm... |
| cmt-conference | query_16.sparql | 1406 | C;E;F | 4トリプル中に残留URI: cmt:Rejection, <http://cmt... |
| cmt-conference | query_17.sparql | 10000 | C;E;F | 2トリプル中に残留URI: cmt:assignedTo, <http://cm... |
| cmt-conference | query_24.sparql | 0 | C;D;E;F | 3トリプル中に残留URI: cmt:maxPapers, <http://cmt... |
| cmt-conference | query_25.sparql | 0 | C;E;F | 2トリプル中に残留URI: cmt:acceptsHardcopySubmiss... |
| cmt-conference | query_3.sparql | 4300 | C;E;F | 3トリプル中に残留URI: cmt:title, <http://cmt#> |
| cmt-conference | query_30.sparql | 0 | C;E;F | 3トリプル中に残留URI: <http://cmt#> |
| cmt-conference | query_4.sparql | 953 | C;E;F | 2トリプル中に残留URI: cmt:Acceptance, <http://cm... |
| cmt-conference | query_5.sparql | 2150 | C;E;F | 5トリプル中に残留URI: <http://cmt#>, cmt:title, ... |
| ... | (他 23件) | ... | ... | ... |

### Category E: 複合トリプル不整合 (2件)

| ペア | クエリ | input_count | all_categories | 理由 |
|------|--------|-------------|----------------|------|
| edas-conference | q_37.sparql | 6 | E | 2トリプル、FILTER/残留URIなし（OPTIONAL化候補） |
| ekaw-confOf | q_61.sparql | 8 | E;F | 2トリプル、FILTER/残留URIなし（OPTIONAL化候補） |

### Category F: 概念階層不整合 (1件)

| ペア | クエリ | input_count | all_categories | 理由 |
|------|--------|-------------|----------------|------|
| conference-edas | q_1.sparql | 1620 | F | rdf:type制約: <http: |

### Category G: 述語不整合 (12件)

| ペア | クエリ | input_count | all_categories | 理由 |
|------|--------|-------------|----------------|------|
| confOf-cmt | q_36.sparql | 10000 | G | 1トリプル、残留URI/FILTER/rdf:typeなし |
| confOf-conference | q_36.sparql | 10000 | G | 1トリプル、残留URI/FILTER/rdf:typeなし |
| confOf-edas | q_36.sparql | 10000 | G | 1トリプル、残留URI/FILTER/rdf:typeなし |
| confOf-ekaw | q_42.sparql | 2606 | G | 1トリプル、残留URI/FILTER/rdf:typeなし |
| conference-confOf | q_11.sparql | 18 | G | 1トリプル、残留URI/FILTER/rdf:typeなし |
| conference-confOf | q_14.sparql | 1772 | G | 1トリプル、残留URI/FILTER/rdf:typeなし |
| conference-ekaw | q_11.sparql | 18 | G | 1トリプル、残留URI/FILTER/rdf:typeなし |
| conference-ekaw | q_14.sparql | 1772 | G | 1トリプル、残留URI/FILTER/rdf:typeなし |
| edas-cmt | q_16.sparql | 4244 | G | 1トリプル、残留URI/FILTER/rdf:typeなし |
| edas-ekaw | q_45.sparql | 10000 | G | 1トリプル、残留URI/FILTER/rdf:typeなし |
| ekaw-conference | q_11.sparql | 10000 | G | 1トリプル、残留URI/FILTER/rdf:typeなし |
| ekaw-edas | q_11.sparql | 10000 | G | 1トリプル、残留URI/FILTER/rdf:typeなし |

---

**レポート終了**
