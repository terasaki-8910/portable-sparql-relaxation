#!/usr/bin/env python3
"""
緩和クエリ評価プログラム（Relaxation Query Evaluator）

relaxation ディレクトリに格納された SPARQLクエリを評価するプログラム。
以下の3段階チェックで緩和の有効性を測定する：

【評価条件】
1. ソースオントロジーで非空（結果あり）
2. 変換直後ターゲットオントロジーで空（結果0件）
3. 緩和後ターゲットオントロジーで非空（結果あり）

→ 3条件すべて満たすクエリのみを「成功」とカウント

【データセット選択優先順位】
1. _100.ttl
2. _100.owl
3. <dataset名>.ttl
4. <dataset名>.owl

【使用方法】
# 全ペアを評価（自動検出）
python evaluate_relaxation_test.py --all

# 特定のペアのみ評価
python evaluate_relaxation_test.py cmt-conference

# 複数ペアを評価
python evaluate_relaxation_test.py cmt-conference conference-confOf

# デバッグモード（各ペア最大10クエリ）
python evaluate_relaxation_test.py cmt-conference -n 10

【出力ファイル】
- output/relaxation_test/relaxation_query_results.csv   : 全クエリの詳細結果
- output/relaxation_test/RELAXATION_QUERY_SUMMARY.md    : 統計サマリー
- output/relaxation_test/relaxation_query_<ペア名>.json : ペア別JSON詳細

【CSVカラム】
- pair_name, query_file                   : 基本情報
- source_count, source_success            : ソース実行結果
- translated_count, translated_empty      : 変換直後実行結果
- relaxation_phase, relaxation_count      : 緩和結果
- relaxation_success, all_conditions_met  : 成否判定
- tp, fp, fn, recall, f1                  : 評価指標
"""

import os
import sys
import re
import csv
import json
import time
import argparse
import logging
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional, Any
from dataclasses import dataclass, field

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "sparql_translator"))

# 既存モジュールのインポート
from test_dir.test_data_retrieval import DataRetrievalTester
from modules.config_loader import ConfigLoader
from modules.data_loader import DataLoader, DataSourceFactory

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
class RelaxationQueryResult:
    """緩和クエリ評価結果"""
    pair_name: str
    query_file: str
    
    # ソース実行
    source_query: str = ""
    source_count: int = 0
    source_unique_count: int = 0  # ユニークキー数（F1計算に使用）
    source_success: bool = False  # ソースで非空か
    source_entities: List[str] = field(default_factory=list)
    source_error: str = ""
    
    # 翻訳
    translation_success: bool = False
    translated_query: str = ""
    translation_error: str = ""
    
    # 変換直後ターゲット実行
    translated_count: int = 0
    translated_empty: bool = False  # 変換直後が空か
    translated_entities: List[str] = field(default_factory=list)
    translated_error: str = ""
    
    # 緩和
    relaxation_applied: bool = False
    relaxation_phase: str = ""
    relaxed_query: str = ""
    relaxation_count: int = 0
    relaxation_success: bool = False  # 緩和後非空か
    relaxation_entities: List[str] = field(default_factory=list)
    relaxation_error: str = ""
    tried_phases: List[str] = field(default_factory=list)
    
    # 総合判定
    all_conditions_met: bool = False  # 3条件すべて満たすか
    
    # 評価指標（緩和後）
    tp: int = 0
    fp: int = 0
    fn: int = 0
    precision: float = 0.0  # 適合率
    recall: float = 0.0     # 再現率
    f1: float = 0.0         # F1スコア
    information_loss: float = 0.0  # 情報損失 (1 - recall)
    
    def to_csv_row(self) -> dict:
        """CSV行に変換"""
        return {
            'pair_name': self.pair_name,
            'query_file': self.query_file,
            # ソース
            'source_count': self.source_count,
            'source_unique_count': self.source_unique_count,  # ユニークキー数
            'source_success': self.source_success,
            'source_error': self.source_error,
            # 翻訳
            'translation_success': self.translation_success,
            'translation_error': self.translation_error,
            # 変換直後
            'translated_count': self.translated_count,
            'translated_empty': self.translated_empty,
            'translated_error': self.translated_error,
            # 緩和
            'relaxation_applied': self.relaxation_applied,
            'relaxation_phase': self.relaxation_phase,
            'relaxation_count': self.relaxation_count,
            'relaxation_success': self.relaxation_success,
            'tried_phases': ','.join(self.tried_phases) if self.tried_phases else '',
            'relaxation_error': self.relaxation_error,
            # 総合判定
            'all_conditions_met': self.all_conditions_met,
            # 評価指標
            'tp': self.tp,
            'fp': self.fp,
            'fn': self.fn,
            'precision': f'{self.precision:.4f}',
            'recall': f'{self.recall:.4f}',
            'f1': f'{self.f1:.4f}',
            'information_loss': f'{self.information_loss:.4f}',
            # 緩和試行回数
            'tried_phases_count': len(self.tried_phases) if self.tried_phases else 0,
            # クエリ本文（全文）
            'source_query': self.source_query if self.source_query else '',
            'translated_query': self.translated_query if self.translated_query else '',
            'relaxed_query': self.relaxed_query if self.relaxed_query else '',
        }


# =============================================================================
# メイン評価クラス
# =============================================================================

