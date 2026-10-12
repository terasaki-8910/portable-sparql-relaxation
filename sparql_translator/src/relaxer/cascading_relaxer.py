#!/usr/bin/env python3
"""
Cascading Query Relaxer - カスケード型クエリ緩和システム

パイプライン型の順次適用により、Phase順序に従って段階的にクエリを緩和する。
分類アルゴリズムで失敗パターンを判定し情報として記録するが、
緩和自体はPhase 1からPhase 5まで順次パイプラインで適用する。

Phases:
    Phase 1 (Category C): 残留トリプル削除 - ソースURIを含むトリプルを削除
    Phase 2 (Category D): FILTER緩和 - FILTER句を削除
    Phase 3 (Category E): OPTIONAL化 - 複数トリプルをOPTIONAL化
    Phase 4a (Category F1): クラス階層緩和 - rdfs:subClassOfに基づき上位クラスへ一般化
    Phase 4b (Category F2): プロパティ階層緩和 - rdfs:subPropertyOfに基づき上位プロパティへ一般化
    Phase 5 (Category F3): rdf:type削除 - rdf:type制約を削除（フォールバック）

使用方法:
    from sparql_translator.src.relaxer.cascading_relaxer import CascadingRelaxer
    
    relaxer = CascadingRelaxer()
    result = relaxer.relax_query(query, source_ont, target_ont, executor_func)
"""

import os
import re
import logging
from typing import List, Tuple, Optional, Callable, Dict, Any, Set
from dataclasses import dataclass, field
from itertools import combinations

# OntologyHierarchyParser をインポート
from sparql_translator.src.relaxer.ontology_hierarchy import OntologyHierarchyParser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ParsedQuery:
    """パース済みSPARQLクエリ"""
    prefix_section: str = ""
    select_clause: str = ""
    where_content: str = ""
    order_by: str = ""
    limit: str = ""
    offset: str = ""
    group_by: str = ""
    having: str = ""
    original: str = ""
    
    def rebuild(self, new_where_content: str = None) -> str:
        """クエリを再構築"""
        where = new_where_content if new_where_content is not None else self.where_content
        
        parts = []
        if self.prefix_section.strip():
            parts.append(self.prefix_section.strip())
        if self.select_clause.strip():
            parts.append(self.select_clause.strip())
        
        # WHERE句
        where_clean = where.strip()
        parts.append(f"WHERE {{\n  {where_clean}\n}}")
        
        # 修飾句
        if self.group_by.strip():
            parts.append(self.group_by.strip())
        if self.having.strip():
            parts.append(self.having.strip())
        if self.order_by.strip():
            parts.append(self.order_by.strip())
        if self.limit.strip():
            parts.append(self.limit.strip())
        if self.offset.strip():
            parts.append(self.offset.strip())
        
        return "\n".join(parts)


# データセットプレフィックス対応表
DATASET_PREFIXES = {
    'cmt': {
        'prefixes': ['cmt:'],
        'namespaces': ['http://cmt#'],
    },
    'conference': {
        'prefixes': ['conference:'],
        'namespaces': ['http://conference#'],
    },
    'confOf': {
        'prefixes': ['confOf:'],
        'namespaces': ['http://confOf#'],
    },
    'edas': {
        'prefixes': ['edas:'],
        'namespaces': ['http://edas#'],
    },
    'ekaw': {
        'prefixes': ['ekaw:'],
        'namespaces': ['http://ekaw#'],
    },
    'gbo': {
        'prefixes': ['gbo:'],
        'namespaces': ['http://gbo#'],
    },
    'gmo': {
        'prefixes': ['gmo:'],
        'namespaces': ['http://gmo#'],
    },
    'agro': {
        'prefixes': ['agro:'],
        'namespaces': ['http://ontology.irstea.fr/agronomictaxon/'],
    },
    'dbpedia': {
        'prefixes': ['dbo:', 'dbp:', 'dbr:'],
        'namespaces': ['http://dbpedia.org/'],
    },
}


@dataclass
class RelaxationResult:
    """緩和結果"""
    success: bool
    phase: str
    original_query: str
    relaxed_query: str
    result_count: int
    all_tried_phases: List[str]
    best_results: List[Dict[str, Any]]  # 各フェーズでの最良結果


@dataclass
class PhaseResult:
    """各フェーズの結果"""
    phase_name: str
    candidates: List[str]
    best_candidate: Optional[str]
    best_count: int
    executed: bool


