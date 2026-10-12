"""
Ruthless Rewriter データ取得率測定スクリプト

data/alignment/ 配下のアラインメントペアを使用して、
実際のRDFデータセットでクエリを実行し、データ取得率を測定する。

重要: ソースデータセットとターゲットデータセットを分離して処理
- input_query → ソースデータセットで実行
- output_query → ターゲットデータセットで実行
- 結果を比較してデータ取得率を算出
"""

import os
import sys
import json
import csv
import tempfile
from pathlib import Path
from SPARQLWrapper import SPARQLWrapper, JSON
from rdflib import Graph
import xml.etree.ElementTree as ET

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from sparql_translator.src.parser.edoal_parser_ruthless import EdoalParser
from sparql_translator.src.parser.sparql_ast_parser import SparqlAstParser
from sparql_translator.src.rewriter.sparql_rewriter_ruthless import SparqlRewriterRuthless
from sparql_translator.src.rewriter.ast_serializer import AstSerializer
from modules.config_loader import ConfigLoader
from modules.data_loader import DataLoader


class DataRetrievalTester:
    """データ取得率測定クラス"""
    
    def __init__(self, project_root: str, rdfs_materialize: bool = False):
        self.project_root = project_root
        self.data_dir = os.path.join(project_root, 'data', 'alignment')
        self.ast_parser = SparqlAstParser(project_root)
        self.serializer = AstSerializer(project_root)
        self.failed_cases = []  # 失敗ケースを記録

        # ConfigLoaderとDataLoaderを初期化
        self.config_loader = ConfigLoader(project_root)
        # RDFS limited materialization（rdfs5/7/9/11のみ。既定OFF）
        self.data_loader = DataLoader(self.config_loader, rdfs_materialize=rdfs_materialize)
        
    def extract_cell_xml_for_uri(self, alignment_file: str, uri: str) -> str:
        """指定URIに関連するCellのXMLを抽出"""
        try:
            with open(alignment_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # XML名前空間を定義
            namespaces = {
                'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
                'edoal': 'http://ns.inria.org/edoal/1.0/#',
                'align': 'http://knowledgeweb.semanticweb.org/heterogeneity/alignment#',
                'rdfs': 'http://www.w3.org/2000/01/rdf-schema#',
                'xsd': 'http://www.w3.org/2001/XMLSchema#'
            }
            
            # 名前空間を登録
            for prefix, uri_val in namespaces.items():
                ET.register_namespace(prefix, uri_val)
            
            root = ET.fromstring(content)
            
            # 全てのCellを検索
            for cell in root.findall('.//align:map/align:Cell', namespaces):
                cell_str = ET.tostring(cell, encoding='unicode')
                # URIが含まれているかチェック
                if uri in cell_str:
                    return cell_str
            
            return ""
        except Exception as e:
            return f"Error extracting cell XML: {e}"
        
    def load_rdf_graph(self, dataset_files: list) -> Graph:
        """RDFファイルをグラフに読み込み（後方互換性のため残存）"""
        graph = Graph()
        for file_path in dataset_files:
            if os.path.exists(file_path):
                try:
                    if file_path.endswith('.ttl'):
                        graph.parse(file_path, format='turtle')
                    elif file_path.endswith('.owl'):
                        graph.parse(file_path, format='xml')
                    print(f"  ✓ 読み込み: {os.path.basename(file_path)} ({len(graph)} トリプル)")
                except Exception as e:
                    print(f"  ✗ エラー: {os.path.basename(file_path)} - {e}")
        return graph
    
    def execute_sparql_query(self, query: str, data_sources: list) -> dict:
        """
        SPARQLクエリを実行（DataLoaderのデータソースを使用）
        
        Args:
            query: SPARQLクエリ文字列
            data_sources: DataLoaderから取得したデータソースのリスト
            
        Returns:
            実行結果の辞書
        """
        if not data_sources:
            return {
                'success': False,
                'error': 'データソースが指定されていません',
                'count': 0
            }
        
        try:
            # 最初のデータソースで実行（統合されている場合は1つのみ）
            data_source = data_sources[0]
            
            # タイムアウト60秒でクエリ実行（全データソースタイプで統一）
            results = data_source.query(query, timeout=60)
            
            result_list = []
            if isinstance(results, list):
                result_list = results
            else:
                # 他の形式の場合は変換
                result_list = list(results) if hasattr(results, '__iter__') else []
            
            return {
                'success': True,
                'count': len(result_list),
                'results': result_list[:5]  # 最初の5件のみ保存
            }
        except TimeoutError as e:
            return {
                'success': False,
                'error': f'タイムアウト: {str(e)}',
                'count': 0
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'count': 0
            }
    
    def translate_query(self, input_query: str, alignment_file: str) -> tuple:
        """クエリを変換"""
        try:
            # アラインメントをパース
            alignment = EdoalParser(file_path=alignment_file, verbose=False).parse()
            
            # SPARQLをASTにパース
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sparql', delete=False, encoding='utf-8') as tmp:
                tmp.write(input_query)
                tmp_path = tmp.name
            
            try:
                ast = self.ast_parser.parse(tmp_path)
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            
            # リライター実行
            rewriter = SparqlRewriterRuthless(alignment, verbose=False)
            rewritten_ast = rewriter.walk(ast)
            
            # シリアライズ
            output_query = self.serializer.serialize(rewritten_ast)
            
            # 未使用URIを取得
            missing_uris = rewriter.get_unused_source_uris()
            used_uris = list(rewriter.used_source_uris)
            
            return (True, output_query, None, missing_uris, alignment, used_uris)
        except Exception as e:
            return (False, None, str(e), [], None, [])
    
    def test_pair(self, pair_name: str, limit: int = None) -> dict:
        """単一ペアをテスト（ソース/ターゲット分離版）"""
        pair_dir = os.path.join(self.data_dir, pair_name)
        
        if not os.path.exists(pair_dir):
            return {'error': f'ペアディレクトリが見つかりません: {pair_dir}'}
        
        # alignment.json を読み込み
        alignment_json_path = os.path.join(pair_dir, 'alignment.json')
        if not os.path.exists(alignment_json_path):
            return {'error': f'alignment.json が見つかりません'}
        
        print(f"\n{'='*80}")
        print(f"ペア: {pair_name}")
        print(f"{'='*80}")
        
        # ConfigLoaderとDataLoaderを使用してソース/ターゲットを分離ロード
        try:
            source_sources, target_sources = self.data_loader.load_source_and_target_for_pair(pair_name)
            print(f"ソースデータソース: {len(source_sources)} 件")
            print(f"ターゲットデータソース: {len(target_sources)} 件")
        except Exception as e:
            return {'error': f'データソースのロードに失敗: {e}'}
        
        # アラインメントファイル
        alignment_config = self.config_loader.load_alignment_config(pair_name)
        alignment_file = alignment_config.get('alignment_file')
        if not alignment_file:
            return {'error': 'アラインメントファイルが指定されていません'}
        
        # 絶対パスに変換
        if not os.path.isabs(alignment_file):
            alignment_file = os.path.join(self.project_root, alignment_file)
        
        if not os.path.exists(alignment_file):
            return {'error': f'アラインメントファイルが見つかりません: {alignment_file}'}
        
        print(f"アラインメント: {os.path.basename(alignment_file)}")
        
        # クエリディレクトリ
        queries_dir = alignment_config.get('queries_dir')
        if not queries_dir:
            return {'error': 'クエリディレクトリが指定されていません'}
        
        if not os.path.isabs(queries_dir):
            queries_dir = os.path.join(self.project_root, queries_dir)
        
        if not os.path.exists(queries_dir):
            return {'error': f'queriesディレクトリが見つかりません: {queries_dir}'}
        
        # 期待出力ディレクトリ
        expected_dir = alignment_config.get('expected_output_dir')
        has_expected = False
        if expected_dir:
            if not os.path.isabs(expected_dir):
                expected_dir = os.path.join(self.project_root, expected_dir)
            has_expected = os.path.exists(expected_dir)
        
        print(f"期待出力: {'あり' if has_expected else 'なし'}")
        
        # クエリファイルを処理
        query_files = sorted([f for f in os.listdir(queries_dir) if f.endswith('.sparql')])
        
        if limit:
            query_files = query_files[:limit]
            print(f"\nクエリ数: {len(query_files)} (制限: {limit})")
        else:
            print(f"\nクエリ数: {len(query_files)}")
        
        results = []
        success_count = 0
        retrieval_count = 0
        match_count = 0  # 入力と出力の結果が一致した数
        error_count = 0
        
        for i, query_file in enumerate(query_files, 1):
            query_path = os.path.join(queries_dir, query_file)
            
            with open(query_path, 'r', encoding='utf-8') as f:
                input_query = f.read()
            
            # 期待クエリを読み込み
            expected_query = ""
            if has_expected:
                expected_path = os.path.join(expected_dir, query_file)
                if os.path.exists(expected_path):
                    with open(expected_path, 'r', encoding='utf-8') as f:
                        expected_query = f.read()
            
            # クエリを変換
            translation_success, output_query, translation_error, missing_uris, alignment, used_uris = self.translate_query(input_query, alignment_file)
            
            # エンティティ情報とアラインメント情報を取得
            input_query_entities = []
            entity_alignment = []
            
            if translation_success:
                input_query_entities = sorted(list(used_uris))
                for uri in input_query_entities:
                    cell_xml = self.extract_cell_xml_for_uri(alignment_file, uri)
                    if cell_xml:
                        entity_alignment.append(f"URI: {uri}\n{cell_xml}")
                    else:
                        entity_alignment.append(f"URI: {uri}\n(No alignment cell found)")
            
            if not translation_success:
                print(f"[{i}/{len(query_files)}] {query_file:25s} ✗ 変換失敗: {translation_error}")
                error_count += 1
                results.append({
                    'query_file': query_file,
                    'translation_success': False,
                    'translation_error': translation_error,
                    'data_retrieved': False,
                    'results_match': False,
                    'input_query': input_query,
                    'output_query': '',
                    'expected_query': expected_query,
                    'input_query_entities': '',
                    'entity_alignment': ''
                })
                
                # 失敗ケースを記録
                self.failed_cases.append({
                    'pair_name': pair_name,
                    'query_file': query_file,
                    'input_query': input_query,
                    'expected_query': expected_query,
                    'error': translation_error,
                    'missing_uris': []
                })
                continue
            
            # 入力クエリをソースデータセットで実行
            input_result = self.execute_sparql_query(input_query, source_sources)
            
            # 変換後クエリをターゲットデータセットで実行
            output_result = self.execute_sparql_query(output_query, target_sources)
            
            # 結果を比較
            input_count = input_result.get('count', 0) if input_result.get('success') else 0
            output_count = output_result.get('count', 0) if output_result.get('success') else 0
            
            # 結果が一致するかチェック（件数ベース）
            results_match = (input_count > 0 and output_count > 0 and input_count == output_count)
            
            result_entry = {
                'query_file': query_file,
                'translation_success': True,
                'input_execution_success': input_result.get('success', False),
                'output_execution_success': output_result.get('success', False),
                'input_count': input_count,
                'output_count': output_count,
                'results_match': results_match,
                'data_retrieved': output_count > 0,
                'missing_uris': missing_uris,
                'input_query': input_query,
                'output_query': output_query,
                'expected_query': expected_query,
                'input_query_entities': ", ".join(input_query_entities),
                'entity_alignment': "\n---\n".join(entity_alignment)
            }
            
            if output_result.get('success') and output_count > 0:
                if results_match:
                    print(f"[{i}/{len(query_files)}] {query_file:25s} ✓ 一致! ソース:{input_count} ターゲット:{output_count} 件")
                    success_count += 1
                    retrieval_count += 1
                    match_count += 1
                else:
                    print(f"[{i}/{len(query_files)}] {query_file:25s} ⚠ 不一致 ソース:{input_count} ターゲット:{output_count} 件")
                    success_count += 1
                    retrieval_count += 1
                    
                    # 不一致ケースを記録
                    self.failed_cases.append({
                        'pair_name': pair_name,
                        'query_file': query_file,
                        'input_query': input_query,
                        'output_query': output_query,
                        'expected_query': expected_query,
                        'input_count': input_count,
                        'output_count': output_count,
                        'missing_uris': missing_uris,
                        'alignment_file': alignment_file
                    })
            elif output_result.get('success'):
                print(f"[{i}/{len(query_files)}] {query_file:25s} ⚠ 0件 (ソース:{input_count}件)")
                success_count += 1
                
                # 0件取得の場合は必ず失敗ケースとして記録
                self.failed_cases.append({
                    'pair_name': pair_name,
                    'query_file': query_file,
                    'input_query': input_query,
                    'output_query': output_query,
                    'expected_query': expected_query,
                    'input_count': input_count,
                    'output_count': 0,
                    'missing_uris': missing_uris,
                    'alignment_file': alignment_file
                })
            else:
                print(f"[{i}/{len(query_files)}] {query_file:25s} ✗ 実行エラー: {output_result.get('error', '')[:50]}")
                error_count += 1
                
                # 実行エラーも記録
                self.failed_cases.append({
                    'pair_name': pair_name,
                    'query_file': query_file,
                    'input_query': input_query,
                    'output_query': output_query,
                    'expected_query': expected_query,
                    'error': output_result.get('error'),
                    'input_count': input_count,
                    'output_count': 0,
                    'missing_uris': missing_uris,
                    'alignment_file': alignment_file
                })
            
            results.append(result_entry)
        
        # サマリー
        total = len(query_files)
        retrieval_rate = (retrieval_count / total * 100) if total > 0 else 0
        match_rate = (match_count / total * 100) if total > 0 else 0
        success_rate = (success_count / total * 100) if total > 0 else 0
        
        print(f"\n{'='*80}")
        print(f"結果サマリー: {pair_name}")
        print(f"{'='*80}")
        print(f"総クエリ数:         {total}")
        print(f"変換成功:           {success_count} / {total} ({success_rate:.1f}%)")
        print(f"データ取得成功:     {retrieval_count} / {total} ({retrieval_rate:.1f}%)")
        print(f"結果一致:           {match_count} / {total} ({match_rate:.1f}%)")
        print(f"エラー:             {error_count}")
        
        return {
            'pair_name': pair_name,
            'total_queries': total,
            'translation_success': success_count,
            'data_retrieval_success': retrieval_count,
            'results_match_count': match_count,
            'error_count': error_count,
            'retrieval_rate': retrieval_rate,
            'match_rate': match_rate,
            'success_rate': success_rate,
            'results': results
        }
    
    def test_multiple_pairs(self, pair_names: list) -> list:
        """複数ペアをテスト"""
        all_results = []
        
        for pair_name in pair_names:
            result = self.test_pair(pair_name)
            all_results.append(result)
        
        # 総合サマリー
        print(f"\n\n{'='*80}")
        print("総合サマリー")
        print(f"{'='*80}")
        
        total_queries = sum(r.get('total_queries', 0) for r in all_results)
        total_retrieval = sum(r.get('data_retrieval_success', 0) for r in all_results)
        total_match = sum(r.get('results_match_count', 0) for r in all_results)
        
        for result in all_results:
            if 'retrieval_rate' in result:
                print(f"{result['pair_name']:25s} 取得率: {result['retrieval_rate']:5.1f}% 一致率: {result.get('match_rate', 0):5.1f}% ({result['data_retrieval_success']}/{result['total_queries']})")
        
        overall_retrieval_rate = (total_retrieval / total_queries * 100) if total_queries > 0 else 0
        overall_match_rate = (total_match / total_queries * 100) if total_queries > 0 else 0
        print(f"\n{'全体':25s} 取得率: {overall_retrieval_rate:5.1f}% 一致率: {overall_match_rate:5.1f}% ({total_retrieval}/{total_queries})")
        
        return all_results
    
    def save_failed_cases_csv(self, output_file: str = 'failed_cases_detailed.csv'):
        """失敗ケースをCSV形式で保存"""
        if not self.failed_cases:
            print(f"\n失敗ケースはありません")
            return
        
        print(f"\n失敗ケース詳細をCSVに保存: {output_file}")
        
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'pair_name', 'query_file', 
                'missing_uri_1', 'cell_xml_1',
                'missing_uri_2', 'cell_xml_2',
                'input_query', 'output_query', 'expected_query'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for case in self.failed_cases:
                missing_uris = case.get('missing_uris', [])
                alignment_file = case.get('alignment_file', '')
                
                # 最大2つのURIとそのCellXMLを抽出
                uri1 = missing_uris[0] if len(missing_uris) > 0 else ''
                uri2 = missing_uris[1] if len(missing_uris) > 1 else ''
                
                cell_xml_1 = ''
                cell_xml_2 = ''
                
                if alignment_file:
                    if uri1:
                        cell_xml_1 = self.extract_cell_xml_for_uri(alignment_file, uri1)
                    if uri2:
                        cell_xml_2 = self.extract_cell_xml_for_uri(alignment_file, uri2)
                
                writer.writerow({
                    'pair_name': case.get('pair_name', ''),
                    'query_file': case.get('query_file', ''),
                    'missing_uri_1': uri1,
                    'cell_xml_1': cell_xml_1,
                    'missing_uri_2': uri2,
                    'cell_xml_2': cell_xml_2,
                    'input_query': case.get('input_query', ''),
                    'output_query': case.get('output_query', ''),
                    'expected_query': case.get('expected_query', '')
                })
        
        print(f"✓ {len(self.failed_cases)} 件の失敗ケースを保存しました")


def main():
    """メイン処理"""
    project_root = str(PROJECT_ROOT)
    tester = DataRetrievalTester(project_root)
    
    # テストするペア（データセットがあるペアを選択）
    test_pairs = [
        'cmt-confOf',
        'cmt-conference',
        'cmt-edas',
        'cmt-ekaw',
        'conference-cmt',
        'conference-confOf',
        'conference-edas',
        'conference-ekaw',
        'confOf-cmt',
        'confOf-conference',
        'confOf-edas',
        'confOf-ekaw',
        'gbo-gmo'
    ]
    
    print("=" * 80)
    print("Ruthless Rewriter データ取得率測定（全データセット）")
    print("=" * 80)
    print(f"テスト対象: {len(test_pairs)} ペア")
    
    results = tester.test_multiple_pairs(test_pairs)
    
    # 結果をJSONに保存
    output_file = 'data_retrieval_results_all.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n詳細結果を保存: {output_file}")
    
    # 失敗ケースをCSVに保存
    tester.save_failed_cases_csv('failed_cases_detailed.csv')


if __name__ == '__main__':
    main()