class RelaxationQueryEvaluator:
    """緩和クエリ評価クラス"""
    
    def __init__(self, project_root: Path = None, verbose: bool = False,
                 enabled_phases: Optional[Set[str]] = None,
                 rdfs_materialize: bool = False):
        self.verbose = verbose
        # アブレーション用。None なら全フェーズ＝従来と同一挙動。
        # キー: 'L1','L2','L3','L4a','L4b','L5'。cascading_relaxer 本体は一切変更しない。
        self.enabled_phases = enabled_phases
        # Task E: rdfs5/7/9/11 の限定RDFS materialization（既定OFF）。ロードしたグラフに適用。
        self.rdfs_materialize = rdfs_materialize
        if project_root is None:
            self.project_root = PROJECT_ROOT
        elif isinstance(project_root, str):
            self.project_root = Path(project_root).resolve()
        else:
            self.project_root = project_root
        
        # ConfigLoader初期化
        self.config_loader = ConfigLoader(str(self.project_root))
        self.data_loader = DataLoader(self.config_loader)
        
        # DataRetrievalTesterの初期化（translate_query用）
        try:
            self.tester = DataRetrievalTester(str(self.project_root))
            self.translator_available = True
            print("[INFO] DataRetrievalTester を初期化しました")
        except Exception as e:
            print(f"[WARNING] DataRetrievalTester が利用不可: {e}")
            self.translator_available = False
            self.tester = None
        
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
    
    def find_all_pairs(self) -> List[str]:
        """relaxationディレクトリを持つ全ペアを検出
        
        除外リスト: クエリファイルがソース空で評価不能なペア
        """
        # 評価不能ペア（ソース空）を除外
        EXCLUDED_PAIRS = {
            'confOf-edas',      # ソース空
            'confOf-ekaw',      # ソース空
            'conference-cmt',   # ソース空
            'edas-cmt',         # ソース空
            'edas-conference',  # ソース空
        }
        
        alignment_dir = self.project_root / 'data' / 'alignment'
        valid_pairs = []
        
        for pair_dir in sorted(alignment_dir.iterdir()):
            if pair_dir.is_dir():
                pair_name = pair_dir.name
                
                # 除外ペアはスキップ
                if pair_name in EXCLUDED_PAIRS:
                    continue
                    
                relaxation_dir = pair_dir / 'queries' / 'relaxation'
                
                # relaxationディレクトリが存在し、クエリファイルがあるペアのみ
                if relaxation_dir.exists():
                    sparql_files = list(relaxation_dir.glob('*.sparql'))
                    if sparql_files:
                        valid_pairs.append(pair_name)
        
        return valid_pairs
    
    def find_relaxation_queries(self, pair_name: str) -> List[Path]:
        """ペアのrelaxationクエリファイルを検索"""
        relaxation_dir = self.project_root / 'data' / 'alignment' / pair_name / 'queries' / 'relaxation'
        
        if not relaxation_dir.exists():
            return []
        
        # .sparql ファイルを取得
        return sorted(relaxation_dir.glob('*.sparql'))
    
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
    
    def load_dataset_priority(self, pair_name: str, ontology_name: str) -> Optional[Any]:
        """
        _eswc.ttl優先でデータセットを読み込み（パフォーマンス最適化）
        
        優先順位:
        1. _eswc.ttl （小規模データセット）
        2. _100.ttl
        3. _100.owl
        4. <name>.ttl
        5. <name>.owl
        """
        # まずペアディレクトリ内のdatasetを確認
        pair_dataset_dir = self.project_root / 'data' / 'alignment' / pair_name / 'dataset'
        global_dataset_dir = self.project_root / 'data' / 'datasets'
        
        candidates = [
            (pair_dataset_dir / f"{ontology_name}_eswc.ttl", "turtle"),
            (global_dataset_dir / f"{ontology_name}_eswc.ttl", "turtle"),
            (pair_dataset_dir / f"{ontology_name}_100.ttl", "turtle"),
            (global_dataset_dir / f"{ontology_name}_100.ttl", "turtle"),
            (pair_dataset_dir / f"{ontology_name}_100.owl", "xml"),
            (global_dataset_dir / f"{ontology_name}_100.owl", "xml"),
            (pair_dataset_dir / f"{ontology_name}.ttl", "turtle"),
            (global_dataset_dir / f"{ontology_name}.ttl", "turtle"),
            (pair_dataset_dir / f"{ontology_name}.owl", "xml"),
            (global_dataset_dir / f"{ontology_name}.owl", "xml"),
        ]
        
        for file_path, rdf_format in candidates:
            if file_path.exists():
                try:
                    # DataSourceFactoryでデータソースを生成
                    dataset_info = {
                        "type": "file",
                        "path": str(file_path),
                        "format": rdf_format
                    }
                    data_source = DataSourceFactory.create_source(dataset_info, self.config_loader)
                    print(f"    ✓ データセット読み込み: {file_path.name}")
                    # Task E: RDFS materialization をロード後のグラフにインメモリ適用（元ファイルは不変）
                    if getattr(self, 'rdfs_materialize', False) and hasattr(data_source, 'graph'):
                        try:
                            from modules.rdfs_materializer import materialize as _rdfs_mat
                            _before = len(data_source.graph)
                            _cnt = _rdfs_mat(data_source.graph)
                            print(f"    [RDFS] {ontology_name}: {_before}→{len(data_source.graph)} triples {_cnt}")
                        except Exception as _e:
                            print(f"    [RDFS] materialize失敗（推論なしで続行）: {_e}")
                    return data_source
                except Exception as e:
                    print(f"    ✗ データセット読み込みエラー: {file_path.name} - {e}")
                    continue
        
        return None
    
    def load_pair_data_sources(self, pair_name: str) -> Tuple[Optional[Any], Optional[Any]]:
        """ペアのソース・ターゲットデータソースを読み込み"""
        # キャッシュチェック
        cache_key = pair_name
        if cache_key in self._source_cache and cache_key in self._target_cache:
            return self._source_cache[cache_key], self._target_cache[cache_key]
        
        # ペア名からソース・ターゲットオントロジー名を推定
        parts = pair_name.split('-')
        if len(parts) != 2:
            print(f"    ✗ 無効なペア名形式: {pair_name}")
            return None, None
        
        source_ont, target_ont = parts[0], parts[1]
        
        print(f"  データソース読み込み中...")
        print(f"    ソース: {source_ont}")
        source_ds = self.load_dataset_priority(pair_name, source_ont)
        
        print(f"    ターゲット: {target_ont}")
        target_ds = self.load_dataset_priority(pair_name, target_ont)
        
        # キャッシュに保存
        if source_ds:
            self._source_cache[cache_key] = source_ds
        if target_ds:
            self._target_cache[cache_key] = target_ds
        
        return source_ds, target_ds
    
    def execute_query(self, query: str, data_source, timeout: int = 60, add_limit: bool = True) -> Tuple[int, List[str], str]:
        """
        クエリを実行して結果件数、エンティティリスト、エラーを返す
        Windows対応のタイムアウト処理付き
        
        Args:
            query: SPARQLクエリ
            data_source: データソース
            timeout: タイムアウト秒数
            add_limit: LIMIT句がない場合に自動追加（デフォルト: True、最大10000件）
        
        Returns:
            (result_count, entities, error_message)
        """
        import threading
        import queue
        
        # LIMIT句の自動追加（パフォーマンス最適化）
        actual_query = query
        limit_added = False
        if add_limit and 'LIMIT' not in query.upper():
            # クエリの末尾にLIMIT 10000を追加
            actual_query = query.strip()
            if actual_query.endswith('}'):
                actual_query += ' LIMIT 10000'
                limit_added = True
            else:
                # 既に}の後にコメントなどがある場合
                actual_query += '\nLIMIT 10000'
                limit_added = True
        
        if self.verbose and limit_added:
            print(f"[LIMIT追加] ", end="", flush=True)
        
        result_queue = queue.Queue()
        
        def query_worker():
            try:
                # 元のdata_source.queryはすでにタイムアウトを試みるが、
                # Windowsでは機能しないので、ここでもラップする
                results = data_source.query(actual_query, timeout=timeout)
                result_queue.put(('success', results))
            except Exception as e:
                result_queue.put(('error', str(e)))
        
        thread = threading.Thread(target=query_worker, daemon=True)
        thread.start()
        thread.join(timeout=timeout)
        
        if thread.is_alive():
            # タイムアウト発生
            return 0, [], f"Query timed out after {timeout} seconds"
        
        try:
            status, result_or_error = result_queue.get_nowait()
            if status == 'error':
                return 0, [], result_or_error
            results = result_or_error
            
            if results is None:
                return 0, [], "Query returned None"
            
            result_list = list(results) if hasattr(results, '__iter__') else []
            count = len(result_list)
            
            # エンティティURI抽出
            entities = []
            seen = set()
            for row in result_list:
                if isinstance(row, dict):
                    for value in row.values():
                        uri = str(value) if value else ''
                        if uri.startswith('http://') and uri not in seen:
                            seen.add(uri)
                            entities.append(uri)
                elif hasattr(row, 'asdict'):
                    for value in row.asdict().values():
                        uri = str(value) if value else ''
                        if uri.startswith('http://') and uri not in seen:
                            seen.add(uri)
                            entities.append(uri)
                elif hasattr(row, '__iter__'):
                    for value in row:
                        uri = str(value) if value else ''
                        if uri.startswith('http://') and uri not in seen:
                            seen.add(uri)
                            entities.append(uri)
            
            return count, entities, ""
            
        except Exception as e:
            return 0, [], str(e)
    
    def extract_entity_key(self, uri: str) -> Optional[str]:
        """URIからエンティティキー（種別-番号）を抽出
        
        例: 
        - "http://cmt-instances#paper-1" → "paper-1"
        - "http://confOf-instances#paper1" → "paper-1"
        - "http://conference-instances#paper_1" → "paper-1"
        """
        if '#' in uri:
            local_name = uri.split('#')[-1]
        elif '/' in uri:
            local_name = uri.split('/')[-1]
        else:
            local_name = uri
        
        # パターン1: prefix + separator + number (例: paper-123, paper_45, person-1)
        # アンダースコアまたはハイフンを明示的なセパレータとして扱う
        match = re.match(r'^([a-zA-Z]+)[_-](\d+)$', local_name)
        if match:
            prefix = match.group(1).lower()
            number = match.group(2)
            return f"{prefix}-{number}"
        
        # パターン2: prefixNumber (例: paper123, person45)
        match = re.match(r'^([a-zA-Z]+)(\d+)$', local_name)
        if match:
            prefix = match.group(1).lower()
            number = match.group(2)
            return f"{prefix}-{number}"
        
        # マッチしない場合はlocal_name全体を返す（小文字化）
        return local_name.lower()
    
    def match_entities(self, source_entities: List[str], target_entities: List[str]) -> Tuple[int, int, int]:
        """エンティティをマッチングしてTP, FP, FN数を返す
        
        改善版: エンティティ種別（prefix）も考慮してマッチング
        例: paper-1 は paper-1 とのみマッチし、person-1 とはマッチしない
        
        Returns:
            (tp, fp, fn): TP=マッチしたキー数, FP=targetのみにあるキー数, FN=sourceのみにあるキー数
        """
        if not source_entities and not target_entities:
            return 0, 0, 0
        if not source_entities:
            # sourceが空ならtarget全てがFP
            target_keys = set(self.extract_entity_key(uri) for uri in target_entities if self.extract_entity_key(uri))
            return 0, len(target_keys), 0
        if not target_entities:
            # targetが空ならsource全てがFN
            source_keys = set(self.extract_entity_key(uri) for uri in source_entities if self.extract_entity_key(uri))
            return 0, 0, len(source_keys)
        
        # ソースエンティティのユニークキーセット
        source_keys = set()
        for uri in source_entities:
            key = self.extract_entity_key(uri)
            if key:
                source_keys.add(key)
        
        # ターゲットエンティティのユニークキーセット
        target_keys = set()
        for uri in target_entities:
            key = self.extract_entity_key(uri)
            if key:
                target_keys.add(key)
        
        # 集合演算でTP, FP, FNを計算
        tp = len(source_keys & target_keys)  # 両方にあるキー
        fn = len(source_keys - target_keys)  # sourceのみにあるキー
        fp = len(target_keys - source_keys)  # targetのみにあるキー
        
        return tp, fp, fn
    
    def calculate_metrics(
        self, 
        source_entities: List[str], 
        target_entities: List[str]
    ) -> Tuple[int, int, int, int, float, float, float]:
        """評価指標を計算 (source_unique, tp, fp, fn, precision, recall, f1)
        
        ユニークキーベースで計算:
        - source_unique: source のユニークキー数
        - TP: source と target 両方に存在するキー数
        - FP: target のみに存在するキー数
        - FN: source のみに存在するキー数
        """
        tp, fp, fn = self.match_entities(source_entities, target_entities)
        
        # ソースのユニークキー数を計算
        source_unique = tp + fn  # TP + FN = sourceのユニーク数
        
        # ゼロ除算対策
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        
        return source_unique, tp, fp, fn, precision, recall, f1
    
    def apply_relaxation(
        self, 
        query: str, 
        target_data_source,
        source_ont: str = None,
        target_ont: str = None
    ) -> Tuple[str, str, List[str], str]:
        """
        クエリ緩和を適用
        
        Returns:
            (relaxed_query, phase, tried_phases, error)
        """
        if not self.relaxer_available or not self.relaxer:
            return query, "", [], "Relaxer not available"
        
        try:
            # executor関数を定義
            def executor(q: str) -> Dict[str, Any]:
                count, entities, error = self.execute_query(q, target_data_source)
                return {
                    'success': error == "",
                    'count': count,
                    'error': error
                }
            
            # CascadingRelaxerで緩和
            relax_result = self.relaxer.relax_query(
                query=query,
                source_ont=source_ont,
                target_ont=target_ont,
                executor=executor,
                enabled_phases=self.enabled_phases
            )
            
            if relax_result.success and relax_result.relaxed_query != query:
                tried_phases = relax_result.all_tried_phases if hasattr(relax_result, 'all_tried_phases') else []
                return relax_result.relaxed_query, relax_result.phase, tried_phases, ""
            else:
                tried_phases = relax_result.all_tried_phases if hasattr(relax_result, 'all_tried_phases') else []
                return query, "", tried_phases, "No successful relaxation"
            
        except Exception as e:
            return query, "", [], str(e)
    
    def evaluate_query(
        self,
        pair_name: str,
        query_file: Path,
        source_ds,
        target_ds,
        edoal_file: Path
    ) -> RelaxationQueryResult:
        """1クエリを評価"""
        verbose = self.verbose
        result = RelaxationQueryResult(
            pair_name=pair_name,
            query_file=query_file.name
        )
        
        # Step 1: クエリファイル読み込み
        if verbose:
            print(f"    [Step1] クエリ読み込み中...", end=" ", flush=True)
        try:
            with open(query_file, 'r', encoding='utf-8') as f:
                source_query = f.read().strip()
            result.source_query = source_query
        except Exception as e:
            result.source_error = f"Failed to read query file: {e}"
            if verbose:
                print(f"失敗")
            return result
        
        if not source_query:
            result.source_error = "Empty query file"
            if verbose:
                print(f"空")
            return result
        if verbose:
            print(f"OK")
            # クエリの先頭部分を表示（デバッグ用）
            query_preview = source_query.replace('\n', ' ')[:200]
            print(f"    [DEBUG] クエリ: {query_preview}...")
        
        # Step 2: ソースオントロジーで実行
        if verbose:
            print(f"    [Step2] ソース実行中...", end=" ", flush=True)
            print(f"(ds={type(source_ds).__name__})", end=" ", flush=True)
        source_count, source_entities, source_error = self.execute_query(source_query, source_ds)
        if verbose and source_error:
            print(f"エラー: {source_error[:100]}", end=" ", flush=True)
        result.source_count = source_count
        result.source_entities = source_entities
        result.source_error = source_error
        result.source_success = (source_count > 0 and source_error == "")
        if verbose:
            print(f"{source_count}件")
        
        if not result.source_success:
            # ソースで非空でない → 条件1を満たさない
            return result
        
        # Step 3: 翻訳（DataRetrievalTesterのtranslate_queryを使用）
        if verbose:
            print(f"    [Step3] 翻訳中...", end=" ", flush=True)
        if not self.translator_available:
            result.translation_error = "Translator not available"
            if verbose:
                print(f"失敗")
            return result
        
        try:
            success, translated_query, error, missing_uris, alignment, used_uris = \
                self.tester.translate_query(source_query, str(edoal_file))
            if success and translated_query:
                result.translation_success = True
                result.translated_query = translated_query
                if verbose:
                    print(f"OK")
            else:
                result.translation_error = error or "Translation returned empty"
                if verbose:
                    print(f"失敗")
                return result
        except Exception as e:
            result.translation_error = str(e)
            if verbose:
                print(f"例外: {e}")
            return result
        
        # Step 4: 変換直後ターゲットで実行
        if verbose:
            print(f"    [Step4] 変換直後ターゲット実行中...", end=" ", flush=True)
        trans_count, trans_entities, trans_error = self.execute_query(result.translated_query, target_ds)
        result.translated_count = trans_count
        result.translated_entities = trans_entities
        result.translated_error = trans_error
        result.translated_empty = (trans_count == 0)
        if verbose:
            print(f"{trans_count}件")
        
        if not result.translated_empty:
            # 変換直後が空でない → 条件2を満たさない（緩和不要）
            return result
        
        # Step 5: 緩和を適用
        if verbose:
            print(f"    [Step5] 緩和適用中...", end=" ", flush=True)
        parts = pair_name.split('-')
        source_ont = parts[0] if len(parts) >= 2 else None
        target_ont = parts[1] if len(parts) >= 2 else None
        
        relaxed_query, phase, tried_phases, relax_error = self.apply_relaxation(
            translated_query, target_ds, source_ont, target_ont
        )
        
        result.relaxed_query = relaxed_query
        result.relaxation_phase = phase
        result.tried_phases = tried_phases
        result.relaxation_error = relax_error
        if verbose:
            print(f"Phase={phase or 'なし'}")
        
        if phase and relaxed_query != translated_query:
            result.relaxation_applied = True
            
            # 緩和クエリを実行
            if verbose:
                print(f"    [Step6] 緩和クエリ実行中...", end=" ", flush=True)
            relax_count, relax_entities, relax_exec_error = self.execute_query(relaxed_query, target_ds)
            result.relaxation_count = relax_count
            result.relaxation_entities = relax_entities
            result.relaxation_success = (relax_count > 0 and relax_exec_error == "")
            if verbose:
                print(f"{relax_count}件")
            
            if relax_exec_error:
                result.relaxation_error = relax_exec_error
        
        # Step 6: 総合判定
        result.all_conditions_met = (
            result.source_success and 
            result.translated_empty and 
            result.relaxation_success
        )
        
        # Step 7: 評価指標計算（緩和後）
        if result.relaxation_success:
            source_unique, tp, fp, fn, precision, recall, f1 = self.calculate_metrics(
                source_entities, result.relaxation_entities
            )
            result.source_unique_count = source_unique
            result.tp = tp
            result.fp = fp
            result.fn = fn
            result.precision = precision
            result.recall = recall
            result.f1 = f1
            result.information_loss = 1.0 - recall
        
        return result
    
    def evaluate_pair(self, pair_name: str, max_queries: int = None) -> List[RelaxationQueryResult]:
        """1ペアを評価"""
        results = []
        
        print(f"\n{'='*80}")
        print(f"ペア: {pair_name}")
        print(f"{'='*80}")
        
        # EDOALファイル検索
        edoal_file = self.find_edoal_file(pair_name)
        if not edoal_file:
            print(f"  ✗ EDOALファイルが見つかりません")
            return results
        print(f"  ✓ EDOALファイル: {edoal_file.name}")
        
        # データソース読み込み
        source_ds, target_ds = self.load_pair_data_sources(pair_name)
        if not source_ds or not target_ds:
            print(f"  ✗ データソースの読み込みに失敗")
            return results
        
        # relaxationクエリ検索
        query_files = self.find_relaxation_queries(pair_name)
        if not query_files:
            print(f"  ✗ relaxationクエリが見つかりません")
            return results
        
        if max_queries:
            query_files = query_files[:max_queries]
        
        print(f"  クエリ数: {len(query_files)}")
        print(f"-" * 80)
        
        # 各クエリを評価
        for i, query_file in enumerate(query_files):
            print(f"  [{i+1}/{len(query_files)}] {query_file.name}", end=" ")
            
            result = self.evaluate_query(
                pair_name, query_file, source_ds, target_ds, edoal_file
            )
            results.append(result)
            
            # 結果表示
            if result.all_conditions_met:
                print(f"✓ 成功 (Phase: {result.relaxation_phase}, F1: {result.f1:.2f})")
            elif not result.source_success:
                print(f"✗ ソース空 ({result.source_count}件)")
            elif not result.translation_success:
                print(f"✗ 翻訳失敗: {result.translation_error[:50]}")
            elif not result.translated_empty:
                print(f"- 変換直後非空 ({result.translated_count}件) → 緩和不要")
            elif not result.relaxation_success:
                print(f"✗ 緩和失敗 (試行: {','.join(result.tried_phases) if result.tried_phases else 'なし'})")
            else:
                print(f"? 不明")
        
        return results
    
    def evaluate_all_pairs(self, pair_names: List[str] = None, max_queries: int = None) -> List[RelaxationQueryResult]:
        """全ペアを評価"""
        if pair_names is None:
            pair_names = self.find_all_pairs()
        
        print("=" * 80)
        print("緩和クエリ評価プログラム（Relaxation Query Evaluator）")
        print("=" * 80)
        print(f"対象ペア: {len(pair_names)}ペア")
        print(f"ペア一覧: {', '.join(pair_names)}")
        if max_queries:
            print(f"最大クエリ数: {max_queries}/ペア")
        print("=" * 80)
        
        all_results = []
        
        for i, pair_name in enumerate(pair_names):
            print(f"\n[{i+1}/{len(pair_names)}] 評価中: {pair_name}")
            pair_results = self.evaluate_pair(pair_name, max_queries)
            all_results.extend(pair_results)
        
        return all_results


