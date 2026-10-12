# 緩和クエリ評価レポート
**評価日時**: 2026年09月12日
**処理時間**: 5.5分 (330.0秒)
---
## 📊 全体統計
- **総クエリ数**: 90
- **ソース非空（データ取得成功）**: 90/90 (100.0%)
- **翻訳成功**: 90/90 (100.0%)
- **変換直後空（条件2）**: 88/90 (97.8%)
- **緩和適用**: 80/90
- **緩和成功（クエリ回復）**: 80/80 (100.0%)

### 🎯 3条件達成（成功ケース）
- **成功数**: 80/90 (88.9%)
- **平均Precision（適合率）**: 77.92%
- **平均Recall（再現率）**: 87.73%
- **平均F1**: 77.58%
- **平均情報損失率**: 12.27%

### 📈 Phase別統計
| Phase | 成功数 | 割合 | 平均F1 | 平均Precision | 平均Recall | 平均情報損失 |
|-------|--------|------|--------|---------------|------------|---------------|
| Phase1_ResidualDeletion | 42 | 52.5% | 74.7% | 77.0% | 82.6% | 17.4% |
| Phase2_FilterRemoval | 32 | 40.0% | 90.7% | 89.7% | 97.0% | 3.0% |
| Phase3_Optionalization | 5 | 6.2% | 15.4% | 9.3% | 69.1% | 30.9% |
| Phase4a_ClassHierarchy | 1 | 1.2% | 89.1% | 80.4% | 100.0% | 0.0% |

### ❌ エラー分類統計
| エラー種別 | 件数 | 割合 |
|------------|------|------|
| ソース空（データなし） | 0 | 0.0% |
| 翻訳失敗 | 0 | 0.0% |
| 変換直後非空（緩和不要だった） | 2 | 2.2% |
| 緩和失敗 | 8 | 8.9% |

---
## 📈 ペア別統計

### ペア別サマリー
| ペア名 | クエリ数 | 成功数 | 成功率 | 平均F1 | 平均Precision | 平均情報損失 |
|--------|----------|--------|--------|--------|---------------|---------------|
| cmt-confOf | 10 | 8 | 80% | 94.4% | 97.5% | 6.3% |
| cmt-conference | 10 | 9 | 90% | 61.7% | 86.6% | 40.4% |
| cmt-edas | 10 | 10 | 100% | 85.1% | 77.7% | 0.0% |
| cmt-ekaw | 10 | 10 | 100% | 83.5% | 83.1% | 10.0% |
| confOf-cmt | 10 | 9 | 90% | 64.8% | 65.7% | 31.2% |
| confOf-conference | 10 | 10 | 100% | 78.5% | 76.1% | 8.0% |
| conference-confOf | 10 | 10 | 100% | 88.4% | 82.8% | 2.0% |
| conference-edas | 10 | 5 | 50% | 67.2% | 60.2% | 17.4% |
| conference-ekaw | 10 | 9 | 90% | 69.2% | 65.0% | 0.0% |

### cmt-confOf
- **クエリ数**: 10
- **成功**: 8 (80.0%)
- **平均Precision**: 97.55%
- **平均Recall**: 93.68%
- **平均F1**: 94.44%
- **平均情報損失率**: 6.32%
- **Phase別内訳**: Phase1_ResidualDeletion: 5, Phase2_FilterRemoval: 3

### cmt-conference
- **クエリ数**: 10
- **成功**: 9 (90.0%)
- **平均Precision**: 86.64%
- **平均Recall**: 59.63%
- **平均F1**: 61.66%
- **平均情報損失率**: 40.37%
- **Phase別内訳**: Phase1_ResidualDeletion: 5, Phase2_FilterRemoval: 4

### cmt-edas
- **クエリ数**: 10
- **成功**: 10 (100.0%)
- **平均Precision**: 77.67%
- **平均Recall**: 100.00%
- **平均F1**: 85.06%
- **平均情報損失率**: 0.00%
- **Phase別内訳**: Phase1_ResidualDeletion: 6, Phase2_FilterRemoval: 4

### cmt-ekaw
- **クエリ数**: 10
- **成功**: 10 (100.0%)
- **平均Precision**: 83.10%
- **平均Recall**: 90.00%
- **平均F1**: 83.51%
- **平均情報損失率**: 10.00%
- **Phase別内訳**: Phase1_ResidualDeletion: 6, Phase2_FilterRemoval: 4

### confOf-cmt
- **クエリ数**: 10
- **成功**: 9 (90.0%)
- **平均Precision**: 65.66%
- **平均Recall**: 68.85%
- **平均F1**: 64.78%
- **平均情報損失率**: 31.15%
- **Phase別内訳**: Phase1_ResidualDeletion: 3, Phase2_FilterRemoval: 4, Phase3_Optionalization: 2

### confOf-conference
- **クエリ数**: 10
- **成功**: 10 (100.0%)
- **平均Precision**: 76.14%
- **平均Recall**: 92.00%
- **平均F1**: 78.46%
- **平均情報損失率**: 8.00%
- **Phase別内訳**: Phase1_ResidualDeletion: 7, Phase2_FilterRemoval: 2, Phase3_Optionalization: 1

### conference-confOf
- **クエリ数**: 10
- **成功**: 10 (100.0%)
- **平均Precision**: 82.76%
- **平均Recall**: 98.00%
- **平均F1**: 88.41%
- **平均情報損失率**: 2.00%
- **Phase別内訳**: Phase1_ResidualDeletion: 5, Phase2_FilterRemoval: 4, Phase4a_ClassHierarchy: 1

### conference-edas
- **クエリ数**: 10
- **成功**: 5 (50.0%)
- **平均Precision**: 60.17%
- **平均Recall**: 82.65%
- **平均F1**: 67.22%
- **平均情報損失率**: 17.35%
- **Phase別内訳**: Phase1_ResidualDeletion: 1, Phase2_FilterRemoval: 4

### conference-ekaw
- **クエリ数**: 10
- **成功**: 9 (90.0%)
- **平均Precision**: 64.99%
- **平均Recall**: 99.96%
- **平均F1**: 69.16%
- **平均情報損失率**: 0.04%
- **Phase別内訳**: Phase1_ResidualDeletion: 4, Phase2_FilterRemoval: 3, Phase3_Optionalization: 2