class CascadingRelaxer:
    """
    カスケード型クエリ緩和クラス
    
    決定木の順序に従い、各Phaseを順番に試行。
    成功後も次のPhaseを試行し、最も適切な結果を選択。
    """
    
    def __init__(self, verbose: bool = True, schema_directory: Optional[str] = None):
        self.verbose = verbose
        
        # スキーマディレクトリを自動検出または指定
        if schema_directory is None:
            # デフォルトのスキーマディレクトリを検出
            current_file = os.path.abspath(__file__)
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file))))
            schema_directory = os.path.join(project_root, 'data', 'datasets')
        
        self.schema_directory = schema_directory
        self.ontology_hierarchy = OntologyHierarchyParser(schema_directory)
        logger.info(f"CascadingRelaxer initialized with schema directory: {schema_directory}")
    
    def _parse_query(self, query: str) -> ParsedQuery:
        """
        SPARQLクエリを構成要素に分解
        
        Args:
            query: SPARQLクエリ文字列
            
        Returns:
            ParsedQuery: パース結果
        """
        parsed = ParsedQuery(original=query)
        
        # PREFIX宣言を抽出
        prefix_lines = []
        remaining_lines = []
        for line in query.split('\n'):
            if line.strip().upper().startswith('PREFIX'):
                prefix_lines.append(line)
            else:
                remaining_lines.append(line)
        
        parsed.prefix_section = '\n'.join(prefix_lines)
        remaining = '\n'.join(remaining_lines)
        
        # SELECT句を抽出
        select_match = re.search(
            r'(SELECT\s+(?:DISTINCT\s+)?(?:\*|(?:\?[\w]+\s*)+))',
            remaining,
            re.IGNORECASE
        )
        if select_match:
            parsed.select_clause = select_match.group(1).strip()
        
        # WHERE句の内容を抽出（ネストしたブレースを考慮）
        where_start = re.search(r'WHERE\s*\{', remaining, re.IGNORECASE)
        if where_start:
            start_pos = where_start.end()
            depth = 1
            end_pos = start_pos
            
            while end_pos < len(remaining) and depth > 0:
                if remaining[end_pos] == '{':
                    depth += 1
                elif remaining[end_pos] == '}':
                    depth -= 1
                end_pos += 1
            
            parsed.where_content = remaining[start_pos:end_pos-1].strip()
            
            # WHERE句の後の修飾句を抽出
            after_where = remaining[end_pos:].strip()
            
            # GROUP BY
            group_match = re.search(r'(GROUP\s+BY\s+[\?\w\s,]+)', after_where, re.IGNORECASE)
            if group_match:
                parsed.group_by = group_match.group(1).strip()
            
            # HAVING
            having_match = re.search(r'(HAVING\s*\([^)]+\))', after_where, re.IGNORECASE)
            if having_match:
                parsed.having = having_match.group(1).strip()
            
            # ORDER BY
            order_match = re.search(r'(ORDER\s+BY\s+[^\n]+)', after_where, re.IGNORECASE)
            if order_match:
                parsed.order_by = order_match.group(1).strip()
            
            # LIMIT
            limit_match = re.search(r'(LIMIT\s+\d+)', after_where, re.IGNORECASE)
            if limit_match:
                parsed.limit = limit_match.group(1).strip()
            
            # OFFSET
            offset_match = re.search(r'(OFFSET\s+\d+)', after_where, re.IGNORECASE)
            if offset_match:
                parsed.offset = offset_match.group(1).strip()
        
        return parsed
    
    def relax_query(
        self,
        query: str,
        source_ont: str,
        target_ont: str,
        executor: Callable[[str], Dict[str, Any]],
        max_results_threshold: int = 100000,
        enabled_phases: Optional[Set[str]] = None
    ) -> RelaxationResult:
        """
        クエリを段階的に緩和し、最適な結果を返す

        Args:
            query: 元のSPARQLクエリ（output_query）
            source_ont: ソースオントロジー名
            target_ont: ターゲットオントロジー名
            executor: クエリ実行関数 (query) -> {'success': bool, 'count': int, 'error': str}
            max_results_threshold: 結果件数がこれを超えると過緩和とみなす
            enabled_phases: アブレーション用。実行するフェーズの集合
                （キー: 'L1','L2','L3','L4a','L4b','L5'）。None なら全フェーズ（既定・従来と同一挙動）。
                各フェーズ内部のロジック・候補生成・閾値は一切変更しない。無効化したフェーズは
                _execute_phase を呼ばずスキップするのみ（カスケードの current_query は前段の
                実行済みフェーズの出力のまま次段へ渡る）。

        Returns:
            RelaxationResult: 緩和結果
        """
        def _enabled(key: str) -> bool:
            return enabled_phases is None or key in enabled_phases

        all_tried_phases = []
        best_results = []
        current_query = query
        current_best_count = 0
        current_best_query = query
        current_best_phase = "Original"

        # Phase 1: 残留トリプル削除 (Category C)
        if _enabled('L1'):
            phase1_result = self._execute_phase(
                phase_name="Phase1_ResidualDeletion",
                candidates_func=lambda q: self._phase1_remove_residual_triples(q, source_ont),
                current_query=current_query,
                executor=executor,
                max_results_threshold=max_results_threshold
            )
            all_tried_phases.append(phase1_result.phase_name)
            best_results.append({
                'phase': phase1_result.phase_name,
                'best_count': phase1_result.best_count,
                'candidate_count': len(phase1_result.candidates),
                'executed': phase1_result.executed
            })

            if phase1_result.best_count > 0 and (phase1_result.best_count < current_best_count or current_best_count == 0):
                current_best_count = phase1_result.best_count
                current_best_query = phase1_result.best_candidate
                current_best_phase = phase1_result.phase_name

            # 成功しても次フェーズを継続（さらなる改善を探す）
            # ただし、成功した場合はそのクエリをベースに次を試す
            if phase1_result.best_candidate:
                current_query = phase1_result.best_candidate

        # Phase 2: FILTER緩和 (Category D)
        if _enabled('L2'):
            phase2_result = self._execute_phase(
                phase_name="Phase2_FilterRemoval",
                candidates_func=lambda q: self._phase2_remove_filter(q),
                current_query=current_query,
                executor=executor,
                max_results_threshold=max_results_threshold
            )
            all_tried_phases.append(phase2_result.phase_name)
            best_results.append({
                'phase': phase2_result.phase_name,
                'best_count': phase2_result.best_count,
                'candidate_count': len(phase2_result.candidates),
                'executed': phase2_result.executed
            })

            if phase2_result.best_count > 0:
                if current_best_count == 0 or (phase2_result.best_count < current_best_count):
                    current_best_count = phase2_result.best_count
                    current_best_query = phase2_result.best_candidate
                    current_best_phase = phase2_result.phase_name
                current_query = phase2_result.best_candidate

        # Phase 3: OPTIONAL化 (Category E)
        if _enabled('L3'):
            phase3_result = self._execute_phase(
                phase_name="Phase3_Optionalization",
                candidates_func=lambda q: self._phase3_optionalize_triples(q),
                current_query=current_query,
                executor=executor,
                max_results_threshold=max_results_threshold
            )
            all_tried_phases.append(phase3_result.phase_name)
            best_results.append({
                'phase': phase3_result.phase_name,
                'best_count': phase3_result.best_count,
                'candidate_count': len(phase3_result.candidates),
                'executed': phase3_result.executed
            })

            if phase3_result.best_count > 0:
                if current_best_count == 0 or (phase3_result.best_count < current_best_count):
                    current_best_count = phase3_result.best_count
                    current_best_query = phase3_result.best_candidate
                    current_best_phase = phase3_result.phase_name
                current_query = phase3_result.best_candidate

        # Phase 4a: クラス階層緩和 - rdfs:subClassOfに基づく一般化
        if _enabled('L4a'):
            phase4a_result = self._execute_phase(
                phase_name="Phase4a_ClassHierarchy",
                candidates_func=lambda q: self._phase4a_class_hierarchy_relaxation(q, target_ont),
                current_query=current_query,
                executor=executor,
                max_results_threshold=max_results_threshold
            )
            all_tried_phases.append(phase4a_result.phase_name)
            best_results.append({
                'phase': phase4a_result.phase_name,
                'best_count': phase4a_result.best_count,
                'candidate_count': len(phase4a_result.candidates),
                'executed': phase4a_result.executed
            })

            if phase4a_result.best_count > 0:
                if current_best_count == 0 or (phase4a_result.best_count < current_best_count):
                    current_best_count = phase4a_result.best_count
                    current_best_query = phase4a_result.best_candidate
                    current_best_phase = phase4a_result.phase_name
                current_query = phase4a_result.best_candidate

        # Phase 4b: プロパティ階層緩和 - rdfs:subPropertyOfに基づく一般化
        if _enabled('L4b'):
            phase4b_result = self._execute_phase(
                phase_name="Phase4b_PropertyHierarchy",
                candidates_func=lambda q: self._phase4b_property_hierarchy_relaxation(q, target_ont),
                current_query=current_query,
                executor=executor,
                max_results_threshold=max_results_threshold
            )
            all_tried_phases.append(phase4b_result.phase_name)
            best_results.append({
                'phase': phase4b_result.phase_name,
                'best_count': phase4b_result.best_count,
                'candidate_count': len(phase4b_result.candidates),
                'executed': phase4b_result.executed
            })

            if phase4b_result.best_count > 0:
                if current_best_count == 0 or (phase4b_result.best_count < current_best_count):
                    current_best_count = phase4b_result.best_count
                    current_best_query = phase4b_result.best_candidate
                    current_best_phase = phase4b_result.phase_name
                current_query = phase4b_result.best_candidate

        # Phase 5: rdf:type削除 (フォールバック - 階層緩和が効かない場合)
        if _enabled('L5'):
            phase5_result = self._execute_phase(
                phase_name="Phase5_TypeRemoval",
                candidates_func=lambda q: self._phase5_remove_rdf_type(q),
                current_query=current_query,
                executor=executor,
                max_results_threshold=max_results_threshold
            )
            all_tried_phases.append(phase5_result.phase_name)
            best_results.append({
                'phase': phase5_result.phase_name,
                'best_count': phase5_result.best_count,
                'candidate_count': len(phase5_result.candidates),
                'executed': phase5_result.executed
            })

            if phase5_result.best_count > 0:
                if current_best_count == 0 or (phase5_result.best_count < current_best_count):
                    current_best_count = phase5_result.best_count
                    current_best_query = phase5_result.best_candidate
                    current_best_phase = phase5_result.phase_name
                current_query = phase5_result.best_candidate

        return RelaxationResult(
            success=current_best_count > 0,
            phase=current_best_phase,
            original_query=query,
            relaxed_query=current_best_query if current_best_count > 0 else query,
            result_count=current_best_count,
            all_tried_phases=all_tried_phases,
            best_results=best_results
        )
    
    def _execute_phase(
        self,
        phase_name: str,
        candidates_func: Callable[[str], List[str]],
        current_query: str,
        executor: Callable[[str], Dict[str, Any]],
        max_results_threshold: int
    ) -> PhaseResult:
        """
        単一フェーズを実行
        
        Args:
            phase_name: フェーズ名
            candidates_func: 緩和候補生成関数
            current_query: 現在のクエリ
            executor: クエリ実行関数
            max_results_threshold: 過緩和判定閾値
            
        Returns:
            PhaseResult: フェーズ実行結果
        """
        if self.verbose:
            logger.info(f"  Executing {phase_name}...")
        
        try:
            candidates = candidates_func(current_query)
        except Exception as e:
            logger.warning(f"  {phase_name} candidate generation failed: {e}")
            return PhaseResult(
                phase_name=phase_name,
                candidates=[],
                best_candidate=None,
                best_count=0,
                executed=False
            )
        
        if not candidates:
            if self.verbose:
                logger.info(f"    No candidates generated for {phase_name}")
            return PhaseResult(
                phase_name=phase_name,
                candidates=[],
                best_candidate=None,
                best_count=0,
                executed=True
            )
        
        if self.verbose:
            logger.info(f"    Generated {len(candidates)} candidates")
        
        # 各候補を実行し、最小非ゼロ結果を選択
        best_candidate = None
        best_count = 0
        
        for i, candidate in enumerate(candidates):
            try:
                result = executor(candidate)
                if result.get('success', False):
                    count = result.get('count', 0)
                    if count > 0 and count < max_results_threshold:
                        # 最小非ゼロ結果を選択（0件除く）
                        if best_count == 0 or count < best_count:
                            best_count = count
                            best_candidate = candidate
                            if self.verbose:
                                logger.info(f"    Candidate {i+1}: {count} results (new best)")
                        else:
                            if self.verbose:
                                logger.info(f"    Candidate {i+1}: {count} results")
                    elif count >= max_results_threshold:
                        if self.verbose:
                            logger.info(f"    Candidate {i+1}: {count} results (over-relaxed)")
                    else:
                        if self.verbose:
                            logger.info(f"    Candidate {i+1}: 0 results")
                else:
                    if self.verbose:
                        logger.info(f"    Candidate {i+1}: execution failed - {result.get('error', 'unknown')}")
            except Exception as e:
                if self.verbose:
                    logger.warning(f"    Candidate {i+1}: error - {e}")
        
        return PhaseResult(
            phase_name=phase_name,
            candidates=candidates,
            best_candidate=best_candidate,
            best_count=best_count,
            executed=True
        )
    
    # ========================================
    # Phase 1: 残留トリプル削除
    # ========================================
    
    def _phase1_remove_residual_triples(self, query: str, source_ont: str) -> List[str]:
        """
        Phase 1: ソースURIが残留しているトリプルを削除
        
        Args:
            query: SPARQLクエリ
            source_ont: ソースオントロジー名
            
        Returns:
            緩和候補クエリのリスト
        """
        candidates = []
        
        # ソースURIを検出
        residual_uris = self._detect_source_uris(query, source_ont)
        
        if not residual_uris:
            return candidates
        
        # クエリをパース
        parsed = self._parse_query(query)
        if not parsed.where_content:
            return candidates
        
        # トリプルを展開（Turtle記法を展開）
        triples = self._expand_turtle_triples(parsed.where_content)
        
        if not triples:
            return candidates
        
        # 残留URIを含むトリプルを特定して削除
        kept_triples = []
        removed_any = False
        
        for triple in triples:
            contains_residual = False
            for uri in residual_uris:
                if uri in triple:
                    contains_residual = True
                    break
            
            if contains_residual:
                removed_any = True
            else:
                kept_triples.append(triple)
        
        if removed_any and kept_triples:
            new_where = '\n  '.join(kept_triples)
            new_query = parsed.rebuild(new_where)
            candidates.append(new_query)
        
        return candidates
    
    def _expand_turtle_triples(self, where_content: str) -> List[str]:
        """
        Turtle記法（; ,）を展開して完全なトリプルのリストを返す
        
        例: ?s a <Class> ; <p1> ?o1 ; <p2> ?o2 .
        →  [?s a <Class> ., ?s <p1> ?o1 ., ?s <p2> ?o2 .]
        
        Args:
            where_content: WHERE句の内容
            
        Returns:
            完全なトリプルのリスト
        """
        triples = []
        
        # FILTER句を一時的に除去
        where_clean = re.sub(r'FILTER\s*\([^)]*\)', '', where_content, flags=re.IGNORECASE)
        where_clean = re.sub(r'FILTER\s+\w+\s*\([^)]*\)', '', where_clean, flags=re.IGNORECASE)
        
        # OPTIONALブロックを一時的に除去（別途処理）
        where_clean = re.sub(r'OPTIONAL\s*\{[^}]*\}', '', where_clean, flags=re.IGNORECASE)
        
        # 改行とタブをスペースに正規化し、連続スペースを1つに
        where_clean = re.sub(r'[\n\r\t]+', ' ', where_clean)
        where_clean = re.sub(r'\s+', ' ', where_clean)
        where_clean = where_clean.strip()
        
        # {} を除去
        where_clean = where_clean.strip('{}').strip()
        
        if not where_clean:
            return triples
        
        # トークンに分割（URI、リテラル、記号を考慮）
        all_tokens = self._tokenize_sparql_content(where_clean)
        
        if not all_tokens:
            return triples
        
        # トークンを処理
        current_subject = None
        current_predicate = None
        i = 0
        
        while i < len(all_tokens):
            token = all_tokens[i]
            
            # 区切り文字の処理
            if token == '.':
                # ピリオド: 主語をリセット
                current_subject = None
                current_predicate = None
                i += 1
                continue
            elif token == ';':
                # セミコロン: 主語は維持、述語をリセット
                current_predicate = None
                i += 1
                continue
            elif token == ',':
                # カンマ: 主語と述語を維持
                i += 1
                continue
            elif token in ['{', '}']:
                i += 1
                continue
            
            # トリプルを構築
            if current_subject is None:
                # 新しい主語
                if i + 2 < len(all_tokens):
                    current_subject = token
                    current_predicate = all_tokens[i + 1]
                    obj = all_tokens[i + 2]
                    # 次のトークンが区切り文字でないことを確認
                    if current_predicate not in ['.', ';', ',', '{', '}'] and obj not in ['.', ';', ',', '{', '}']:
                        triples.append(f"{current_subject} {current_predicate} {obj} .")
                        i += 3
                    else:
                        i += 1
                else:
                    i += 1
            elif current_predicate is None:
                # 継続（;の後）: 述語と目的語
                if i + 1 < len(all_tokens):
                    current_predicate = token
                    obj = all_tokens[i + 1]
                    if obj not in ['.', ';', ',', '{', '}']:
                        triples.append(f"{current_subject} {current_predicate} {obj} .")
                        i += 2
                    else:
                        i += 1
                else:
                    i += 1
            else:
                # 継続（,の後）: 目的語のみ
                obj = token
                if obj not in ['.', ';', ',', '{', '}']:
                    triples.append(f"{current_subject} {current_predicate} {obj} .")
                i += 1
        
        return triples
    
    def _tokenize_sparql_content(self, content: str) -> List[str]:
        """
        SPARQLコンテンツをトークンに分割（URI、リテラル、区切り文字を考慮）
        
        Args:
            content: SPARQLコンテンツ
            
        Returns:
            トークンのリスト
        """
        tokens = []
        current_token = ""
        in_uri = False
        in_string = False
        string_char = None
        
        i = 0
        while i < len(content):
            char = content[i]
            
            if in_uri:
                current_token += char
                if char == '>':
                    in_uri = False
                    tokens.append(current_token)
                    current_token = ""
            elif in_string:
                current_token += char
                if char == string_char and (i == 0 or content[i-1] != '\\'):
                    in_string = False
            elif char == '<':
                if current_token:
                    tokens.append(current_token)
                    current_token = ""
                current_token = char
                in_uri = True
            elif char in '"\'':
                in_string = True
                string_char = char
                current_token += char
            elif char in ' \t':
                if current_token:
                    tokens.append(current_token)
                    current_token = ""
            elif char in '.;,{}':
                # 区切り文字を個別トークンとして追加
                if current_token:
                    tokens.append(current_token)
                    current_token = ""
                tokens.append(char)
            else:
                current_token += char
            
            i += 1
        
        if current_token:
            tokens.append(current_token)
        
        return tokens
    
    def _detect_source_uris(self, query: str, source_ont: str) -> List[str]:
        """ソースオントロジーのURIを検出"""
        residuals = []
        source_info = DATASET_PREFIXES.get(source_ont, {'prefixes': [], 'namespaces': []})
        
        # PREFIX宣言行を除外
        query_body = self._remove_prefix_lines(query)
        
        # プレフィックス形式の検出
        for prefix in source_info['prefixes']:
            prefix_clean = prefix.rstrip(':')
            pattern = rf'\b{re.escape(prefix_clean)}:[\w]+'
            matches = re.findall(pattern, query_body)
            residuals.extend(matches)
        
        # 完全URI形式の検出
        for namespace in source_info['namespaces']:
            pattern = rf'<{re.escape(namespace)}[^>]*>'
            matches = re.findall(pattern, query_body)
            residuals.extend(matches)
        
        return list(set(residuals))
    
    def _remove_prefix_lines(self, query: str) -> str:
        """PREFIX宣言行を除外"""
        lines = query.split('\n')
        non_prefix_lines = [line for line in lines if not line.strip().upper().startswith('PREFIX')]
        return '\n'.join(non_prefix_lines)
    
    # ========================================
    # Phase 2: FILTER削除
    # ========================================
    
    def _phase2_remove_filter(self, query: str) -> List[str]:
        """
        Phase 2: FILTER句を削除
        
        Args:
            query: SPARQLクエリ
            
        Returns:
            緩和候補クエリのリスト
        """
        candidates = []
        
        parsed = self._parse_query(query)
        if not parsed.where_content:
            return candidates
        
        if not re.search(r'FILTER', parsed.where_content, re.IGNORECASE):
            return candidates
        
        # FILTER句を行単位で削除（よりシンプルで確実な方法）
        lines = parsed.where_content.split('\n')
        new_lines = []
        for line in lines:
            # FILTERを含む行をスキップ
            if not re.search(r'\bFILTER\b', line, re.IGNORECASE):
                new_lines.append(line)
        
        new_where = '\n'.join(new_lines)
        
        # 空行を整理
        lines = [l for l in new_where.split('\n') if l.strip()]
        new_where = '\n  '.join(lines)
        
        if new_where.strip():
            new_query = parsed.rebuild(new_where)
            candidates.append(new_query)
        
        return candidates
    
    # ========================================
    # Phase 3: OPTIONAL化
    # ========================================
    
    def _phase3_optionalize_triples(self, query: str) -> List[str]:
        """
        Phase 3: トリプルパターンをOPTIONAL化
        
        複数のトリプルがある場合、1つずつOPTIONAL化を試みる
        
        Args:
            query: SPARQLクエリ
            
        Returns:
            緩和候補クエリのリスト
        """
        candidates = []
        
        parsed = self._parse_query(query)
        if not parsed.where_content:
            return candidates
        
        # UNION句を含むクエリはスキップ（構文が複雑すぎるため）
        if re.search(r'\bunion\b', parsed.where_content, re.IGNORECASE):
            if self.verbose:
                logger.info("    Skipping Phase3 for UNION query")
            return candidates
        
        # トリプルパターンを展開
        triples = self._expand_turtle_triples(parsed.where_content)
        
        if len(triples) < 2:
            return candidates  # トリプルが2つ未満なら対象外
        
        # 単一トリプルのOPTIONAL化
        for i, triple in enumerate(triples):
            other_triples = triples[:i] + triples[i+1:]
            if other_triples:
                # 必須トリプル + OPTIONAL
                required_part = '\n  '.join(other_triples)
                optional_part = f"OPTIONAL {{ {triple} }}"
                new_where = f"{required_part}\n  {optional_part}"
                new_query = parsed.rebuild(new_where)
                candidates.append(new_query)
        
        # 3つ以上のトリプルがある場合、2つの組み合わせでOPTIONAL化
        if len(triples) >= 3:
            for combo in combinations(range(len(triples)), 2):
                optional_triples = [triples[i] for i in combo]
                required_triples = [triples[i] for i in range(len(triples)) if i not in combo]
                
                if required_triples:
                    required_part = '\n  '.join(required_triples)
                    optional_part = f"OPTIONAL {{ {' '.join(optional_triples)} }}"
                    new_where = f"{required_part}\n  {optional_part}"
                    new_query = parsed.rebuild(new_where)
                    candidates.append(new_query)
        
        return candidates[:20]  # 最大20候補に制限
    
    # ========================================
    # Phase 4a: クラス階層緩和 (rdfs:subClassOfベース)
    # ========================================
    
    def _phase4a_class_hierarchy_relaxation(self, query: str, target_ont: str) -> List[str]:
        """
        Phase 4a: rdfs:subClassOfに基づくクラス階層緩和
        
        rdf:typeトリプルに含まれるクラスを、上位クラスに置き換える。
        1レベルずつ上位へ一般化していく（Option A）。
        
        Args:
            query: SPARQLクエリ
            target_ont: ターゲットオントロジー名
            
        Returns:
            緩和候補クエリのリスト
        """
        candidates = []
        
        parsed = self._parse_query(query)
        if not parsed.where_content:
            return candidates
        
        # トリプルを展開
        triples = self._expand_turtle_triples(parsed.where_content)
        
        if not triples:
            return candidates
        
        # rdf:typeトリプルを検索
        type_triple_indices = []
        for i, triple in enumerate(triples):
            if re.search(r'\s+rdf:type\s+', triple, re.IGNORECASE) or \
               re.search(r'\s+a\s+[<\?\w]', triple) or \
               'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' in triple:
                type_triple_indices.append(i)
        
        if not type_triple_indices:
            return candidates
        
        # 各rdf:typeトリプルについて階層緩和を試みる
        for idx in type_triple_indices:
            triple = triples[idx]
            
            # トリプルからクラスURIを抽出
            class_uri = self._extract_class_from_type_triple(triple, target_ont)
            
            if not class_uri:
                continue
            
            # 上位クラスを取得（1レベルずつ）
            parent_classes = self.ontology_hierarchy.get_parent_classes(target_ont, class_uri)
            
            for parent_class in parent_classes:
                # owl:ThingやRDFS基底クラスは除外
                if 'owl#Thing' in parent_class or 'owl:Thing' in parent_class:
                    continue
                if 'rdfs#Resource' in parent_class or 'rdfs:Resource' in parent_class:
                    continue
                
                # 新しいトリプルを生成
                new_triple = self._replace_class_in_triple(triple, class_uri, parent_class, target_ont)
                
                if new_triple and new_triple != triple:
                    new_triples = triples.copy()
                    new_triples[idx] = new_triple
                    new_where = '\n  '.join(new_triples)
                    new_query = parsed.rebuild(new_where)
                    candidates.append(new_query)
        
        return candidates[:15]  # 最大15候補に制限
    
    def _extract_class_from_type_triple(self, triple: str, target_ont: str) -> Optional[str]:
        """
        rdf:typeトリプルからクラスURIを抽出
        
        Args:
            triple: トリプル文字列
            target_ont: ターゲットオントロジー名
            
        Returns:
            クラスURI（フル形式）
        """
        # パターン: ?x rdf:type <FullURI>
        match = re.search(r'rdf:type\s+<([^>]+)>', triple, re.IGNORECASE)
        if match:
            return match.group(1)
        
        # パターン: ?x a <FullURI>
        match = re.search(r'\s+a\s+<([^>]+)>', triple)
        if match:
            return match.group(1)
        
        # パターン: ?x rdf:type prefix:LocalName
        match = re.search(r'rdf:type\s+(\w+):(\w+)', triple, re.IGNORECASE)
        if match:
            prefix = match.group(1)
            local = match.group(2)
            # プレフィックスを解決
            namespace = self._get_namespace_for_prefix(prefix, target_ont)
            if namespace:
                return f"{namespace}{local}"
        
        # パターン: ?x a prefix:LocalName
        match = re.search(r'\s+a\s+(\w+):(\w+)', triple)
        if match:
            prefix = match.group(1)
            local = match.group(2)
            namespace = self._get_namespace_for_prefix(prefix, target_ont)
            if namespace:
                return f"{namespace}{local}"
        
        return None
    
    def _get_namespace_for_prefix(self, prefix: str, target_ont: str) -> Optional[str]:
        """
        プレフィックスから名前空間を取得
        
        Args:
            prefix: プレフィックス名
            target_ont: ターゲットオントロジー名
            
        Returns:
            名前空間URI
        """
        # よく使われるプレフィックス
        common_prefixes = {
            'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
            'rdfs': 'http://www.w3.org/2000/01/rdf-schema#',
            'owl': 'http://www.w3.org/2002/07/owl#',
            'xsd': 'http://www.w3.org/2001/XMLSchema#',
        }
        
        if prefix in common_prefixes:
            return common_prefixes[prefix]
        
        # オントロジー固有のプレフィックス
        if prefix.lower() == target_ont.lower():
            return f"http://{target_ont}#"
        
        # DATASET_PREFIXESから検索
        for ont_name, info in DATASET_PREFIXES.items():
            if ont_name.lower() == prefix.lower():
                return info['namespaces'][0] if info['namespaces'] else None
        
        return None
    
    def _replace_class_in_triple(self, triple: str, old_class: str, new_class: str, target_ont: str) -> Optional[str]:
        """
        トリプル内のクラスを置換
        
        Args:
            triple: 元のトリプル
            old_class: 置換するクラスURI
            new_class: 新しいクラスURI
            target_ont: ターゲットオントロジー名
            
        Returns:
            置換後のトリプル
        """
        # フルURI形式で置換
        if f"<{old_class}>" in triple:
            return triple.replace(f"<{old_class}>", f"<{new_class}>")
        
        # プレフィックス形式で置換
        # old_classからローカル名を抽出
        old_local = old_class.split('#')[-1] if '#' in old_class else old_class.split('/')[-1]
        new_local = new_class.split('#')[-1] if '#' in new_class else new_class.split('/')[-1]
        
        # パターン: prefix:LocalName
        for prefix in [target_ont, target_ont.lower()]:
            old_prefixed = f"{prefix}:{old_local}"
            new_prefixed = f"{prefix}:{new_local}"
            if old_prefixed in triple:
                return triple.replace(old_prefixed, new_prefixed)
        
        # 大文字小文字を無視した検索
        pattern = re.compile(re.escape(old_local), re.IGNORECASE)
        if pattern.search(triple):
            return pattern.sub(new_local, triple)
        
        return None
    
    # ========================================
    # Phase 4b: プロパティ階層緩和 (rdfs:subPropertyOfベース)
    # ========================================
    
    def _phase4b_property_hierarchy_relaxation(self, query: str, target_ont: str) -> List[str]:
        """
        Phase 4b: rdfs:subPropertyOfに基づくプロパティ階層緩和
        
        述語（プロパティ）を上位プロパティに置き換える。
        1レベルずつ上位へ一般化していく（Option A）。
        
        Args:
            query: SPARQLクエリ
            target_ont: ターゲットオントロジー名
            
        Returns:
            緩和候補クエリのリスト
        """
        candidates = []
        
        parsed = self._parse_query(query)
        if not parsed.where_content:
            return candidates
        
        # トリプルを展開
        triples = self._expand_turtle_triples(parsed.where_content)
        
        if not triples:
            return candidates
        
        # 各トリプルの述語を抽出し、階層緩和を試みる
        for i, triple in enumerate(triples):
            # rdf:typeは除外（Phase 4aで処理済み）
            if re.search(r'\s+rdf:type\s+', triple, re.IGNORECASE) or \
               re.search(r'\s+a\s+[<\?\w]', triple):
                continue
            
            # 述語を抽出
            property_uri = self._extract_property_from_triple(triple, target_ont)
            
            if not property_uri:
                continue
            
            # 上位プロパティを取得
            parent_properties = self.ontology_hierarchy.get_parent_properties(target_ont, property_uri)
            
            for parent_property in parent_properties:
                # 新しいトリプルを生成
                new_triple = self._replace_property_in_triple(triple, property_uri, parent_property, target_ont)
                
                if new_triple and new_triple != triple:
                    new_triples = triples.copy()
                    new_triples[i] = new_triple
                    new_where = '\n  '.join(new_triples)
                    new_query = parsed.rebuild(new_where)
                    candidates.append(new_query)
        
        return candidates[:15]  # 最大15候補に制限
    
    def _extract_property_from_triple(self, triple: str, target_ont: str) -> Optional[str]:
        """
        トリプルから述語（プロパティ）URIを抽出
        
        Args:
            triple: トリプル文字列
            target_ont: ターゲットオントロジー名
            
        Returns:
            プロパティURI
        """
        # 標準的なトリプルパターンを解析: ?s predicate ?o または ?s predicate "literal"
        # パターン: ?s <FullURI> ?o
        match = re.search(r'\?\w+\s+<([^>]+)>\s+', triple)
        if match:
            return match.group(1)
        
        # パターン: ?s prefix:localName ?o
        match = re.search(r'\?\w+\s+(\w+):(\w+)\s+', triple)
        if match:
            prefix = match.group(1)
            local = match.group(2)
            namespace = self._get_namespace_for_prefix(prefix, target_ont)
            if namespace:
                return f"{namespace}{local}"
        
        return None
    
    def _replace_property_in_triple(self, triple: str, old_property: str, new_property: str, target_ont: str) -> Optional[str]:
        """
        トリプル内のプロパティを置換
        
        Args:
            triple: 元のトリプル
            old_property: 置換するプロパティURI
            new_property: 新しいプロパティURI
            target_ont: ターゲットオントロジー名
            
        Returns:
            置換後のトリプル
        """
        # フルURI形式で置換
        if f"<{old_property}>" in triple:
            return triple.replace(f"<{old_property}>", f"<{new_property}>")
        
        # プレフィックス形式で置換
        old_local = old_property.split('#')[-1] if '#' in old_property else old_property.split('/')[-1]
        new_local = new_property.split('#')[-1] if '#' in new_property else new_property.split('/')[-1]
        
        for prefix in [target_ont, target_ont.lower()]:
            old_prefixed = f"{prefix}:{old_local}"
            new_prefixed = f"{prefix}:{new_local}"
            if old_prefixed in triple:
                return triple.replace(old_prefixed, new_prefixed)
        
        return None
    
    # ========================================
    # Phase 5: rdf:type削除 (フォールバック)
    # ========================================
    
    def _phase5_remove_rdf_type(self, query: str) -> List[str]:
        """
        Phase 5: rdf:type制約を削除（階層緩和が効かない場合のフォールバック）
        
        Args:
            query: SPARQLクエリ
            
        Returns:
            緩和候補クエリのリスト
        """
        candidates = []
        
        parsed = self._parse_query(query)
        if not parsed.where_content:
            return candidates
        
        # UNION句を含むクエリはスキップ
        if re.search(r'\bunion\b', parsed.where_content, re.IGNORECASE):
            if self.verbose:
                logger.info("    Skipping Phase5 for UNION query")
            return candidates
        
        # トリプルを展開
        triples = self._expand_turtle_triples(parsed.where_content)
        
        if not triples:
            return candidates
        
        # rdf:typeトリプルを除外
        non_type_triples = []
        removed_any = False
        
        for triple in triples:
            # rdf:type または 'a' (省略形) を含むかチェック
            if re.search(r'\s+rdf:type\s+', triple, re.IGNORECASE) or \
               re.search(r'\s+a\s+[<\?\w]', triple) or \
               'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' in triple:
                removed_any = True
            else:
                non_type_triples.append(triple)
        
        if removed_any and non_type_triples:
            new_where = '\n  '.join(non_type_triples)
            new_query = parsed.rebuild(new_where)
            candidates.append(new_query)
        
        return candidates


