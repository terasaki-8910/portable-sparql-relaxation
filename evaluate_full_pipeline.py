#!/usr/bin/env python3
"""
全体フロー評価プログラム（クエリ変換 + 緩和）

SPARQLクエリ変換と緩和の全体フローを評価し、
独自システムとBaselineを比較する統合評価プログラム。

【フロー】
1. ソースクエリをTranslatorAdapterで変換
2. 変換されたクエリでターゲットデータに対して実行
3. 結果が0件 → 失敗と判定
4. 失敗の場合、CascadingRelaxerで緩和クエリを生成
5. 緩和クエリでターゲットデータに対して再実行
6. 各Phase（Phase1～Phase6）の緩和を順次試行（再帰的）
7. 最初に成功したPhaseで終了（最小緩和の原則）

【使用方法】
# 全ペアを評価（自動検出）
python evaluate_full_pipeline.py --all

# 特定のペアのみ評価
python evaluate_full_pipeline.py cmt-conference

# 複数ペアを評価
python evaluate_full_pipeline.py cmt-conference conference-confOf gmo-gbo

# デバッグモード（各ペア最大20クエリ）
python evaluate_full_pipeline.py cmt-conference --max-queries 20
python evaluate_full_pipeline.py cmt-conference -n 20

# (pair,query_file) を明示指定して再現実行
python evaluate_full_pipeline.py cmt-confOf cmt-conference ... --query-list output/_query_allowlist_545.txt

【出力ファイル】
- output/full_pipeline_results.csv              : 全クエリの詳細結果
- output/full_pipeline_<ペア名>.json           : ペア別詳細（JSON）
- output/FULL_PIPELINE_SUMMARY.md               : 統計サマリー（Markdown）
- output/full_pipeline_no_relaxation.csv        : 緩和なしの評価CSV
- output/full_pipeline_relaxation_only.csv      : 緩和対象のみの評価CSV（カテゴリ付き）
- output/relaxation_phase_analysis.csv          : Phase別分析

【CSVカラム】
- pair_name, query_file, query_sha256            : 基本情報（sha256はinput_queryの内容ハッシュ）
- initial_status                                 : ターゲット初回実行の状態
                                                    ('empty_success'/'nonempty_success'/'timeout'/'error')
- custom_initial_tp/fp/fn/precision/recall/f1   : 独自システム初回（緩和前）
- custom_final_tp/fp/fn/precision/recall/f1     : 独自システム最終（緩和後）
- result_cap, cap_hit                            : 旧10000件打ち切り(撤廃済み)の診断列。
                                                    result_capは参照値、cap_hitは真の件数がそれを超えたか
- relaxation_attempted                           : トリガ発火有無（apply_relaxationが呼ばれたか）
- relaxation_applied                             : 緩和適用有無（発火後、実際にPhaseが採用されたか）
- relaxation_phase                               : 適用された緩和Phase
- baseline_tp/fp/fn/precision/recall/f1         : Baseline（緩和なし）
- f1_diff_initial, f1_diff_final                : F1差分（初回・最終）

【評価指標】
- 二値分類: TP/FP/FN, Precision, Recall, F1, F2, F0.5
- 翻訳成功率: 変換が成功したクエリの割合
- 初回成功率: 緩和なしで結果が得られたクエリの割合
- 緩和成功率: 緩和後に結果が得られたクエリの割合
- Phase別貢献度: 各Phaseで成功したクエリ数
"""


"""
TODO: クエリ変換システムを

"""
import os
import sys

# --- 決定性のため PYTHONHASHSEED=0 を固定して自身を再実行 ---
# rdflib の BNode 自動ラベルが Python のハッシュ乱数化に依存し、プロセス毎に
# 変わることで結果の安定ソートキーが非決定になる。
# その対策として本プロセスの環境変数に PYTHONHASHSEED=0 を設定し、自身を再実行する。
# グローバル環境や shell は変更しない（子プロセスの env のみ）。既に 0 なら再実行しない。
# Windows では os.execv のプロセス置換が不安定なため subprocess で親が待機する形にする。
if __name__ == "__main__" and os.environ.get("PYTHONHASHSEED") != "0":
    # __name__ ガード: ProcessPoolExecutor(spawn) がワーカーで本モジュールを再importする際
    # (__name__=='__mp_main__') に再実行が発火してフォークボム化するのを防ぐ。
    import subprocess as _subprocess
    _child_env = dict(os.environ)
    _child_env["PYTHONHASHSEED"] = "0"
    sys.exit(_subprocess.call([sys.executable] + sys.argv, env=_child_env))
# --- ここから下は PYTHONHASHSEED=0 が有効なプロセスで実行される ---

import re
import csv
import json
import time
import argparse
import logging
import hashlib
try:
    import psutil
except ImportError:
    psutil = None
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional, Any, Callable
from dataclasses import dataclass, field

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "sparql_translator"))

# 既存モジュールのインポート
from test_dir.test_data_retrieval import DataRetrievalTester
from modules.translator_adapter import TranslatorAdapter
from baseline_compare_generate_all_pairs_results import BaselineTranslator

# CascadingRelaxerのインポート
try:
    from sparql_translator.src.relaxer.cascading_relaxer import CascadingRelaxer
    RELAXER_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] CascadingRelaxer import failed: {e}")
    RELAXER_AVAILABLE = False

