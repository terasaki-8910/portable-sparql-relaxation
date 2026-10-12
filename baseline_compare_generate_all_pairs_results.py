"""
独自手法とJava製ベースライン翻訳機(SparqlTranslator.jar)の比較プログラム

- 自動検出: data/alignment/*/alignment.json
- Baseline: baseline/thieblin-sparql-translator/jar utiles/SparqlTranslator.jar
- タイムアウト: 60秒/クエリ
- データセット/エンドポイント不在時: スキップ
- ログ: リアルタイム出力
- 既存データのスキップ機能付き
"""

from pathlib import Path
import sys
import csv
import time
import subprocess
import tempfile
import os
import re
import json

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from test_dir.test_data_retrieval import DataRetrievalTester

# Baseline JAR設定
BASELINE_JAR_DIR = PROJECT_ROOT / 'baseline' / 'thieblin-sparql-translator' / 'jar utiles'
BASELINE_JAR_PATH = BASELINE_JAR_DIR / 'SparqlTranslator.jar'


class BaselineTranslator:
    """Baseline SparqlTranslator.jar のラッパークラス"""
    
    def __init__(self):
        self.jar_dir = BASELINE_JAR_DIR
        self.jar_path = BASELINE_JAR_PATH
        
        # JAR存在確認
        if not self.jar_path.exists():
            raise FileNotFoundError(f"Baseline JAR が見つかりません: {self.jar_path}")
        if not (self.jar_dir / 'lib').exists():
            raise FileNotFoundError(f"lib ディレクトリが見つかりません: {self.jar_dir / 'lib'}")
    
    def normalize_query(self, query: str) -> str:
        """
        クエリを正規化してBaselineのパーサーバグを回避する
        - 行末の余分な空白を削除
        - 各行の先頭・末尾の空白を削除
        - 空行を削除
        """
        lines = query.split('\n')
        # 各行の前後空白を削除（ただしインデントは保持したいので strip() は慎重に）
        # Baselineは空白に厳しいので、安全のため全ての前後空白を削除
        normalized_lines = [line.strip() for line in lines]
        # 空行を削除
        normalized_lines = [line for line in normalized_lines if line]
        # 結合して返す
        return '\n'.join(normalized_lines)
    
    def convert_to_prefix_format(self, query: str) -> str:
        """
        フルURI形式のクエリをPREFIX形式に変換する
        BaselineはPREFIX形式を期待するため
        """
        uri_pattern = r'<(http://[^>]+)>'
        uris = re.findall(uri_pattern, query)
        
        namespaces = {}
        prefix_count = 0
        
        for uri in uris:
            if '#' in uri:
                ns, local = uri.rsplit('#', 1)
                ns = ns + '#'
            elif '/' in uri:
                ns, local = uri.rsplit('/', 1)
                ns = ns + '/'
            else:
                continue
            
            if ns not in namespaces:
                # 既知の名前空間にプリフィックスを割り当て
                known_prefixes = {
                    'http://www.w3.org/1999/02/22-rdf-syntax-ns#': 'rdf',
                    'http://www.w3.org/2000/01/rdf-schema#': 'rdfs',
                    'http://www.w3.org/2002/07/owl#': 'owl',
                    'http://cmt#': 'cmt',
                    'http://confOf#': 'confOf',
                    'http://conference#': 'conference',
                    'http://edas#': 'edas',
                    'http://ekaw#': 'ekaw',
                }
                if ns in known_prefixes:
                    namespaces[ns] = known_prefixes[ns]
                else:
                    namespaces[ns] = f'ns{prefix_count}'
                    prefix_count += 1
        
        # PREFIX宣言を生成
        prefix_lines = []
        for ns, prefix in sorted(namespaces.items(), key=lambda x: x[1]):
            prefix_lines.append(f'PREFIX {prefix}: <{ns}>')
        
        # クエリ内のURIを置換
        converted_query = query
        for uri in uris:
            if '#' in uri:
                ns, local = uri.rsplit('#', 1)
                ns = ns + '#'
            elif '/' in uri:
                ns, local = uri.rsplit('/', 1)
                ns = ns + '/'
            else:
                continue
            
            if ns in namespaces:
                prefix = namespaces[ns]
                converted_query = converted_query.replace(f'<{uri}>', f'{prefix}:{local}')
        
        result = '\n'.join(prefix_lines) + '\n' + converted_query
        return result
    
    def extract_translated_query(self, stdout: str) -> str:
        """標準出力から変換されたSPARQLクエリを抽出する"""
        if not stdout or stdout.strip() == 'null':
            return None
        
        lines = stdout.strip().split('\n')
        
        # "null" が最終行の場合は失敗
        if lines[-1].strip() == 'null':
            return None
        
        # PREFIX から始まる行を探して、そこから末尾までをクエリとして抽出
        query_lines = []
        in_query = False
        
        for line in lines:
            stripped = line.strip()
            if stripped.upper().startswith('PREFIX') or stripped.upper().startswith('SELECT'):
                in_query = True
            if in_query:
                query_lines.append(line)
        
        if query_lines:
            return '\n'.join(query_lines).strip()
        
        return None
    
    def translate(self, alignment_file: str, query: str, timeout: int = 60) -> dict:
        """
        Baselineでクエリを変換する
        
        Args:
            alignment_file: EDOALアラインメントファイルのパス
            query: 入力SPARQLクエリ文字列
            timeout: タイムアウト秒数
            
        Returns:
            {
                'success': bool,
                'output_query': str or None,
                'error': str or None,
                'returncode': int,
                'stdout': str,
                'stderr': str
            }
        """
        result = {
            'success': False,
            'output_query': None,
            'error': None,
            'returncode': -1,
            'stdout': '',
            'stderr': ''
        }
        
        # クエリを正規化（行末空白削除）
        normalized_query = self.normalize_query(query)
        
        # クエリをPREFIX形式に変換
        converted_query = self.convert_to_prefix_format(normalized_query)
        
        # 一時ファイルに保存
        tmp_file = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sparql', delete=False, encoding='utf-8') as tmp:
                tmp.write(converted_query)
                tmp_file = tmp.name
            
            # Javaコマンドを構築
            cmd = [
                'java', '-jar', 'SparqlTranslator.jar',
                str(alignment_file),
                tmp_file
            ]
            
            # 実行
            proc_result = subprocess.run(
                cmd,
                cwd=str(self.jar_dir),
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            result['returncode'] = proc_result.returncode
            result['stdout'] = proc_result.stdout
            result['stderr'] = proc_result.stderr
            
            # 変換結果を抽出
            translated_query = self.extract_translated_query(proc_result.stdout)
            
            if translated_query:
                result['success'] = True
                result['output_query'] = translated_query
            else:
                result['success'] = False
                # エラー原因を特定
                if 'null' in proc_result.stdout:
                    result['error'] = 'Baseline returned null (query pattern not supported)'
                elif proc_result.stderr:
                    # SLF4J警告を除外
                    error_lines = [l for l in proc_result.stderr.split('\n') 
                                  if not l.startswith('SLF4J')]
                    if error_lines:
                        result['error'] = error_lines[0][:200]  # 最初の200文字
                    else:
                        result['error'] = 'Unknown error'
                else:
                    result['error'] = 'No output from baseline'
                    
        except subprocess.TimeoutExpired:
            result['error'] = f'Timeout ({timeout}s)'
        except Exception as e:
            result['error'] = str(e)
        finally:
            if tmp_file and os.path.exists(tmp_file):
                os.unlink(tmp_file)
        
        return result


def find_edoal_file(pair_dir: Path) -> Path:
    """ペアディレクトリからEDOALファイルを動的に検索"""
    alignment_subdir = pair_dir / 'alignment'
    if alignment_subdir.exists():
        edoal_files = list(alignment_subdir.glob('*.edoal'))
        if edoal_files:
            return edoal_files[0]
    return None

def main():
    project_root = str(PROJECT_ROOT)
    tester = DataRetrievalTester(project_root)
    
    # Baseline翻訳機を初期化
    try:
        baseline = BaselineTranslator()
        print(f"[OK] Baseline JAR: {BASELINE_JAR_PATH}")
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        print("   Baselineなしで続行します（独自手法のみ）")
        baseline = None
    
    # alignment.jsonを持つ全ペアを自動検出
    alignment_dir = PROJECT_ROOT / 'data' / 'alignment'
    all_pairs = []
    
    print("="*80)
    print("alignment.jsonを持つペアを検索中...")
    print("="*80)
    
    for pair_dir in sorted(alignment_dir.iterdir()):
        if pair_dir.is_dir():
            alignment_json = pair_dir / 'alignment.json'
            if alignment_json.exists():
                all_pairs.append(pair_dir.name)
                print(f"  * {pair_dir.name}")
    
    print(f"\n検出されたペア数: {len(all_pairs)}")
    print("="*80)
    
    if not all_pairs:
        print("WARNING: alignment.jsonを持つペアが見つかりませんでした")
        return
    
    # 既存CSVから完了済みクエリを読み込み
    output_dir = PROJECT_ROOT / 'output'
    csv_path = output_dir / 'baseline_comparison_results.csv'
    
    completed_queries = set()  # (pair_name, query_file) のセット
    all_results = []
    
    if csv_path.exists():
        print("\n既存CSVを検出 - 完了済みクエリを読み込み中...")
        print("="*80)
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pair_name = row.get('pair_name', '')
                    query_file = row.get('query_file', '')
                    if pair_name and query_file:
                        completed_queries.add((pair_name, query_file))
                        all_results.append(row)  # 既存データを保持
            print(f"[OK] 完了済みクエリ数: {len(completed_queries)}")
            
            # 完了済みペアを確認
            completed_pairs = set(pair for pair, _ in completed_queries)
            remaining_pairs = [p for p in all_pairs if p not in completed_pairs or 
                             any((p, qf) not in completed_queries for qf in ['dummy'])]
            print(f"[OK] 完了済みペア数: {len(completed_pairs)}")
            print(f"⏳ 残りペア数: {len(remaining_pairs)}")
        except Exception as e:
            print(f"[WARN]  CSV読み込みエラー: {e}")
            print("   → 新規作成します")
        print()
    
    print("="*80)
    print("独自手法 vs Baseline 比較テスト実行")
    print("="*80)
    print(f"対象ペア数: {len(all_pairs)}")
    print(f"タイムアウト: 60秒/クエリ")
    print(f"スキップモード: {'有効' if completed_queries else '無効'}")
    print(f"Baseline: {'有効' if baseline else '無効'}")
    print("="*80)
    print()
    
    start_time = time.time()
    total_new_queries = 0
    total_skipped_queries = 0
    
    for pair_idx, pair_name in enumerate(all_pairs, 1):
        pair_start = time.time()
        print(f"\n{'='*80}")
        print(f"[{pair_idx}/{len(all_pairs)}] ペア: {pair_name}")
        print(f"{'='*80}")
        
        try:
            # 事前チェック: クエリファイルリストを取得して完了済みを確認
            pair_dir = PROJECT_ROOT / 'data' / 'alignment' / pair_name
            alignment_json_path = pair_dir / 'alignment.json'
            
            if not alignment_json_path.exists():
                print(f"[WARN]  alignment.json が見つかりません")
                print(f"   → スキップします")
                continue
            
            # alignment.jsonからクエリディレクトリを取得
            import json
            try:
                with open(alignment_json_path, 'r', encoding='utf-8') as f:
                    alignment_config = json.load(f)
                    queries_dir_rel = alignment_config.get('queries_dir', '')
                    if not queries_dir_rel:
                        print(f"[WARN]  queries_dir が設定されていません")
                        print(f"   → スキップします")
                        continue
                    
                    queries_dir = PROJECT_ROOT / queries_dir_rel
                    if not queries_dir.exists():
                        print(f"[WARN]  クエリディレクトリが見つかりません: {queries_dir}")
                        print(f"   → スキップします")
                        continue
                    
                    # クエリファイルリストを取得
                    query_files = sorted([f.name for f in queries_dir.glob('*.sparql')])
                    if not query_files:
                        print(f"[WARN]  クエリファイルが見つかりません")
                        print(f"   → スキップします")
                        continue
                    
                    # 完了済みクエリをチェック
                    remaining_queries = [qf for qf in query_files 
                                        if (pair_name, qf) not in completed_queries]
                    skipped_count = len(query_files) - len(remaining_queries)
                    
                    if skipped_count > 0:
                        print(f"[SKIP] スキップ済み: {skipped_count}/{len(query_files)}クエリ")
                    
                    if not remaining_queries:
                        print(f"[OK] 全クエリ完了済み ({len(query_files)}件) - データセット読み込みをスキップします")
                        total_skipped_queries += skipped_count
                        continue
                    
                    print(f"[INFO] 実行対象: {len(remaining_queries)}/{len(query_files)}クエリ")
                    
            except Exception as e:
                print(f"[WARN]  事前チェックエラー: {e}")
                print(f"   → 通常処理を試みます")
            
            # データセット読み込みとクエリ実行
            result = tester.test_pair(pair_name)
            
            # エラーチェック
            if 'error' in result:
                print(f"[WARN]  エラー: {result['error']}")
                print(f"   → スキップします")
                continue
            
            # results キーから個々のクエリ結果を取得
            query_results = result.get('results', [])
            if not query_results:
                print(f"[WARN]  クエリ結果なし")
                print(f"   → スキップします")
                continue
            
            # 完了済みクエリを除外してフィルタリング
            new_results = []
            
            # EDOALファイルを取得（Baseline用）
            edoal_file = find_edoal_file(pair_dir)
            if baseline and not edoal_file:
                print(f"   [WARN] EDOALファイルが見つかりません - Baselineスキップ")
            
            for query_result in query_results:
                query_file = query_result.get('query_file', '')
                if (pair_name, query_file) not in completed_queries:
                    query_result['pair_name'] = pair_name
                    
                    # Baseline変換を実行
                    if baseline and edoal_file:
                        input_query = query_result.get('input_query', '')
                        if input_query:
                            baseline_result = baseline.translate(str(edoal_file), input_query)
                            query_result['baseline_translation_success'] = baseline_result['success']
                            query_result['baseline_output_query'] = baseline_result.get('output_query', '')
                            query_result['baseline_error'] = baseline_result.get('error', '')
                            
                            # Baseline変換が成功した場合、ターゲットデータセットで実行
                            if baseline_result['success'] and baseline_result.get('output_query'):
                                try:
                                    # DataRetrievalTesterのデータソースを使用
                                    _, target_sources = tester.data_loader.load_source_and_target_for_pair(pair_name)
                                    baseline_exec_result = tester.execute_sparql_query(
                                        baseline_result['output_query'], 
                                        target_sources
                                    )
                                    query_result['baseline_retrieval_success'] = baseline_exec_result.get('success', False)
                                    query_result['baseline_output_count'] = baseline_exec_result.get('count', 0)
                                    
                                    # 結果一致判定（独自手法の入力件数と比較）
                                    input_count = query_result.get('input_count', 0)
                                    baseline_count = baseline_exec_result.get('count', 0)
                                    query_result['baseline_results_match'] = (
                                        input_count > 0 and baseline_count > 0 and input_count == baseline_count
                                    )
                                except Exception as e:
                                    query_result['baseline_retrieval_success'] = False
                                    query_result['baseline_output_count'] = 0
                                    query_result['baseline_results_match'] = False
                                    query_result['baseline_error'] = f"Execution error: {str(e)[:100]}"
                            else:
                                query_result['baseline_retrieval_success'] = False
                                query_result['baseline_output_count'] = 0
                                query_result['baseline_results_match'] = False
                        else:
                            query_result['baseline_translation_success'] = False
                            query_result['baseline_output_query'] = ''
                            query_result['baseline_error'] = 'No input query'
                            query_result['baseline_retrieval_success'] = False
                            query_result['baseline_output_count'] = 0
                            query_result['baseline_results_match'] = False
                    else:
                        # Baseline無効の場合
                        query_result['baseline_translation_success'] = None
                        query_result['baseline_output_query'] = ''
                        query_result['baseline_error'] = 'Baseline disabled'
                        query_result['baseline_retrieval_success'] = None
                        query_result['baseline_output_count'] = 0
                        query_result['baseline_results_match'] = None
                    
                    new_results.append(query_result)
                    all_results.append(query_result)
            
            total_skipped_queries += skipped_count
            
            if not new_results:
                print(f"[WARN]  新規結果なし（データ不整合の可能性）")
                continue
            
            # 統計計算 (新規実行分のみ)
            total = len(new_results)
            total_new_queries += total
            translation_ok = sum(1 for r in new_results if r.get('translation_success', False))
            data_retrieved = sum(1 for r in new_results if r.get('data_retrieved', False))
            match_ok = sum(1 for r in new_results if r.get('results_match', False))
            
            # Baseline統計
            baseline_translation_ok = sum(1 for r in new_results 
                                         if r.get('baseline_translation_success', False))
            baseline_retrieved = sum(1 for r in new_results 
                                    if r.get('baseline_retrieval_success', False))
            baseline_match_ok = sum(1 for r in new_results 
                                   if r.get('baseline_results_match', False))
            
            pair_elapsed = time.time() - pair_start
            
            print(f"\n[STATS] ペア統計 (新規実行分):")
            print(f"   総クエリ数: {total}")
            print(f"   --- 独自手法 ---")
            print(f"   変換成功:   {translation_ok}/{total} ({translation_ok/total*100:.1f}%)")
            print(f"   データ取得: {data_retrieved}/{total} ({data_retrieved/total*100:.1f}%)")
            print(f"   結果一致:   {match_ok}/{total} ({match_ok/total*100:.1f}%)")
            if baseline:
                print(f"   --- Baseline ---")
                print(f"   変換成功:   {baseline_translation_ok}/{total} ({baseline_translation_ok/total*100:.1f}%)")
                print(f"   データ取得: {baseline_retrieved}/{total} ({baseline_retrieved/total*100:.1f}%)")
                print(f"   結果一致:   {baseline_match_ok}/{total} ({baseline_match_ok/total*100:.1f}%)")
            print(f"   処理時間:   {pair_elapsed:.1f}秒")
            
            # 中間保存 (5ペアごと、またはエラー時のため)
            if pair_idx % 5 == 0:
                save_csv(csv_path, all_results, output_dir)
                print(f"\n[SAVE] 中間保存完了 ({pair_idx}/{len(all_pairs)}ペア)")
            
        except KeyboardInterrupt:
            print(f"\n\n[WARN]  ユーザーによる中断")
            print(f"[SAVE] 現在までの結果を保存します...")
            save_csv(csv_path, all_results, output_dir)
            break
        except Exception as e:
            print(f"[WARN]  例外発生: {e}")
            import traceback
            traceback.print_exc()
            print(f"   → スキップして次のペアへ")
            # エラー時も中間保存
            save_csv(csv_path, all_results, output_dir)
    
    total_elapsed = time.time() - start_time
    
    # 最終保存
    if all_results:
        save_csv(csv_path, all_results, output_dir)
        
        print(f"\n\n{'='*80}")
        print(f"[DONE] 完了!")
        print(f"{'='*80}")
        print(f"[FILE] 保存先: {csv_path}")
        print(f"[TIME] 総処理時間: {total_elapsed/60:.1f}分")
        print(f"[NEW] 新規実行: {total_new_queries}クエリ")
        print(f"[SKIP] スキップ: {total_skipped_queries}クエリ")
        print()
        
        # ペア別統計
        print(f"[STATS] ペア別統計:")
        print(f"{'-'*80}")
        for pair in all_pairs:
            pair_results = [r for r in all_results 
                          if isinstance(r, dict) and r.get('pair_name') == pair]
            if pair_results:
                total = len(pair_results)
                translation_success = sum(1 for r in pair_results 
                                        if r.get('translation_success', False) or r.get('translation_success') == 'True')
                retrieval_success = sum(1 for r in pair_results 
                                      if r.get('data_retrieved', False) or r.get('retrieval_success', False) or 
                                      r.get('data_retrieved') == 'True' or r.get('retrieval_success') == 'True')
                match_count = sum(1 for r in pair_results 
                                if r.get('results_match', False) or r.get('results_match') == 'True')
                
                # Baseline統計
                baseline_trans = sum(1 for r in pair_results 
                                    if r.get('baseline_translation_success', False) or r.get('baseline_translation_success') == 'True')
                baseline_retr = sum(1 for r in pair_results 
                                   if r.get('baseline_retrieval_success', False) or r.get('baseline_retrieval_success') == 'True')
                baseline_match = sum(1 for r in pair_results 
                                    if r.get('baseline_results_match', False) or r.get('baseline_results_match') == 'True')
                
                print(f"\n{pair}:")
                print(f"  クエリ数:     {total}")
                print(f"  [独自] 変換: {translation_success/total*100:.1f}% 取得: {retrieval_success/total*100:.1f}% 一致: {match_count/total*100:.1f}%")
                print(f"  [Base] 変換: {baseline_trans/total*100:.1f}% 取得: {baseline_retr/total*100:.1f}% 一致: {baseline_match/total*100:.1f}%")
        
        # 全体統計
        total_queries = sum(1 for r in all_results if isinstance(r, dict))
        total_translation = sum(1 for r in all_results 
                              if isinstance(r, dict) and (r.get('translation_success', False) or r.get('translation_success') == 'True'))
        total_retrieval = sum(1 for r in all_results 
                            if isinstance(r, dict) and (r.get('data_retrieved', False) or r.get('retrieval_success', False) or 
                            r.get('data_retrieved') == 'True' or r.get('retrieval_success') == 'True'))
        total_match = sum(1 for r in all_results 
                        if isinstance(r, dict) and (r.get('results_match', False) or r.get('results_match') == 'True'))
        
        # Baseline全体統計
        total_baseline_trans = sum(1 for r in all_results 
                                  if isinstance(r, dict) and (r.get('baseline_translation_success', False) or r.get('baseline_translation_success') == 'True'))
        total_baseline_retr = sum(1 for r in all_results 
                                 if isinstance(r, dict) and (r.get('baseline_retrieval_success', False) or r.get('baseline_retrieval_success') == 'True'))
        total_baseline_match = sum(1 for r in all_results 
                                  if isinstance(r, dict) and (r.get('baseline_results_match', False) or r.get('baseline_results_match') == 'True'))
        
        print(f"\n{'='*80}")
        print(f"[STATS] 全体統計:")
        print(f"{'-'*80}")
        print(f"  総ペア数:       {len(all_pairs)}")
        print(f"  総クエリ数:     {total_queries}")
        print(f"\n  --- 独自手法 ---")
        print(f"  変換成功率:     {total_translation/total_queries*100:.1f}% ({total_translation}/{total_queries})")
        print(f"  データ取得率:   {total_retrieval/total_queries*100:.1f}% ({total_retrieval}/{total_queries})")
        print(f"  結果一致率:     {total_match/total_queries*100:.1f}% ({total_match}/{total_queries})")
        print(f"\n  --- Baseline ---")
        print(f"  変換成功率:     {total_baseline_trans/total_queries*100:.1f}% ({total_baseline_trans}/{total_queries})")
        print(f"  データ取得率:   {total_baseline_retr/total_queries*100:.1f}% ({total_baseline_retr}/{total_queries})")
        print(f"  結果一致率:     {total_baseline_match/total_queries*100:.1f}% ({total_baseline_match}/{total_queries})")
        print(f"{'='*80}")
    else:
        print(f"\n[WARN] 結果がありません")


def save_csv(csv_path, all_results, output_dir):
    """CSVファイルに保存"""
    output_dir.mkdir(exist_ok=True)
    
    fieldnames = [
        'pair_name',
        'query_file',
        # 独自手法
        'translation_success',
        'retrieval_success',
        'results_match',
        'input_count',
        'output_count',
        'error_message',
        # Baseline
        'baseline_translation_success',
        'baseline_retrieval_success',
        'baseline_results_match',
        'baseline_output_count',
        'baseline_error',
        # クエリ内容
        'input_query',
        'output_query',
        'baseline_output_query',
        'expected_query',
        'input_query_entities',
        'entity_alignment'
    ]
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for result in all_results:
            # 既存データ(dict/str混在)と新規データ(dict)を統合処理
            if isinstance(result, dict):
                writer.writerow({
                    'pair_name': result.get('pair_name', ''),
                    'query_file': result.get('query_file', ''),
                    'translation_success': result.get('translation_success', False),
                    'retrieval_success': result.get('data_retrieved') if 'data_retrieved' in result else result.get('retrieval_success', False),
                    'results_match': result.get('results_match', False),
                    'input_count': result.get('input_count', 0),
                    'output_count': result.get('output_count', 0),
                    'error_message': result.get('translation_error') if 'translation_error' in result else result.get('error_message', ''),
                    # Baseline
                    'baseline_translation_success': result.get('baseline_translation_success', ''),
                    'baseline_retrieval_success': result.get('baseline_retrieval_success', ''),
                    'baseline_results_match': result.get('baseline_results_match', ''),
                    'baseline_output_count': result.get('baseline_output_count', 0),
                    'baseline_error': result.get('baseline_error', ''),
                    # クエリ内容
                    'input_query': result.get('input_query', ''),
                    'output_query': result.get('output_query', ''),
                    'baseline_output_query': result.get('baseline_output_query', ''),
                    'expected_query': result.get('expected_query', ''),
                    'input_query_entities': result.get('input_query_entities', ''),
                    'entity_alignment': result.get('entity_alignment', '')
                })


if __name__ == '__main__':
    main()