class DecisionTreeClassifier:
    """
    決定木ベースの分類器
    
    クエリを分析して適切なカテゴリを判定
    """
    
    def __init__(self):
        pass
    
    def classify(self, query: str, source_ont: str) -> Tuple[str, Dict[str, Any]]:
        """
        クエリを分類
        
        Args:
            query: SPARQLクエリ
            source_ont: ソースオントロジー名
            
        Returns:
            (primary_category, analysis_dict)
        """
        analysis = {
            'is_empty_where': self._is_empty_where(query),
            'triple_count': self._count_triples(query),
            'has_residual_uris': False,
            'residual_uris': [],
            'has_filter': self._has_filter(query),
            'has_rdf_type': self._has_rdf_type(query),
        }
        
        # 残留URI検出
        residual_uris = self._detect_source_uris(query, source_ont)
        analysis['has_residual_uris'] = len(residual_uris) > 0
        analysis['residual_uris'] = residual_uris
        
        # 決定木による分類
        if analysis['is_empty_where']:
            return 'A', analysis
        
        if analysis['triple_count'] == 0:
            return 'A', analysis
        
        if analysis['has_residual_uris']:
            if analysis['triple_count'] == 1:
                return 'B', analysis
            else:
                return 'C', analysis
        
        if analysis['has_filter']:
            return 'D', analysis
        
        if analysis['triple_count'] >= 2:
            return 'E', analysis
        
        if analysis['has_rdf_type']:
            return 'F', analysis
        
        if analysis['triple_count'] >= 1:
            return 'G', analysis
        
        return 'H', analysis
    
    def _is_empty_where(self, query: str) -> bool:
        """WHERE句が空かどうか"""
        return bool(re.search(r'WHERE\s*\{\s*\}', query, re.IGNORECASE))
    
    def _count_triples(self, query: str) -> int:
        """トリプルパターンをカウント"""
        where_match = re.search(r'WHERE\s*\{(.*)\}', query, re.IGNORECASE | re.DOTALL)
        if not where_match:
            return 0
        
        where_content = where_match.group(1)
        
        # FILTER句を除外
        where_content = re.sub(r'FILTER\s*\([^)]*\)', '', where_content, flags=re.IGNORECASE)
        
        # トリプルをカウント
        count = 0
        lines = where_content.split('\n')
        for line in lines:
            line = line.strip()
            if not line or line in ['{', '}']:
                continue
            if '?' in line:
                count += 1
        
        return count
    
    def _has_filter(self, query: str) -> bool:
        """FILTER句があるかどうか"""
        return bool(re.search(r'FILTER\s*\(', query, re.IGNORECASE))
    
    def _has_rdf_type(self, query: str) -> bool:
        """rdf:type制約があるかどうか"""
        if re.search(r'\s+rdf:type\s+', query, re.IGNORECASE):
            return True
        if re.search(r'\s+a\s+[<\w]', query):
            return True
        if 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' in query:
            return True
        return False
    
    def _detect_source_uris(self, query: str, source_ont: str) -> List[str]:
        """ソースURIを検出"""
        residuals = []
        source_info = DATASET_PREFIXES.get(source_ont, {'prefixes': [], 'namespaces': []})
        
        # PREFIX行を除外
        lines = query.split('\n')
        query_body = '\n'.join([l for l in lines if not l.strip().upper().startswith('PREFIX')])
        
        for prefix in source_info['prefixes']:
            prefix_clean = prefix.rstrip(':')
            pattern = rf'\b{re.escape(prefix_clean)}:[\w]+'
            matches = re.findall(pattern, query_body)
            residuals.extend(matches)
        
        for namespace in source_info['namespaces']:
            pattern = rf'<{re.escape(namespace)}[^>]*>'
            matches = re.findall(pattern, query_body)
            residuals.extend(matches)
        
        return list(set(residuals))