# ロギング設定
logging.basicConfig(level=logging.WARNING, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# CascadingRelaxerのログを抑制
logging.getLogger('sparql_translator.src.relaxer.cascading_relaxer').setLevel(logging.WARNING)
logging.getLogger('sparql_translator.src.relaxer.ontology_hierarchy').setLevel(logging.WARNING)


# =============================================================================
# データクラス定義
# =============================================================================

@dataclass
class BinaryMetrics:
    """二値分類メトリクス"""
    tp: int = 0
    fp: int = 0
    fn: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    f2_score: float = 0.0
    f0_5_score: float = 0.0
    
    @classmethod
    def calculate(cls, source_count: int, target_count: int, matched_count: int) -> 'BinaryMetrics':
        """TP/FP/FNから評価指標を計算"""
        tp = matched_count
        fn = source_count - matched_count
        fp = target_count - matched_count
        
        # ゼロ除算対策
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        f2 = 5 * precision * recall / (4 * precision + recall) if (4 * precision + recall) > 0 else 0.0
        f0_5 = 1.25 * precision * recall / (0.25 * precision + recall) if (0.25 * precision + recall) > 0 else 0.0
        
        return cls(
            tp=tp, fp=fp, fn=fn,
            precision=precision, recall=recall,
            f1_score=f1, f2_score=f2, f0_5_score=f0_5
        )


@dataclass
class QueryExecutionResult:
    """クエリ実行結果"""
    success: bool = False
    result_count: int = 0
    entities: List[str] = field(default_factory=list)
    error_message: str = ""
    query: str = ""
    # status は success/result_count からのみ導出可能な値を「呼び出し側が
    # execute_query を再読みしなくても」区別できるようCSVへ露出するための列。
    # 'empty_success'(真の0件) / 'nonempty_success' / 'timeout' / 'error'(それ以外の例外)。
    status: str = ""
    cap_hit: bool = False  # data_loader の旧10000件上限(撤廃済み)を、この呼び出しの真の件数が超えていたか


@dataclass
class RelaxationInfo:
    """緩和情報"""
    applied: bool = False
    # トリガ(evaluate_custom_system内 if initial_result.status=='empty_success' ...)が
    # 発火し apply_relaxation が実際に呼ばれたかどうか。applied=False だけでは
    # 「トリガ不発」と「発火したが全フェーズ失敗」を区別できなかった問題への対処。
    attempted: bool = False
    phase: str = ""
    original_query: str = ""
    relaxed_query: str = ""
    tried_phases: List[str] = field(default_factory=list)
    category: str = ""  # 失敗カテゴリ (A, B, C, D, E, F, G)
    primary_category: str = ""  # プライマリカテゴリ


@dataclass
class SystemResult:
    """システム評価結果"""
    translation_success: bool = False
    initial_metrics: BinaryMetrics = field(default_factory=BinaryMetrics)
    final_metrics: BinaryMetrics = field(default_factory=BinaryMetrics)
    initial_result_count: int = 0
    final_result_count: int = 0
    source_count: int = 0
    relaxation: RelaxationInfo = field(default_factory=RelaxationInfo)
    output_query: str = ""
    final_query: str = ""
    error_message: str = ""
    # ターゲット初回実行の状態（QueryExecutionResult.status のコピー）。
    # 'empty_success'/'nonempty_success'/'timeout'/'error' の4値。
    initial_status: str = ""
    source_cap_hit: bool = False
    initial_cap_hit: bool = False
    final_cap_hit: bool = False


@dataclass
class QueryComparisonResult:
    """クエリ比較結果（独自システム vs Baseline）"""
    pair_name: str
    query_file: str
    input_query: str = ""
    custom: SystemResult = field(default_factory=SystemResult)
    baseline: SystemResult = field(default_factory=SystemResult)
    
    def to_csv_row(self) -> dict:
        """CSV行に変換"""
        # 旧10000件上限の参照値。data_loader側は撤廃済みでこの値では
        # もう打ち切らない。cap_hit の判定にのみ使う診断用の定数（run全体で固定）。
        RESULT_CAP_REFERENCE = 10000
        return {
            'pair_name': self.pair_name,
            'query_file': self.query_file,
            'input_query': self.input_query,
            'query_sha256': hashlib.sha256(self.input_query.encode('utf-8')).hexdigest(),
            # 独自システム - 初回（緩和前）
            'custom_initial_source_count': self.custom.source_count,
            'custom_initial_result_count': self.custom.initial_result_count,
            # 'empty_success'(真の0件)/'nonempty_success'/'timeout'/'error' の4値。
            # relaxation_applied=False の原因を「トリガ不発」と「発火後全滅」に
            # 切り分けられなかった問題への対処。
            'initial_status': self.custom.initial_status,
            'custom_initial_tp': self.custom.initial_metrics.tp,
            'custom_initial_fp': self.custom.initial_metrics.fp,
            'custom_initial_fn': self.custom.initial_metrics.fn,
            'custom_initial_precision': f'{self.custom.initial_metrics.precision:.4f}',
            'custom_initial_recall': f'{self.custom.initial_metrics.recall:.4f}',
            'custom_initial_f1': f'{self.custom.initial_metrics.f1_score:.4f}',
            # 独自システム - 最終（緩和後）
            'custom_final_result_count': self.custom.final_result_count,
            'custom_final_tp': self.custom.final_metrics.tp,
            'custom_final_fp': self.custom.final_metrics.fp,
            'custom_final_fn': self.custom.final_metrics.fn,
            'custom_final_precision': f'{self.custom.final_metrics.precision:.4f}',
            'custom_final_recall': f'{self.custom.final_metrics.recall:.4f}',
            'custom_final_f1': f'{self.custom.final_metrics.f1_score:.4f}',
            'custom_final_f2': f'{self.custom.final_metrics.f2_score:.4f}',
            'custom_final_f0_5': f'{self.custom.final_metrics.f0_5_score:.4f}',
            # 上限診断（撤廃に伴い追加）: result_cap は打ち切りに使われていない
            # 参照値、cap_hit は source/initial/final のいずれかの真の件数がそれを超えたか。
            'result_cap': RESULT_CAP_REFERENCE,
            'cap_hit': bool(self.custom.source_cap_hit or self.custom.initial_cap_hit
                             or self.custom.final_cap_hit),
            # 緩和情報
            'relaxation_attempted': self.custom.relaxation.attempted,
            'relaxation_applied': self.custom.relaxation.applied,
            'relaxation_phase': self.custom.relaxation.phase,
            'relaxation_category': self.custom.relaxation.category,
            'relaxation_primary_category': self.custom.relaxation.primary_category,
            'custom_translation_success': self.custom.translation_success,
            # 独自クエリ
            'custom_output_query': self.custom.output_query,
            'custom_final_query': self.custom.final_query,
            # Baseline（緩和なし）
            'baseline_source_count': self.baseline.source_count,
            'baseline_result_count': self.baseline.final_result_count,
            'baseline_tp': self.baseline.final_metrics.tp,
            'baseline_fp': self.baseline.final_metrics.fp,
            'baseline_fn': self.baseline.final_metrics.fn,
            'baseline_precision': f'{self.baseline.final_metrics.precision:.4f}',
            'baseline_recall': f'{self.baseline.final_metrics.recall:.4f}',
            'baseline_f1': f'{self.baseline.final_metrics.f1_score:.4f}',
            'baseline_f2': f'{self.baseline.final_metrics.f2_score:.4f}',
            'baseline_f0_5': f'{self.baseline.final_metrics.f0_5_score:.4f}',
            'baseline_translation_success': self.baseline.translation_success,
            'baseline_output_query': self.baseline.output_query,
            # 差分
            'f1_diff_initial': f'{self.custom.initial_metrics.f1_score - self.baseline.final_metrics.f1_score:+.4f}',
            'f1_diff_final': f'{self.custom.final_metrics.f1_score - self.baseline.final_metrics.f1_score:+.4f}',
            # エラー
            'custom_error': self.custom.error_message,
            'baseline_error': self.baseline.error_message,
        }

    def to_checkpoint(self) -> dict:
        """フル精度のチェックポイント表現（bit-identical な再集計のため丸めない）。"""
        def sr(s: 'SystemResult') -> dict:
            def m(x):
                return {'tp': x.tp, 'fp': x.fp, 'fn': x.fn, 'precision': x.precision,
                        'recall': x.recall, 'f1_score': x.f1_score,
                        'f2_score': x.f2_score, 'f0_5_score': x.f0_5_score}
            return {
                'translation_success': s.translation_success,
                'initial_result_count': s.initial_result_count,
                'final_result_count': s.final_result_count,
                'source_count': s.source_count,
                'output_query': s.output_query,
                'final_query': s.final_query,
                'error_message': s.error_message,
                'initial_status': s.initial_status,
                'source_cap_hit': s.source_cap_hit,
                'initial_cap_hit': s.initial_cap_hit,
                'final_cap_hit': s.final_cap_hit,
                'initial_metrics': m(s.initial_metrics),
                'final_metrics': m(s.final_metrics),
                'relaxation': {
                    'applied': s.relaxation.applied,
                    'attempted': s.relaxation.attempted,
                    'phase': s.relaxation.phase,
                    'category': s.relaxation.category,
                    'primary_category': s.relaxation.primary_category,
                    'tried_phases': list(s.relaxation.tried_phases),
                },
            }
        return {
            'pair_name': self.pair_name,
            'query_file': self.query_file,
            'input_query': self.input_query,
            'custom': sr(self.custom),
            'baseline': sr(self.baseline),
        }

    @classmethod
    def from_checkpoint(cls, d: dict) -> 'QueryComparisonResult':
        """to_checkpoint() の逆。集計に必要な属性を完全復元（フル精度）。"""
        def mm(md: dict) -> 'BinaryMetrics':
            return BinaryMetrics(tp=md['tp'], fp=md['fp'], fn=md['fn'],
                                 precision=md['precision'], recall=md['recall'],
                                 f1_score=md['f1_score'], f2_score=md.get('f2_score', 0.0),
                                 f0_5_score=md.get('f0_5_score', 0.0))
        def sr(sd: dict) -> 'SystemResult':
            r = SystemResult()
            r.translation_success = sd['translation_success']
            r.initial_result_count = sd['initial_result_count']
            r.final_result_count = sd['final_result_count']
            r.source_count = sd['source_count']
            r.output_query = sd['output_query']
            r.final_query = sd['final_query']
            r.error_message = sd['error_message']
            r.initial_status = sd.get('initial_status', '')
            r.source_cap_hit = sd.get('source_cap_hit', False)
            r.initial_cap_hit = sd.get('initial_cap_hit', False)
            r.final_cap_hit = sd.get('final_cap_hit', False)
            r.initial_metrics = mm(sd['initial_metrics'])
            r.final_metrics = mm(sd['final_metrics'])
            rel = sd['relaxation']
            r.relaxation = RelaxationInfo(applied=rel['applied'],
                                          attempted=rel.get('attempted', False),
                                          phase=rel['phase'],
                                          category=rel['category'],
                                          primary_category=rel['primary_category'],
                                          tried_phases=list(rel.get('tried_phases', [])))
            return r
        obj = cls(pair_name=d['pair_name'], query_file=d['query_file'],
                  input_query=d.get('input_query', ''))
        obj.custom = sr(d['custom'])
        obj.baseline = sr(d['baseline'])
        return obj


# =============================================================================
# メイン評価クラス
# =============================================================================

class FullPipelineEvaluator:
    """全体フロー評価クラス"""
    
    def __init__(self, project_root: Path = None, enabled_phases: Optional[Set[str]] = None,
                rdfs_materialize: bool = False, query_allowlist: Optional[Set[Tuple[str, str]]] = None):
        # アブレーション用フェーズ選択（None=全フェーズ, 既定・従来と同一挙動）
        self.enabled_phases = enabled_phases
        # RDFS limited materialization フラグ（既定OFF・挙動不変）
        self.rdfs_materialize = rdfs_materialize
        # (pair_name, query_file) の許可リスト（None=全件, 既定・従来と同一挙動）。
        # クエリファイルがディスク上で後から増えても、特定の母集団（例: 論文Table3の549件）
        # だけを対象に再実行するための絞り込み。evaluate_pair 内でフィルタする。
        self.query_allowlist = query_allowlist
        if project_root is None:
            self.project_root = PROJECT_ROOT
        elif isinstance(project_root, str):
            self.project_root = Path(project_root).resolve()
        else:
            self.project_root = project_root
        self.tester = DataRetrievalTester(str(self.project_root), rdfs_materialize=rdfs_materialize)
        
        # TranslatorAdapterの初期化
        try:
            self.translator = TranslatorAdapter(str(self.project_root))
            self.translator_available = True
            print("[INFO] TranslatorAdapter を初期化しました")
        except Exception as e:
            print(f"[WARNING] TranslatorAdapter が利用不可: {e}")
            self.translator_available = False
            self.translator = None
        
        # Baseline翻訳機の初期化
        try:
            self.baseline_translator = BaselineTranslator()
            self.baseline_available = True
            print("[INFO] Baseline翻訳機を初期化しました")
        except FileNotFoundError as e:
            print(f"[WARNING] Baseline翻訳機が利用不可: {e}")
            self.baseline_available = False
            self.baseline_translator = None
        
        # CascadingRelaxerの初期化
        if RELAXER_AVAILABLE:
            try:
                self.relaxer = CascadingRelaxer()
                self.relaxer_available = True
                print("[INFO] CascadingRelaxer を初期化しました")
            except Exception as e:
                print(f"[WARNING] CascadingRelaxer が利用不可: {e}")
                self.relaxer_available = False
                self.relaxer = None
        else:
            self.relaxer_available = False
            self.relaxer = None
        
        # データソースキャッシュ
        self._source_cache = {}
        self._target_cache = {}
    
    def find_all_pairs(self, local_only: bool = True) -> List[str]:
        """全ての有効なペアを検出
        
        Args:
            local_only: Trueの場合、ローカルデータセットのみを使用するペアに限定
        """
        alignment_dir = self.project_root / 'data' / 'alignment'
        valid_pairs = []
        
        for pair_dir in sorted(alignment_dir.iterdir()):
            if pair_dir.is_dir():
                pair_name = pair_dir.name
                alignment_json = pair_dir / 'alignment.json'
                
                if alignment_json.exists():
                    # ローカルのみモードの場合、リモートエンドポイントを使用するペアをスキップ
                    if local_only:
                        try:
                            with open(alignment_json, 'r', encoding='utf-8') as f:
                                config = json.load(f)
                            has_endpoints = bool(config.get('target_endpoints')) or bool(config.get('source_endpoints')) or bool(config.get('endpoints'))
                            has_datasets = bool(config.get('source_datasets')) or bool(config.get('target_datasets')) or bool(config.get('datasets'))
                            
                            # エンドポイントのみでデータセットがない場合はスキップ
                            if has_endpoints and not has_datasets:
                                continue
                        except:
                            pass
                    
                    valid_pairs.append(pair_name)
        
        return valid_pairs
    
    def find_edoal_file(self, pair_name: str) -> Optional[Path]:
        """EDOALファイルを検索"""
        pair_dir = self.project_root / 'data' / 'alignment' / pair_name
        
        # alignment.jsonからパスを取得
        alignment_json = pair_dir / 'alignment.json'
        if alignment_json.exists():
            try:
                with open(alignment_json, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    edoal_path = config.get('alignment_file', '')
                    if edoal_path:
                        full_path = self.project_root / edoal_path
                        if full_path.exists():
                            return full_path
            except:
                pass
        
        # フォールバック: alignmentサブディレクトリを検索
        alignment_subdir = pair_dir / 'alignment'
        if alignment_subdir.exists():
            edoal_files = list(alignment_subdir.glob('*.edoal'))
            if edoal_files:
                return edoal_files[0]
        
        return None
    
    def extract_numeric_ids(self, uri: str) -> Set[str]:
        """URIから数値IDを抽出"""
        if '#' in uri:
            local_name = uri.split('#')[-1]
        elif '/' in uri:
            local_name = uri.split('/')[-1]
        else:
            local_name = uri
        
        numbers = re.findall(r'\d+', local_name)
        return set(numbers)
    
    def match_entities(self, source_entities: List[str], target_entities: List[str]) -> int:
        """エンティティをマッチングしてTP数を返す"""
        if not source_entities or not target_entities:
            return 0
        
        # ソースエンティティの数値IDをインデックス化
        source_id_map: Dict[str, List[str]] = {}
        for uri in source_entities:
            ids = self.extract_numeric_ids(uri)
            for num_id in ids:
                if num_id not in source_id_map:
                    source_id_map[num_id] = []
                source_id_map[num_id].append(uri)
        
        # マッチング
        matched_count = 0
        matched_source = set()
        
        for target_uri in target_entities:
            target_ids = self.extract_numeric_ids(target_uri)
            for num_id in target_ids:
                if num_id in source_id_map:
                    for source_uri in source_id_map[num_id]:
                        if source_uri not in matched_source:
                            matched_count += 1
                            matched_source.add(source_uri)
                            break
                    break
        
        return matched_count
    
    def execute_query(self, query: str, data_source) -> QueryExecutionResult:
        """クエリを実行"""
        result = QueryExecutionResult(query=query)

        try:
            results = data_source.query(query, timeout=60)

            if results is None:
                result.error_message = "Query returned None"
                result.status = 'error'
                return result

            result_list = list(results) if hasattr(results, '__iter__') else []
            result.result_count = len(result_list)
            result.success = True
            result.status = 'nonempty_success' if result.result_count > 0 else 'empty_success'
            # data_loader側の打ち切り撤廃に伴い、真の件数が旧上限(10000)を
            # 超えていたかをここで受け取る（打ち切り自体はしない・診断用）。
            result.cap_hit = bool(getattr(data_source, 'last_result_cap_hit', False))

            # エンティティURI抽出
            seen = set()
            for row in result_list:
                if isinstance(row, dict):
                    for value in row.values():
                        uri = str(value) if value else ''
                        if uri.startswith('http://') and uri not in seen:
                            seen.add(uri)
                            result.entities.append(uri)
                elif hasattr(row, 'asdict'):
                    for value in row.asdict().values():
                        uri = str(value) if value else ''
                        if uri.startswith('http://') and uri not in seen:
                            seen.add(uri)
                            result.entities.append(uri)
                elif hasattr(row, '__iter__'):
                    for value in row:
                        uri = str(value) if value else ''
                        if uri.startswith('http://') and uri not in seen:
                            seen.add(uri)
                            result.entities.append(uri)

        except TimeoutError as e:
            # data_loader._run_with_timeout が投げる TimeoutError を
            # 汎用 Exception と区別（初回0件のうち打ち切り由来と真の空集合を分離するため）。
            result.error_message = str(e)
            result.status = 'timeout'
        except Exception as e:
            result.error_message = str(e)
            result.status = 'error'

        return result
    
    def calculate_metrics(
        self, 
        source_entities: List[str], 
        target_entities: List[str]
    ) -> BinaryMetrics:
        """二値分類メトリクスを計算"""
        source_count = len(source_entities)
        target_count = len(target_entities)
        matched_count = self.match_entities(source_entities, target_entities)
        
        return BinaryMetrics.calculate(source_count, target_count, matched_count)
    
    def apply_relaxation(
        self, 
        query: str, 
        target_data_source,
        source_ont: str = None,
        target_ont: str = None
    ) -> Tuple[str, RelaxationInfo]:
        """クエリ緩和を適用"""
        relax_info = RelaxationInfo(original_query=query)
        # apply_relaxation の呼び出し自体（=トリガ発火）を記録。
        # 呼び出し元は evaluate_custom_system の1箇所のみで、そこでは既に
        # initial_result.status=='empty_success' かつ self.relaxer_available が
        # 確認済みのため、ここでは無条件にTrueとする。
        relax_info.attempted = True

        if not self.relaxer_available or not self.relaxer:
            return query, relax_info
        
        try:
            # executor関数を定義
            def executor(q: str) -> Dict[str, Any]:
                result = self.execute_query(q, target_data_source)
                return {
                    'success': result.success,
                    'count': result.result_count,
                    'error': result.error_message
                }
            
            # CascadingRelaxerで緩和（enabled_phases でアブレーション対象を制御）
            relax_result = self.relaxer.relax_query(
                query=query,
                source_ont=source_ont,
                target_ont=target_ont,
                executor=executor,
                enabled_phases=self.enabled_phases
            )
            
            if relax_result.success and relax_result.relaxed_query != query:
                relax_info.applied = True
                relax_info.phase = relax_result.phase
                relax_info.relaxed_query = relax_result.relaxed_query
                relax_info.tried_phases = relax_result.all_tried_phases
                return relax_result.relaxed_query, relax_info
            else:
                relax_info.tried_phases = relax_result.all_tried_phases if hasattr(relax_result, 'all_tried_phases') else []
                return query, relax_info
            
        except Exception as e:
            logger.warning(f"Relaxation failed: {e}")
            relax_info.error = str(e)
            return query, relax_info
    
    def evaluate_custom_system(
        self,
        input_query: str,
        output_query: str,  # 変換済みクエリ
        source_data_source,
        target_data_source,
        pair_name: str,
        translation_success: bool = True
    ) -> SystemResult:
        """
        独自システムを評価（緩和付き）
        
        Args:
            input_query: 入力クエリ
            output_query: 変換済みクエリ（test_pairで変換済み）
            source_data_source: ソースデータソース
            target_data_source: ターゲットデータソース
            pair_name: ペア名
            translation_success: 変換が成功したかどうか
        """
        result = SystemResult()
        
        try:
            # 変換済みのクエリを使用
            if not translation_success or not output_query:
                result.translation_success = False
                result.error_message = 'Translation failed or empty output'
                return result
            
            result.translation_success = True
            result.output_query = output_query
            
            # Step 1: ソースクエリ実行
            source_result = self.execute_query(input_query, source_data_source)
            result.source_count = source_result.result_count
            result.source_cap_hit = source_result.cap_hit

            # Step 2: 初回ターゲットクエリ実行
            initial_result = self.execute_query(output_query, target_data_source)
            result.initial_result_count = initial_result.result_count
            result.initial_status = initial_result.status
            result.initial_cap_hit = initial_result.cap_hit

            # 初回メトリクス計算
            result.initial_metrics = self.calculate_metrics(
                source_result.entities, initial_result.entities
            )

            # Step 3: 結果が0件の場合、緩和を試行
            final_query = output_query
            final_entities = initial_result.entities

            # 緩和は「クエリが成功して0件」のときだけ起動。
            # data_loader が rdflib 内部エラーを raise するようになったため、
            # エラー(success=False)で緩和が誤起動しないよう success を条件に追加。
            # (論理は不変。initial_result.status=='empty_success' は
            #  result_count==0 and success の別表現で、CSVでは status 列として露出する)
            if initial_result.result_count == 0 and initial_result.success and self.relaxer_available:
                # ペア名からソース・ターゲットオントロジーを推定
                parts = pair_name.split('-')
                source_ont = parts[0] if len(parts) >= 2 else None
                target_ont = parts[1] if len(parts) >= 2 else None

                final_query, relax_info = self.apply_relaxation(
                    output_query, target_data_source, source_ont, target_ont
                )
                result.relaxation = relax_info

                if relax_info.applied:
                    # 緩和後のクエリを実行
                    relaxed_result = self.execute_query(final_query, target_data_source)
                    result.final_result_count = relaxed_result.result_count
                    result.final_cap_hit = relaxed_result.cap_hit
                    final_entities = relaxed_result.entities
                else:
                    result.final_result_count = initial_result.result_count
                    result.final_cap_hit = initial_result.cap_hit
            else:
                result.final_result_count = initial_result.result_count
                result.final_cap_hit = initial_result.cap_hit

            result.final_query = final_query
            
            # 最終メトリクス計算
            result.final_metrics = self.calculate_metrics(
                source_result.entities, final_entities
            )
            
        except Exception as e:
            result.error_message = str(e)
            logger.error(f"Custom system evaluation failed: {e}")
        
        return result
    
    def evaluate_baseline_system(
        self,
        input_query: str,
        source_data_source,
        target_data_source,
        edoal_file: Path
    ) -> SystemResult:
        """Baselineシステムを評価（緩和なし）"""
        result = SystemResult()
        
        if not self.baseline_available:
            result.error_message = 'Baseline not available'
            return result
        
        try:
            # Baselineで変換
            baseline_result = self.baseline_translator.translate(
                str(edoal_file), input_query, timeout=60
            )
            
            if not baseline_result.get('success', False):
                result.translation_success = False
                result.error_message = baseline_result.get('error', 'Translation failed')
                return result
            
            result.translation_success = True
            output_query = baseline_result.get('output_query', '')
            result.output_query = output_query
            result.final_query = output_query
            
            if not output_query:
                result.error_message = 'Empty output query'
                return result
            
            # WHERE句が空の場合は失敗
            where_match = re.search(r'WHERE\s*\{([^}]*)\}', output_query, re.IGNORECASE | re.DOTALL)
            if where_match:
                where_body = where_match.group(1).strip()
                if not where_body:
                    result.translation_success = False
                    result.error_message = 'Empty WHERE clause'
                    return result
            
            # ソースクエリ実行
            source_result = self.execute_query(input_query, source_data_source)
            result.source_count = source_result.result_count
            
            # ターゲットクエリ実行（緩和なし）
            target_result = self.execute_query(output_query, target_data_source)
            result.initial_result_count = target_result.result_count
            result.final_result_count = target_result.result_count
            
            # メトリクス計算
            metrics = self.calculate_metrics(source_result.entities, target_result.entities)
            result.initial_metrics = metrics
            result.final_metrics = metrics
            
        except Exception as e:
            result.error_message = str(e)
            logger.error(f"Baseline evaluation failed: {e}")
        
        return result
    
    def evaluate_query(
        self,
        pair_name: str,
        query_result: dict,
        source_data_source,
        target_data_source,
        edoal_file: Path
    ) -> QueryComparisonResult:
        """1クエリを評価"""
        comparison = QueryComparisonResult(
            pair_name=pair_name,
            query_file=query_result.get('query_file', 'unknown'),
            input_query=query_result.get('input_query', '')
        )
        
        input_query = query_result.get('input_query', '')
        output_query = query_result.get('output_query', '')  # test_pairで変換済み
        translation_success = query_result.get('translation_success', False)
        
        if not input_query:
            comparison.custom.error_message = 'Missing input query'
            comparison.baseline.error_message = 'Missing input query'
            return comparison
        
        # 独自システム評価（変換済みクエリを使用、緩和付き）
        comparison.custom = self.evaluate_custom_system(
            input_query, output_query,
            source_data_source, target_data_source,
            pair_name, translation_success
        )
        
        # Baseline評価（緩和なし）
        comparison.baseline = self.evaluate_baseline_system(
            input_query, source_data_source, target_data_source, edoal_file
        )
        
        return comparison
    
    def load_pair_data(self, pair_name: str, max_queries: int = None) -> dict:
        """
        ペアのデータソースとクエリを読み込み
        
        DataRetrievalTesterのtest_pairを利用して変換済みクエリを取得
        
        Args:
            pair_name: ペア名
            max_queries: 最大クエリ数（制限用）
        """
        import io
        import contextlib
        
        # test_pairの標準出力を抑制
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            pair_result = self.tester.test_pair(pair_name, limit=max_queries)
        
        if 'error' in pair_result:
            return {'error': pair_result['error']}
        
        # test_pair はデータソースを内部で使用するが結果に含めていない
        # data_loaderから再取得
        try:
            source_sources, target_sources = self.tester.data_loader.load_source_and_target_for_pair(pair_name)
        except Exception as e:
            return {'error': f'データソースのロードに失敗: {e}'}
        
        return {
            'pair_name': pair_name,
            'source_datasource': source_sources[0] if source_sources else None,
            'target_datasource': target_sources[0] if target_sources else None,
            'results': pair_result.get('results', [])
        }
    
    def evaluate_pair(self, pair_name: str, max_queries: int = None) -> List[QueryComparisonResult]:
        """1ペアを評価"""
        results = []
        
        print(f"\n{'='*80}")
        print(f"ペア: {pair_name}")
        print(f"{'='*80}")
        
        try:
            # EDOALファイル取得
            edoal_file = self.find_edoal_file(pair_name)
            if not edoal_file:
                print(f"[ERROR] EDOALファイルが見つかりません: {pair_name}")
                return results
            
            print(f"EDOALファイル: {edoal_file}")
            
            # データソースとクエリを読み込み（test_pairを使用、出力を抑制）
            pair_data = self.load_pair_data(pair_name, max_queries)
            
            if 'error' in pair_data:
                print(f"[ERROR] {pair_data['error']}")
                return results
            
            query_list = pair_data.get('results', [])

            if self.query_allowlist is not None:
                before = len(query_list)
                query_list = [q for q in query_list
                             if (pair_name, q.get('query_file', '')) in self.query_allowlist]
                print(f"[query-list] {pair_name}: {before}件 → {len(query_list)}件 に絞り込み")

            total_queries = len(query_list)
            if max_queries:
                print(f"クエリ数: {total_queries} (制限: {max_queries})")
            else:
                print(f"クエリ数: {total_queries}")
            
            # データソース取得
            source_ds = pair_data.get('source_datasource')
            target_ds = pair_data.get('target_datasource')
            
            if not source_ds or not target_ds:
                print("[ERROR] データソースが取得できません")
                return results
            
            # 各クエリを評価
            for i, query_info in enumerate(query_list):
                query_file = query_info.get('query_file', f'query_{i}')
                
                comparison = self.evaluate_query(
                    pair_name, query_info,
                    source_ds, target_ds, edoal_file
                )
                results.append(comparison)
                
                # 進捗表示（UTF-8でエンコードできない文字を避ける）
                # 緩和適用時は F1 > 0 で成功、未適用時は F1 > 0.5 で成功
                if comparison.custom.relaxation.applied:
                    status = "OK" if comparison.custom.final_metrics.f1_score > 0.0 else "NG"
                else:
                    status = "OK" if comparison.custom.final_metrics.f1_score > 0.5 else "NG"
                relaxed = " (relaxed)" if comparison.custom.relaxation.applied else ""
                print(f"[{i+1:3}/{total_queries}] {query_file:30} F1={comparison.custom.final_metrics.f1_score:.2f}{relaxed} {status}")
            
        except Exception as e:
            print(f"[ERROR] ペア評価失敗: {e}")
            logger.exception(e)
        
        return results
    
    def evaluate_all_pairs(self, pair_names: List[str] = None, max_queries: int = None,
                           run_dir: Path = None, resume: bool = False) -> List[QueryComparisonResult]:
        """全ペアを評価（ペア単位チェックポイント + --resume 対応）"""
        if pair_names is None:
            pair_names = self.find_all_pairs()

        print("=" * 80)
        print("全体フロー評価プログラム（クエリ変換 + 緩和）")
        print("=" * 80)
        print(f"対象ペア: {len(pair_names)}ペア")
        print(f"ペア一覧: {', '.join(pair_names)}")
        if max_queries:
            print(f"[デバッグ] 各ペア最大クエリ数: {max_queries}")
        print("=" * 80)

        all_results = []
        self.pair_times = {}          # ペア単位 wall-clock
        self.pair_diagnostics = {}    # ペア単位 診断（wall/RSS/query数）
        self.completed_pairs = []     # 完了ペア（順序保持）

        pairs_dir = None
        done = set()
        if run_dir is not None:
            pairs_dir = Path(run_dir) / 'pairs'
            pairs_dir.mkdir(parents=True, exist_ok=True)
            if resume:
                for pj in sorted(pairs_dir.glob('*.json')):
                    try:
                        with open(pj, encoding='utf-8') as f:
                            data = json.load(f)
                        pn = data['pair_name']
                        pair_objs = [QueryComparisonResult.from_checkpoint(row) for row in data['results']]
                        # A2（判断事項e対策）: 翻訳器全滅の汚染チェックポイントを resume で再計算する。
                        # クエリ>0 かつ翻訳成功0件 = Java翻訳器が死んだ汚染ペア → done扱いにせず再計算。
                        n_q = len(pair_objs)
                        n_tr = sum(1 for r in pair_objs if r.custom.translation_success)
                        if n_q > 0 and n_tr == 0:
                            print(f"[resume] ★汚染検出（翻訳成功 0/{n_q}）→ 再計算対象: {pn}")
                            continue
                        all_results.extend(pair_objs)
                        done.add(pn)
                        self.pair_times[pn] = data.get('wall_clock_sec')
                        self.pair_diagnostics[pn] = data.get('diagnostics', {})
                        self.completed_pairs.append(pn)
                        print(f"[resume] スキップ（完了済）: {pn} ({n_q}件, 翻訳成功{n_tr})")
                    except Exception as e:
                        print(f"[resume] 破損チェックポイント無視: {pj} ({e})")

        proc = psutil.Process() if psutil else None
        for i, pair_name in enumerate(pair_names):
            if pair_name in done:
                continue
            print(f"\n[{i+1}/{len(pair_names)}] 処理中: {pair_name}")
            _pair_start = time.time()
            pair_results = self.evaluate_pair(pair_name, max_queries)
            wall = round(time.time() - _pair_start, 2)
            self.pair_times[pair_name] = wall
            diag = {'wall_clock_sec': wall, 'query_count': len(pair_results)}
            if proc is not None:
                mi = proc.memory_info()
                diag['rss_mb'] = round(mi.rss / 1024 / 1024, 1)
                # peak_wset は Windows のみ。macOS/Linux は None（rss で代替判断）
                diag['peak_wset_mb'] = round(getattr(mi, 'peak_wset', 0) / 1024 / 1024, 1) \
                    if hasattr(mi, 'peak_wset') else None
            self.pair_diagnostics[pair_name] = diag
            all_results.extend(pair_results)
            self.completed_pairs.append(pair_name)
            if pairs_dir is not None:
                _write_pair_checkpoint(pairs_dir, pair_name, pair_results, wall, diag)
                _update_run_status(Path(run_dir), self.completed_pairs, 'running')

        return all_results


# =============================================================================
# 出力関数
# =============================================================================

def save_results_to_csv(results: List[QueryComparisonResult], output_path: Path):
    """全結果をCSVに保存"""
    fieldnames = [
        'pair_name', 'query_file', 'input_query', 'query_sha256',
        # 独自システム初回
        'custom_initial_source_count', 'custom_initial_result_count', 'initial_status',
        'custom_initial_tp', 'custom_initial_fp', 'custom_initial_fn',
        'custom_initial_precision', 'custom_initial_recall', 'custom_initial_f1',
        # 独自システム最終
        'custom_final_result_count',
        'custom_final_tp', 'custom_final_fp', 'custom_final_fn',
        'custom_final_precision', 'custom_final_recall', 'custom_final_f1',
        'custom_final_f2', 'custom_final_f0_5',
        # 上限診断（撤廃に伴い追加）
        'result_cap', 'cap_hit',
        # 緩和情報
        'relaxation_attempted', 'relaxation_applied', 'relaxation_phase',
        'relaxation_category', 'relaxation_primary_category',
        'custom_translation_success',
        'custom_output_query', 'custom_final_query',
        # Baseline
        'baseline_source_count', 'baseline_result_count',
        'baseline_tp', 'baseline_fp', 'baseline_fn',
        'baseline_precision', 'baseline_recall', 'baseline_f1',
        'baseline_f2', 'baseline_f0_5',
        'baseline_translation_success', 'baseline_output_query',
        # 差分
        'f1_diff_initial', 'f1_diff_final',
        # エラー
        'custom_error', 'baseline_error',
    ]
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(result.to_csv_row())
    
    print(f"[保存] {output_path}")


def save_no_relaxation_csv(results: List[QueryComparisonResult], output_path: Path):
    """緩和なしの評価CSVを保存"""
    # 緩和が適用されなかったクエリのみ
    no_relax_results = [r for r in results if not r.custom.relaxation.applied]
    
    fieldnames = [
        'pair_name', 'query_file',
        'custom_tp', 'custom_fp', 'custom_fn',
        'custom_precision', 'custom_recall', 'custom_f1',
        'baseline_tp', 'baseline_fp', 'baseline_fn',
        'baseline_precision', 'baseline_recall', 'baseline_f1',
        'f1_diff',
    ]
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in no_relax_results:
            writer.writerow({
                'pair_name': r.pair_name,
                'query_file': r.query_file,
                'custom_tp': r.custom.final_metrics.tp,
                'custom_fp': r.custom.final_metrics.fp,
                'custom_fn': r.custom.final_metrics.fn,
                'custom_precision': f'{r.custom.final_metrics.precision:.4f}',
                'custom_recall': f'{r.custom.final_metrics.recall:.4f}',
                'custom_f1': f'{r.custom.final_metrics.f1_score:.4f}',
                'baseline_tp': r.baseline.final_metrics.tp,
                'baseline_fp': r.baseline.final_metrics.fp,
                'baseline_fn': r.baseline.final_metrics.fn,
                'baseline_precision': f'{r.baseline.final_metrics.precision:.4f}',
                'baseline_recall': f'{r.baseline.final_metrics.recall:.4f}',
                'baseline_f1': f'{r.baseline.final_metrics.f1_score:.4f}',
                'f1_diff': f'{r.custom.final_metrics.f1_score - r.baseline.final_metrics.f1_score:+.4f}',
            })
    
    print(f"[保存] {output_path} ({len(no_relax_results)}件)")


def save_relaxation_only_csv(results: List[QueryComparisonResult], output_path: Path):
    """緩和対象のみの評価CSVを保存（カテゴリ付き）"""
    # 緩和が適用されたクエリのみ
    relax_results = [r for r in results if r.custom.relaxation.applied]
    
    fieldnames = [
        'pair_name', 'query_file',
        'relaxation_phase', 'relaxation_category', 'relaxation_primary_category',
        'initial_result_count', 'final_result_count',
        'initial_f1', 'final_f1', 'f1_improvement',
        'baseline_f1', 'f1_vs_baseline',
    ]
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in relax_results:
            writer.writerow({
                'pair_name': r.pair_name,
                'query_file': r.query_file,
                'relaxation_phase': r.custom.relaxation.phase,
                'relaxation_category': r.custom.relaxation.category,
                'relaxation_primary_category': r.custom.relaxation.primary_category,
                'initial_result_count': r.custom.initial_result_count,
                'final_result_count': r.custom.final_result_count,
                'initial_f1': f'{r.custom.initial_metrics.f1_score:.4f}',
                'final_f1': f'{r.custom.final_metrics.f1_score:.4f}',
                'f1_improvement': f'{r.custom.final_metrics.f1_score - r.custom.initial_metrics.f1_score:+.4f}',
                'baseline_f1': f'{r.baseline.final_metrics.f1_score:.4f}',
                'f1_vs_baseline': f'{r.custom.final_metrics.f1_score - r.baseline.final_metrics.f1_score:+.4f}',
            })
    
    print(f"[保存] {output_path} ({len(relax_results)}件)")


def save_phase_analysis_csv(results: List[QueryComparisonResult], output_path: Path):
    """Phase別分析CSVを保存"""
    # Phase別集計
    phase_stats = {}
    for r in results:
        if r.custom.relaxation.applied:
            phase = r.custom.relaxation.phase
            if phase not in phase_stats:
                phase_stats[phase] = {'count': 0, 'f1_sum': 0, 'improvement_sum': 0}
            phase_stats[phase]['count'] += 1
            phase_stats[phase]['f1_sum'] += r.custom.final_metrics.f1_score
            phase_stats[phase]['improvement_sum'] += (
                r.custom.final_metrics.f1_score - r.custom.initial_metrics.f1_score
            )
    
    fieldnames = ['phase', 'count', 'avg_f1', 'avg_improvement']
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for phase, stats in sorted(phase_stats.items()):
            writer.writerow({
                'phase': phase,
                'count': stats['count'],
                'avg_f1': f'{stats["f1_sum"] / stats["count"]:.4f}' if stats['count'] > 0 else '0.0000',
                'avg_improvement': f'{stats["improvement_sum"] / stats["count"]:+.4f}' if stats['count'] > 0 else '+0.0000',
            })
    
    print(f"[保存] {output_path}")


def save_summary_markdown(results: List[QueryComparisonResult], output_path: Path, elapsed_time: float):
    """サマリーMarkdownを保存"""
    if not results:
        return
    
    total = len(results)
    
    # 統計計算
    custom_translation_success = sum(1 for r in results if r.custom.translation_success)
    baseline_translation_success = sum(1 for r in results if r.baseline.translation_success)
    
    # 初回成功（緩和前に結果あり）
    initial_success = sum(1 for r in results if r.custom.initial_result_count > 0)
    
    # 緩和適用
    relaxation_applied = sum(1 for r in results if r.custom.relaxation.applied)
    
    # 最終成功
    final_success = sum(1 for r in results if r.custom.final_result_count > 0)
    
    # 平均スコア計算
    custom_initial_avg_f1 = sum(r.custom.initial_metrics.f1_score for r in results) / total
    custom_final_avg_f1 = sum(r.custom.final_metrics.f1_score for r in results) / total
    custom_final_avg_f2 = sum(r.custom.final_metrics.f2_score for r in results) / total
    custom_final_avg_f05 = sum(r.custom.final_metrics.f0_5_score for r in results) / total
    custom_final_avg_p = sum(r.custom.final_metrics.precision for r in results) / total
    custom_final_avg_r = sum(r.custom.final_metrics.recall for r in results) / total
    baseline_avg_f1 = sum(r.baseline.final_metrics.f1_score for r in results) / total
    baseline_avg_f2 = sum(r.baseline.final_metrics.f2_score for r in results) / total
    baseline_avg_f05 = sum(r.baseline.final_metrics.f0_5_score for r in results) / total
    baseline_avg_p = sum(r.baseline.final_metrics.precision for r in results) / total
    baseline_avg_r = sum(r.baseline.final_metrics.recall for r in results) / total
    
    # Phase別統計
    phase_counts = {}
    for r in results:
        if r.custom.relaxation.applied:
            phase = r.custom.relaxation.phase
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
    
    # Markdown生成
    md = []
    md.append("# 全体フロー評価レポート（クエリ変換 + 緩和）\n")
    md.append(f"**評価日時**: {time.strftime('%Y年%m月%d日 %H:%M:%S')}\n")
    md.append(f"**処理時間**: {elapsed_time/60:.1f}分 ({elapsed_time:.1f}秒)\n")
    md.append("---\n")
    
    md.append("## 📊 全体統計\n")
    md.append(f"- **総クエリ数**: {total}\n")
    md.append(f"- **変換成功率(独自)**: {custom_translation_success}/{total} ({custom_translation_success/total*100:.1f}%)\n")
    md.append(f"- **変換成功率(Baseline)**: {baseline_translation_success}/{total} ({baseline_translation_success/total*100:.1f}%)\n")
    
    md.append("\n### 緩和統計\n")
    md.append(f"- **初回成功（緩和不要）**: {initial_success}/{total} ({initial_success/total*100:.1f}%)\n")
    md.append(f"- **緩和適用**: {relaxation_applied}/{total} ({relaxation_applied/total*100:.1f}%)\n")
    md.append(f"- **最終成功**: {final_success}/{total} ({final_success/total*100:.1f}%)\n")
    
    md.append("\n### 評価指標比較\n")
    md.append("| 指標 | 独自(初回) | 独自(最終) | Baseline | 差分 |\n")
    md.append("|------|-----------|-----------|----------|------|\n")
    md.append(f"| Precision | - | {custom_final_avg_p*100:.2f}% | {baseline_avg_p*100:.2f}% | {(custom_final_avg_p-baseline_avg_p)*100:+.2f}% |\n")
    md.append(f"| Recall | - | {custom_final_avg_r*100:.2f}% | {baseline_avg_r*100:.2f}% | {(custom_final_avg_r-baseline_avg_r)*100:+.2f}% |\n")
    md.append(f"| **F1** | {custom_initial_avg_f1*100:.2f}% | **{custom_final_avg_f1*100:.2f}%** | {baseline_avg_f1*100:.2f}% | **{(custom_final_avg_f1-baseline_avg_f1)*100:+.2f}%** |\n")
    md.append(f"| F2 | - | {custom_final_avg_f2*100:.2f}% | {baseline_avg_f2*100:.2f}% | {(custom_final_avg_f2-baseline_avg_f2)*100:+.2f}% |\n")
    md.append(f"| F0.5 | - | {custom_final_avg_f05*100:.2f}% | {baseline_avg_f05*100:.2f}% | {(custom_final_avg_f05-baseline_avg_f05)*100:+.2f}% |\n")
    
    if phase_counts:
        md.append("\n### Phase別貢献度\n")
        md.append("| Phase | 成功数 | 割合 |\n")
        md.append("|-------|--------|------|\n")
        for phase, count in sorted(phase_counts.items()):
            md.append(f"| {phase} | {count} | {count/total*100:.1f}% |\n")
    
    md.append("\n---\n")
    md.append("## 📈 ペア別統計\n")
    
    # ペア別集計
    by_pair = {}
    for r in results:
        if r.pair_name not in by_pair:
            by_pair[r.pair_name] = []
        by_pair[r.pair_name].append(r)
    
    for pair_name in sorted(by_pair.keys()):
        pair_results = by_pair[pair_name]
        pair_total = len(pair_results)
        pair_relax = sum(1 for r in pair_results if r.custom.relaxation.applied)
        pair_custom_f1 = sum(r.custom.final_metrics.f1_score for r in pair_results) / pair_total
        pair_custom_p = sum(r.custom.final_metrics.precision for r in pair_results) / pair_total
        pair_custom_r = sum(r.custom.final_metrics.recall for r in pair_results) / pair_total
        pair_baseline_f1 = sum(r.baseline.final_metrics.f1_score for r in pair_results) / pair_total
        
        md.append(f"\n### {pair_name}\n")
        md.append(f"- クエリ数: {pair_total}\n")
        md.append(f"- 緩和適用: {pair_relax} ({pair_relax/pair_total*100:.1f}%)\n")
        md.append(f"- Precision(独自): {pair_custom_p*100:.2f}%\n")
        md.append(f"- Recall(独自): {pair_custom_r*100:.2f}%\n")
        md.append(f"- 平均F1(独自): {pair_custom_f1*100:.2f}%\n")
        md.append(f"- 平均F1(Baseline): {pair_baseline_f1*100:.2f}%\n")
        md.append(f"- F1差分: **{(pair_custom_f1-pair_baseline_f1)*100:+.2f}%**\n")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(md)
    
    print(f"[保存] {output_path}")


def save_results_to_json(results: List[QueryComparisonResult], output_dir: Path):
    """ペア別JSONを保存"""
    by_pair = {}
    for r in results:
        if r.pair_name not in by_pair:
            by_pair[r.pair_name] = []
        by_pair[r.pair_name].append(r.to_csv_row())
    
    for pair_name, pair_results in by_pair.items():
        json_path = output_dir / f'full_pipeline_{pair_name}.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(pair_results, f, ensure_ascii=False, indent=2)
        print(f"[保存] {json_path}")


# =============================================================================
# ペア単位並列化（ProcessPoolExecutor, spawn）
# ライブラリ層（cascading_relaxer.py / sparql_translator/src/）は変更しない。
# =============================================================================

def _pair_worker(payload):
    """ProcessPool ワーカー（spawn）: 1ペアを独立プロセスで評価し checkpoint を書く。
    親と共有可変状態なし。毎回新規 evaluator を生成することで前ペアのグラフキャッシュはGCされ
    累積しない（逐次単一プロセスの23GB累積を回避）。返り値は picklable な dict のみ。"""
    import time as _t, traceback as _tb
    try:
        ep = set(payload['enabled_phases']) if payload['enabled_phases'] else None
        ev = FullPipelineEvaluator(payload['project_root'], enabled_phases=ep,
                                   rdfs_materialize=payload['rdfs_materialize'])
        t0 = _t.time()
        pair_results = ev.evaluate_pair(payload['pair_name'], payload['max_queries'])
        wall = round(_t.time() - t0, 2)
        diag = {'wall_clock_sec': wall, 'query_count': len(pair_results)}
        if psutil is not None:
            mi = psutil.Process().memory_info()
            diag['rss_mb'] = round(mi.rss / 1024 / 1024, 1)
            diag['peak_wset_mb'] = round(getattr(mi, 'peak_wset', 0) / 1024 / 1024, 1) \
                if hasattr(mi, 'peak_wset') else None
        pairs_dir = Path(payload['run_dir']) / 'pairs'
        pairs_dir.mkdir(parents=True, exist_ok=True)
        _write_pair_checkpoint(pairs_dir, payload['pair_name'], pair_results, wall, diag)
        return {'ok': True, 'pair_name': payload['pair_name'], 'wall': wall, 'diag': diag,
                'results': [r.to_checkpoint() for r in pair_results]}
    except Exception as e:
        return {'ok': False, 'pair_name': payload['pair_name'], 'error': str(e),
                'traceback': _tb.format_exc()}


def _pair_input_size(pair_name):
    """入力サイズ（データセット .ttl/.owl 等のバイト合計）。大きいペアを先に投入するため。"""
    d = PROJECT_ROOT / 'data' / 'alignment' / pair_name
    tot = 0
    if d.exists():
        for f in d.rglob('*'):
            if f.suffix.lower() in ('.ttl', '.owl', '.nt', '.rdf'):
                try:
                    tot += f.stat().st_size
                except Exception:
                    pass
    return tot


def evaluate_pairs_parallel(pair_names, args, run_dir, enabled_phases):
    """ペア単位 ProcessPoolExecutor 並列。決定性のため最終集計は呼出側で (pair,query) ソート。
    親プロセスはグラフをロードしない。RSSサンプラで総ピーク used RAM を記録。"""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    import multiprocessing as _mp, threading as _th, time as _t
    ordered = sorted(pair_names, key=_pair_input_size, reverse=True)  # 大→小
    payloads = [{'pair_name': pn, 'project_root': str(PROJECT_ROOT),
                 'enabled_phases': sorted(enabled_phases) if enabled_phases else None,
                 'rdfs_materialize': bool(getattr(args, 'rdfs_materialize', False)),
                 'max_queries': args.max_queries, 'run_dir': str(run_dir)} for pn in ordered]
    all_results, pair_times, pair_diags, completed, failed = [], {}, {}, [], []
    peak = {'used': 0}
    stop = {'f': False}

    def _sampler():
        while not stop['f']:
            if psutil is not None:
                try:
                    peak['used'] = max(peak['used'], psutil.virtual_memory().used)
                except Exception:
                    pass
            _t.sleep(0.5)
    th = _th.Thread(target=_sampler, daemon=True)
    th.start()
    ctx = _mp.get_context('spawn')
    print(f"[並列] workers={args.workers} 投入順(サイズ降順): {ordered}")
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=ctx) as ex:
        futs = {ex.submit(_pair_worker, p): p['pair_name'] for p in payloads}
        for fut in as_completed(futs):
            res = fut.result()
            pn = res['pair_name']
            if res.get('ok'):
                for row in res['results']:
                    all_results.append(QueryComparisonResult.from_checkpoint(row))
                pair_times[pn] = res['wall']
                pair_diags[pn] = res['diag']
                completed.append(pn)
                _update_run_status(run_dir, completed, 'running')
                print(f"[worker完了] {pn} ({res['diag']['query_count']}件 {res['wall']}s "
                      f"rss={res['diag'].get('rss_mb')}MB)")
            else:
                failed.append(pn)
                print(f"[worker失敗] {pn}: {res.get('error')}\n{res.get('traceback', '')}")
    stop['f'] = True
    if psutil is not None:
        print(f"[並列] 総ピークRAM(used) = {peak['used']/1024/1024/1024:.1f} GB / "
              f"{psutil.virtual_memory().total/1024/1024/1024:.1f} GB")
    if failed:
        print(f"[並列] 失敗ペア {len(failed)}: {failed}（--resume で再計算可）")
    return all_results, pair_times, pair_diags, completed, peak['used']


# =============================================================================
# メイン関数
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='全体フロー評価プログラム（クエリ変換 + 緩和）'
    )
    parser.add_argument('pairs', nargs='*', help='評価するペア名')
    parser.add_argument('--all', '-a', action='store_true', help='全ペアを評価')
    parser.add_argument('--max-queries', '-n', type=int, default=None,
                        help='各ペアの最大クエリ数（デバッグ用）')
    parser.add_argument('--output', '-o', type=str, default='output',
                        help='出力ディレクトリ')
    parser.add_argument('--config-name', dest='config_name', type=str, default=None,
                        help='run ディレクトリのラベル（未指定なら pairs/all から導出）')
    parser.add_argument('--resume', type=str, default=None,
                        help='既存 run ディレクトリを指定して再開（pairs/ の完了ペアをスキップ）')
    parser.add_argument('--phases', type=str, default=None,
                        help='実行する緩和フェーズをカンマ区切りで指定（例: L1,L2,L3,L4a,L4b,L5）。'
                             '未指定なら全フェーズ（既定・従来と同一挙動）。cascading_relaxer.py 本体は変更しない。')
    parser.add_argument('--rdfs-materialize', dest='rdfs_materialize', action='store_true',
                        help='rdfs5/7/9/11 の限定的RDFS materializationをロード後のグラフに適用（既定OFF）。'
                             'rdfs2/3は適用しない。元の.ttl/.owlは変更しない。')
    parser.add_argument('--workers', type=int, default=1,
                        help='ペア単位並列のワーカー数（default 1=逐次=OFF）。'
                             '>=2 で ProcessPoolExecutor(spawn)による並列。'
                             '★既定OFFの理由: 逐次vs並列の bit-identical 検証で1067中1クエリ(query_16)が'
                             '並列ワーカーでのみ非決定的に差分。論文数値は逐次で生成すること。'
                             '並列は探索用の高速化(2.2x)に限定。ライブラリ層は不変・--resume時は逐次。')
    parser.add_argument('--query-list', dest='query_list', type=str, default=None,
                        help='(pair_name,query_file) の許可リストCSV/TSVへのパス（ヘッダ無し, '
                             'カンマ区切り2列）。指定した組だけを評価する（未指定なら全件・既定・従来と同一挙動）。'
                             'ディスク上のクエリファイルが後から増えても特定の母集団だけを再現するために使う。'
                             '--workers>=2 とは併用不可。')
    args = parser.parse_args()
    enabled_phases = set(p.strip() for p in args.phases.split(',')) if args.phases else None

    query_allowlist = None
    if args.query_list:
        if args.workers and args.workers >= 2:
            print("[ERROR] --query-list は --workers>=2（並列）と併用できません（未対応）")
            return
        list_path = Path(args.query_list)
        if not list_path.is_absolute():
            list_path = PROJECT_ROOT / list_path
        if not list_path.exists():
            print(f"[ERROR] --query-list で指定されたファイルが見つかりません: {list_path}")
            return
        query_allowlist = set()
        with open(list_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(',')
                if len(parts) < 2:
                    print(f"[ERROR] --query-list の行が不正です（pair,query_fileの2列が必要）: {line!r}")
                    return
                query_allowlist.add((parts[0].strip(), parts[1].strip()))
        print(f"[query-list] {list_path} から {len(query_allowlist)}件の許可リストを読み込みました")
    
    # ペア名の決定
    if args.all:
        pair_names = None  # 自動検出
    elif args.pairs:
        pair_names = args.pairs
    else:
        # デフォルト: cmt-conference
        pair_names = ['cmt-conference']
        print(f"[INFO] デフォルトペア: {pair_names}")
    
    # run_dir を実行前に決定（チェックポイントを pairs/ に書くため）
    config_name = getattr(args, 'config_name', None) or ('all' if args.all else '-'.join(args.pairs) if args.pairs else 'cmt-conference')
    if args.resume:
        run_dir = Path(args.resume)
        if not run_dir.is_absolute():
            run_dir = PROJECT_ROOT / run_dir
        if not run_dir.exists():
            print(f"[ERROR] --resume 先が存在しません: {run_dir}")
            return
        _parts = run_dir.name.split('_')
        ts = f'{_parts[0]}_{_parts[1]}' if len(_parts) >= 2 else time.strftime('%Y%m%d_%H%M%S')
        print(f"[resume] 既存 run を再開: {run_dir}")
    else:
        ts = time.strftime('%Y%m%d_%H%M%S')
        run_dir = PROJECT_ROOT / args.output / 'runs' / f'{ts}_{config_name}'
    run_dir.mkdir(parents=True, exist_ok=True)

    # 評価実行（ペア単位チェックポイント付き）
    args.parallel_peak_used = None
    if getattr(args, 'workers', 1) and args.workers >= 2 and not args.resume:
        # 並列。親はグラフをロードしない（ペア一覧の取得のみ軽量 evaluator を使う）。
        _lister = FullPipelineEvaluator(PROJECT_ROOT, enabled_phases=enabled_phases,
                                        rdfs_materialize=args.rdfs_materialize)
        _pairs = pair_names if pair_names is not None else _lister.find_all_pairs()
        start_time = time.time()
        results, _ptimes, _pdiags, _completed, _peak = evaluate_pairs_parallel(
            _pairs, args, run_dir, enabled_phases)
        elapsed_time = time.time() - start_time
        args.parallel_peak_used = _peak
        evaluator = _lister
        evaluator.pair_times = _ptimes
        evaluator.pair_diagnostics = _pdiags
        evaluator.completed_pairs = _completed
    else:
        # 逐次（--workers 1 または --resume）: 既存パス（挙動不変・決定性の参照）
        evaluator = FullPipelineEvaluator(PROJECT_ROOT, enabled_phases=enabled_phases,
                                          rdfs_materialize=args.rdfs_materialize,
                                          query_allowlist=query_allowlist)
        start_time = time.time()
        results = evaluator.evaluate_all_pairs(pair_names, max_queries=args.max_queries,
                                               run_dir=run_dir, resume=bool(args.resume))
        elapsed_time = time.time() - start_time

    if results:
        # 全ペアが揃ってからペア名→クエリでソートして書き出す（決定的順序）
        results = sorted(results, key=lambda r: (r.pair_name, r.query_file))
        # A2（判断事項e対策）: run完了時の健全性検証。翻訳成功が総数未満なら FAILED_TRANSLATION。
        _total = len(results)
        _translated = sum(1 for r in results if r.custom.translation_success)
        _by = {}
        for r in results:
            s, t = _by.get(r.pair_name, (0, 0))
            _by[r.pair_name] = (s + (1 if r.custom.translation_success else 0), t + 1)
        _dead_pairs = sorted(p for p, (s, t) in _by.items() if t > 0 and s == 0)
        _health = {'translated': _translated, 'total': _total,
                   'rate': round(_translated / _total, 4) if _total else None,
                   'dead_translation_pairs': _dead_pairs}
        _run_status = 'completed' if _translated == _total else 'FAILED_TRANSLATION'
        if _translated != _total:
            print(f"[健全性] ★FAILED_TRANSLATION: 翻訳成功 {_translated}/{_total} "
                  f"全滅ペア={_dead_pairs} → run を FAILED とマーク（resume で再計算対象）")
        else:
            print(f"[健全性] OK: 翻訳成功 {_translated}/{_total}")
        save_results_to_csv(results, run_dir / 'full_pipeline_results.csv')
        save_no_relaxation_csv(results, run_dir / 'full_pipeline_no_relaxation.csv')
        save_relaxation_only_csv(results, run_dir / 'full_pipeline_relaxation_only.csv')
        save_phase_analysis_csv(results, run_dir / 'relaxation_phase_analysis.csv')
        save_summary_markdown(results, run_dir / 'FULL_PIPELINE_SUMMARY.md', elapsed_time)
        save_results_to_json(results, run_dir)
        _write_run_config(run_dir, config_name, ts, args, elapsed_time,
                          getattr(evaluator, 'pair_times', {}),
                          getattr(evaluator, 'completed_pairs', []),
                          getattr(evaluator, 'pair_diagnostics', {}),
                          status=_run_status, health=_health,
                          rdfs_materialize_stats=getattr(evaluator.tester.data_loader, 'last_materialize_stats', {})
                              if getattr(evaluator, 'rdfs_materialize', False) else {})
        print(f"\n[完了] 評価結果を保存しました（処理時間: {elapsed_time:.1f}秒） -> {run_dir}")
    else:
        print("\n[警告] 評価結果がありません")


def _write_pair_checkpoint(pairs_dir, pair_name, pair_results, wall, diag):
    """ペア結果を pairs/{pair}.json に atomic 書き出し。tmp→os.replace で壊れたファイルを残さない。"""
    data = {'pair_name': pair_name, 'wall_clock_sec': wall, 'diagnostics': diag,
            'results': [r.to_checkpoint() for r in pair_results]}
    safe = pair_name.replace('/', '_').replace('\\', '_')
    final = pairs_dir / f'{safe}.json'
    tmp = pairs_dir / f'{safe}.json.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(str(tmp), str(final))  # 同一FS上で atomic


def _update_run_status(run_dir, completed_pairs, status):
    """run_config.json を実行中に atomic 更新（kill 時に status/完了ペアが残るように）。"""
    final = run_dir / 'run_config.json'
    tmp = run_dir / 'run_config.json.tmp'
    data = {}
    if final.exists():
        try:
            with open(final, encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
    data.update({'status': status, 'num_completed_pairs': len(completed_pairs),
                 'completed_pairs': list(completed_pairs)})
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(final))


def _write_run_config(run_dir, config_name, ts, args, elapsed_time, pair_times,
                      completed_pairs=None, diagnostics=None, status='completed',
                      rdfs_materialize_stats=None, health=None):
    """run_config.json に再現用メタデータを記録。完了ペア・status・診断も。
    A2: health(翻訳健全性)を記録し、status=FAILED_TRANSLATION の run は下流の照合対象から外せるようにする。"""
    import json as _json, platform as _plat, subprocess as _sp, sys as _sys
    try:
        _commit = _sp.check_output(['git', 'rev-parse', 'HEAD'], cwd=str(PROJECT_ROOT),
                                   encoding='utf-8', errors='replace').strip()
    except Exception:
        _commit = 'unknown'
    try:
        import rdflib as _rl; _rlv = _rl.__version__
    except Exception:
        _rlv = 'unknown'
    cfg = {
        'config_name': config_name,
        'timestamp': ts,
        'git_commit': _commit,
        'params': {
            # θ は relax_query の既定値（呼び出し側未指定）。
            'relax_max_results_threshold_default': 100000,
            'max_queries': args.max_queries,
            'pairs': ('all' if args.all else (args.pairs or ['cmt-conference'])),
            'phases': args.phases or 'all(default)',  # アブレーション設定
            # (pair,query_file) 許可リスト。null=全件（従来と同一挙動）。
            'query_list_path': getattr(args, 'query_list', None),
            'result_cap': None,  # 10000件打ち切りを撤廃。null=無制限。
        },
        'wall_clock_sec_total': round(elapsed_time, 2),
        'wall_clock_sec_per_pair': pair_times,
        'rdflib_version': _rlv,
        # RDFS推論の有効/無効。有効な場合は適用規則を曖昧な"有効"でなく列挙する。
        'rdfs_inference': bool(getattr(args, 'rdfs_materialize', False)),
        'rdfs_rules': ['rdfs5', 'rdfs7', 'rdfs9', 'rdfs11'] if getattr(args, 'rdfs_materialize', False) else [],
        'rdfs_materialize_stats': rdfs_materialize_stats or {},
        'python_version': _sys.version.split()[0],
        # 決定性のため冒頭で PYTHONHASHSEED=0 に固定して再実行済み。実測値を記録（"0" が期待値）。
        'pythonhashseed': os.environ.get('PYTHONHASHSEED'),
        'os': f'{_plat.system()} {_plat.release()}',
        'exp2_endpoints': None,    # 実験1はローカル rdflib（リモート未使用）
        'backend': 'rdflib in-memory (exp1 local)',
        # 並列化
        'workers': getattr(args, 'workers', 1),
        'parallel_peak_used_gb': (round(getattr(args, 'parallel_peak_used', None) / 1024 / 1024 / 1024, 2)
                                  if getattr(args, 'parallel_peak_used', None) else None),
        'status': status,
        'translation_health': health or {},
        'num_completed_pairs': len(completed_pairs or []),
        'completed_pairs': list(completed_pairs or []),
        'per_pair_diagnostics': diagnostics or {},
    }
    tmp = run_dir / 'run_config.json.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        _json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(run_dir / 'run_config.json'))


if __name__ == '__main__':
    main()