# =============================================================================
# 出力関数
# =============================================================================

def save_results_to_csv(results: List[RelaxationQueryResult], output_path: Path):
    """全結果をCSVに保存"""
    fieldnames = [
        'pair_name', 'query_file',
        # ソース
        'source_count', 'source_unique_count', 'source_success', 'source_error',
        # 翻訳
        'translation_success', 'translation_error',
        # 変換直後
        'translated_count', 'translated_empty', 'translated_error',
        # 緩和
        'relaxation_applied', 'relaxation_phase', 'relaxation_count',
        'relaxation_success', 'tried_phases', 'tried_phases_count', 'relaxation_error',
        # 総合判定
        'all_conditions_met',
        # 評価指標
        'tp', 'fp', 'fn', 'precision', 'recall', 'f1', 'information_loss',
        # クエリ本文
        'source_query', 'translated_query', 'relaxed_query',
    ]
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(result.to_csv_row())
    
    print(f"[保存] {output_path}")


def save_summary_markdown(results: List[RelaxationQueryResult], output_path: Path, elapsed_time: float):
    """サマリーMarkdownを保存（拡張版）"""
    if not results:
        return
    
    total = len(results)
    
    # 統計計算
    source_success = sum(1 for r in results if r.source_success)
    translation_success = sum(1 for r in results if r.translation_success)
    translated_empty = sum(1 for r in results if r.source_success and r.translated_empty)
    relaxation_applied = sum(1 for r in results if r.relaxation_applied)
    relaxation_success = sum(1 for r in results if r.relaxation_success)
    all_conditions_met = sum(1 for r in results if r.all_conditions_met)
    
    # 条件を満たすケースの平均指標
    met_results = [r for r in results if r.all_conditions_met]
    avg_precision = sum(r.precision for r in met_results) / len(met_results) if met_results else 0.0
    avg_recall = sum(r.recall for r in met_results) / len(met_results) if met_results else 0.0
    avg_f1 = sum(r.f1 for r in met_results) / len(met_results) if met_results else 0.0
    avg_info_loss = sum(r.information_loss for r in met_results) / len(met_results) if met_results else 0.0
    
    # Phase別統計
    phase_stats = {}
    for r in results:
        if r.all_conditions_met and r.relaxation_phase:
            phase = r.relaxation_phase
            if phase not in phase_stats:
                phase_stats[phase] = {'count': 0, 'f1_sum': 0.0, 'precision_sum': 0.0, 'recall_sum': 0.0, 'info_loss_sum': 0.0}
            phase_stats[phase]['count'] += 1
            phase_stats[phase]['f1_sum'] += r.f1
            phase_stats[phase]['precision_sum'] += r.precision
            phase_stats[phase]['recall_sum'] += r.recall
            phase_stats[phase]['info_loss_sum'] += r.information_loss
    
    # エラー分類統計
    error_stats = {
        'source_empty': sum(1 for r in results if not r.source_success),
        'translation_failed': sum(1 for r in results if r.source_success and not r.translation_success),
        'not_empty_after_translation': sum(1 for r in results if r.source_success and r.translation_success and not r.translated_empty),
        'relaxation_failed': sum(1 for r in results if r.source_success and r.translation_success and r.translated_empty and not r.relaxation_success),
    }
    
    # Markdown生成
    md = []
    md.append("# 緩和クエリ評価レポート\n")
    md.append(f"**評価日時**: {time.strftime('%Y年%m月%d日 %H:%M:%S')}\n")
    md.append(f"**処理時間**: {elapsed_time/60:.1f}分 ({elapsed_time:.1f}秒)\n")
    md.append("---\n")
    
    md.append("## 📊 全体統計\n")
    md.append(f"- **総クエリ数**: {total}\n")
    md.append(f"- **ソース非空（データ取得成功）**: {source_success}/{total} ({source_success/total*100:.1f}%)\n")
    md.append(f"- **翻訳成功**: {translation_success}/{total} ({translation_success/total*100:.1f}%)\n")
    md.append(f"- **変換直後空（条件2）**: {translated_empty}/{source_success} ({translated_empty/source_success*100:.1f}%)\n" if source_success > 0 else "")
    md.append(f"- **緩和適用**: {relaxation_applied}/{total}\n")
    md.append(f"- **緩和成功（クエリ回復）**: {relaxation_success}/{relaxation_applied} ({relaxation_success/relaxation_applied*100:.1f}%)\n" if relaxation_applied > 0 else "")
    
    md.append("\n### 🎯 3条件達成（成功ケース）\n")
    md.append(f"- **成功数**: {all_conditions_met}/{total} ({all_conditions_met/total*100:.1f}%)\n")
    md.append(f"- **平均Precision（適合率）**: {avg_precision*100:.2f}%\n")
    md.append(f"- **平均Recall（再現率）**: {avg_recall*100:.2f}%\n")
    md.append(f"- **平均F1**: {avg_f1*100:.2f}%\n")
    md.append(f"- **平均情報損失率**: {avg_info_loss*100:.2f}%\n")
    
    if phase_stats:
        md.append("\n### 📈 Phase別統計\n")
        md.append("| Phase | 成功数 | 割合 | 平均F1 | 平均Precision | 平均Recall | 平均情報損失 |\n")
        md.append("|-------|--------|------|--------|---------------|------------|---------------|\n")
        for phase in sorted(phase_stats.keys()):
            stats = phase_stats[phase]
            count = stats['count']
            pct = count / all_conditions_met * 100 if all_conditions_met > 0 else 0
            avg_f1_p = stats['f1_sum'] / count * 100 if count > 0 else 0
            avg_prec_p = stats['precision_sum'] / count * 100 if count > 0 else 0
            avg_rec_p = stats['recall_sum'] / count * 100 if count > 0 else 0
            avg_loss_p = stats['info_loss_sum'] / count * 100 if count > 0 else 0
            md.append(f"| {phase} | {count} | {pct:.1f}% | {avg_f1_p:.1f}% | {avg_prec_p:.1f}% | {avg_rec_p:.1f}% | {avg_loss_p:.1f}% |\n")
    
    md.append("\n### ❌ エラー分類統計\n")
    md.append("| エラー種別 | 件数 | 割合 |\n")
    md.append("|------------|------|------|\n")
    error_labels = {
        'source_empty': 'ソース空（データなし）',
        'translation_failed': '翻訳失敗',
        'not_empty_after_translation': '変換直後非空（緩和不要だった）',
        'relaxation_failed': '緩和失敗',
    }
    for key, label in error_labels.items():
        count = error_stats[key]
        pct = count / total * 100 if total > 0 else 0
        md.append(f"| {label} | {count} | {pct:.1f}% |\n")
    
    md.append("\n---\n")
    md.append("## 📈 ペア別統計\n")
    
    # ペア別集計
    by_pair = {}
    for r in results:
        if r.pair_name not in by_pair:
            by_pair[r.pair_name] = []
        by_pair[r.pair_name].append(r)
    
    # ペア別サマリーテーブル
    md.append("\n### ペア別サマリー\n")
    md.append("| ペア名 | クエリ数 | 成功数 | 成功率 | 平均F1 | 平均Precision | 平均情報損失 |\n")
    md.append("|--------|----------|--------|--------|--------|---------------|---------------|\n")
    
    for pair_name in sorted(by_pair.keys()):
        pair_results = by_pair[pair_name]
        pair_total = len(pair_results)
        pair_success = sum(1 for r in pair_results if r.all_conditions_met)
        pair_met = [r for r in pair_results if r.all_conditions_met]
        pair_avg_f1 = sum(r.f1 for r in pair_met) / len(pair_met) * 100 if pair_met else 0.0
        pair_avg_prec = sum(r.precision for r in pair_met) / len(pair_met) * 100 if pair_met else 0.0
        pair_avg_loss = sum(r.information_loss for r in pair_met) / len(pair_met) * 100 if pair_met else 0.0
        success_rate = pair_success / pair_total * 100 if pair_total > 0 else 0
        md.append(f"| {pair_name} | {pair_total} | {pair_success} | {success_rate:.0f}% | {pair_avg_f1:.1f}% | {pair_avg_prec:.1f}% | {pair_avg_loss:.1f}% |\n")
    
    # 各ペアの詳細
    for pair_name in sorted(by_pair.keys()):
        pair_results = by_pair[pair_name]
        pair_total = len(pair_results)
        pair_success = sum(1 for r in pair_results if r.all_conditions_met)
        pair_met = [r for r in pair_results if r.all_conditions_met]
        pair_avg_f1 = sum(r.f1 for r in pair_met) / len(pair_met) if pair_met else 0.0
        pair_avg_prec = sum(r.precision for r in pair_met) / len(pair_met) if pair_met else 0.0
        pair_avg_recall = sum(r.recall for r in pair_met) / len(pair_met) if pair_met else 0.0
        pair_avg_loss = sum(r.information_loss for r in pair_met) / len(pair_met) if pair_met else 0.0
        
        # Phase別内訳
        pair_phase_counts = {}
        for r in pair_results:
            if r.all_conditions_met and r.relaxation_phase:
                phase = r.relaxation_phase
                if phase not in pair_phase_counts:
                    pair_phase_counts[phase] = 0
                pair_phase_counts[phase] += 1
        
        md.append(f"\n### {pair_name}\n")
        md.append(f"- **クエリ数**: {pair_total}\n")
        md.append(f"- **成功**: {pair_success} ({pair_success/pair_total*100:.1f}%)\n")
        md.append(f"- **平均Precision**: {pair_avg_prec*100:.2f}%\n")
        md.append(f"- **平均Recall**: {pair_avg_recall*100:.2f}%\n")
        md.append(f"- **平均F1**: {pair_avg_f1*100:.2f}%\n")
        md.append(f"- **平均情報損失率**: {pair_avg_loss*100:.2f}%\n")
        
        if pair_phase_counts:
            md.append(f"- **Phase別内訳**: ")
            phase_strs = [f"{phase}: {count}" for phase, count in sorted(pair_phase_counts.items())]
            md.append(", ".join(phase_strs) + "\n")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(md)
    
    print(f"[保存] {output_path}")


def save_results_to_json(results: List[RelaxationQueryResult], output_dir: Path):
    """ペア別JSONを保存"""
    by_pair = {}
    for r in results:
        if r.pair_name not in by_pair:
            by_pair[r.pair_name] = []
        by_pair[r.pair_name].append(r.to_csv_row())
    
    for pair_name, pair_results in by_pair.items():
        json_path = output_dir / f'relaxation_query_{pair_name}.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(pair_results, f, indent=2, ensure_ascii=False)
        print(f"[保存] {json_path}")


# =============================================================================
# メイン関数
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='緩和クエリ評価プログラム（Relaxation Query Evaluator）'
    )
    parser.add_argument('pairs', nargs='*', help='評価するペア名')
    parser.add_argument('--all', '-a', action='store_true', help='全ペアを評価')
    parser.add_argument('--max-queries', '-n', type=int, default=None,
                        help='各ペアの最大クエリ数（デバッグ用）')
    parser.add_argument('--output', '-o', type=str, default='output/relaxation_test',
                        help='出力ディレクトリ')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='詳細なデバッグ出力を有効にする')
    parser.add_argument('--phases', type=str, default=None,
                        help="アブレーション用。実行フェーズをカンマ区切りで指定 "
                             "(例: 'L1,L3,L4a,L4b,L5' で no-L2)。未指定なら全フェーズ=従来挙動。"
                             "キー: L1,L2,L3,L4a,L4b,L5")
    parser.add_argument('--config-name', type=str, default=None,
                        help='run_config.json に記録する構成名（任意）')
    parser.add_argument('--rdfs-materialize', dest='rdfs_materialize', action='store_true',
                        help='Task E: rdfs5/7/9/11 の限定RDFS materializationをロード後グラフに適用（既定OFF・元データ不変）')
    args = parser.parse_args()

    # --phases のパース（未指定=None=全フェーズ）
    enabled_phases = None
    if args.phases:
        valid = {'L1', 'L2', 'L3', 'L4a', 'L4b', 'L5'}
        enabled_phases = set(p.strip() for p in args.phases.split(',') if p.strip())
        unknown = enabled_phases - valid
        if unknown:
            parser.error(f"未知のフェーズキー: {sorted(unknown)} (有効: {sorted(valid)})")
        print(f"[INFO] アブレーション: 有効フェーズ = {sorted(enabled_phases)}")
    
    # ペア名の決定
    if args.all:
        pair_names = None  # 自動検出
    elif args.pairs:
        pair_names = args.pairs
    else:
        # デフォルト: cmt-conference
        pair_names = ['cmt-conference']
        print(f"[INFO] デフォルトペア: {pair_names}")
    
    # 評価実行
    evaluator = RelaxationQueryEvaluator(PROJECT_ROOT, verbose=args.verbose,
                                         enabled_phases=enabled_phases,
                                         rdfs_materialize=args.rdfs_materialize)

    start_time = time.time()
    results = evaluator.evaluate_all_pairs(pair_names, max_queries=args.max_queries)
    elapsed_time = time.time() - start_time

    if results:
        # 出力ディレクトリ作成
        output_dir = PROJECT_ROOT / args.output
        output_dir.mkdir(parents=True, exist_ok=True)

        # 各種ファイル保存
        save_results_to_csv(results, output_dir / 'relaxation_query_results.csv')
        save_summary_markdown(results, output_dir / 'RELAXATION_QUERY_SUMMARY.md', elapsed_time)
        save_results_to_json(results, output_dir)

        # run_config.json（再現性）
        try:
            import subprocess as _sp, platform as _plat
            try:
                _commit = _sp.check_output(['git', 'rev-parse', 'HEAD'],
                                           cwd=str(PROJECT_ROOT),
                                           encoding='utf-8', errors='replace').strip()
            except Exception:
                _commit = None
            try:
                import rdflib as _rl
                _rlv = _rl.__version__
            except Exception:
                _rlv = None
            run_config = {
                'config_name': args.config_name,
                'script': 'evaluate_relaxation_test.py',
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'git_commit': _commit,
                'enabled_phases': sorted(enabled_phases) if enabled_phases else 'ALL',
                'phases_arg': args.phases,
                'pairs': pair_names if pair_names else 'AUTO(--all)',
                'max_queries': args.max_queries,
                'num_results': len(results),
                'wall_clock_sec': round(elapsed_time, 2),
                'rdflib_version': _rlv,
                'python_version': _plat.python_version(),
                'os': _plat.platform(),
                'rdfs_inference': False,
                'note': '手作り90件(9ペア×10)のL2アブレーション。cascading_relaxer本体は不変、'
                        'enabled_phasesでフェーズをスキップするのみ。',
            }
            with open(output_dir / 'run_config.json', 'w', encoding='utf-8') as f:
                json.dump(run_config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARNING] run_config.json 書き込み失敗: {e}")
        
        # 簡易サマリー表示
        total = len(results)
        success = sum(1 for r in results if r.all_conditions_met)
        print(f"\n{'='*80}")
        print(f"評価完了: {success}/{total} ({success/total*100:.1f}%) 成功")
        print(f"処理時間: {elapsed_time:.1f}秒")
        print(f"{'='*80}")
    else:
        print("\n[警告] 評価結果がありません")


if __name__ == '__main__':
    main()
