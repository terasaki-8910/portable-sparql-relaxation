"""
data_loader.py
ファイルベースとエンドポイントベースのデータソースを統合的に扱うモジュール

設計原則:
- ファクトリパターンによる type フィールドの厳密な解釈
- rdflib (file) と SPARQLWrapper (endpoint) の透過的な切り替え
- コンテキスト無視の禁止 (Prohibition.md Section 3)
"""

from typing import Union, Dict, Any, List
from pathlib import Path
import rdflib
from SPARQLWrapper import SPARQLWrapper, JSON
from modules.config_loader import ConfigLoader


def _stable_row_key(row_dict: Dict[str, Any]):
    """行の安定なソートキー（全束縛変数を辞書順に並べたタプル）。
    同一入力から常に同一の1万件が得られるようにするため、上限スライス前に用いる。"""
    return tuple(sorted(row_dict.items()))


def _run_with_timeout(fn, timeout):
    """signal.SIGALRM の代替（クロスプラットフォーム, Windows含む）。
    signal.SIGALRM は Unix 専用で Windows では hasattr(signal,'SIGALRM')=False のため
    従来のタイムアウトはこの環境で一度も発動していなかった（実測確認済み）。
    concurrent.futures を用いてスレッド越しに待つ。スレッドは強制終了できないため、
    タイムアウト時は呼び出し元へ制御を返すのみ（バックグラウンドで処理が残り得る点は
    signal.SIGALRM の実装も同様の性質だった＝Pythonバイトコード境界でしか割り込めない）。"""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn)
        try:
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"クエリ実行がタイムアウトしました（{timeout}秒）")


class DataSourceFactory:
    """
    データソースのファクトリクラス
    type フィールドに基づいて適切なクライアントを生成
    """
    
    @staticmethod
    def create_source(dataset_info: Dict[str, Any], config_loader: ConfigLoader):
        """
        データセット情報から適切なデータソースを生成
        
        Args:
            dataset_info: datasets_registry.json からのデータセット情報
            config_loader: ConfigLoaderインスタンス
            
        Returns:
            FileDataSource または EndpointDataSource
            
        Raises:
            ValueError: type フィールドが不正な場合
        """
        ds_type = dataset_info.get("type")
        
        if ds_type == "file":
            return FileDataSource(dataset_info, config_loader.project_root)
        elif ds_type == "endpoint":
            return EndpointDataSource(dataset_info)
        else:
            raise ValueError(f"不正なデータセットタイプ: {ds_type}")


class FileDataSource:
    """
    ファイルベースのRDFデータソース
    rdflib を使用してローカルファイルをロード
    """
    
    def __init__(self, dataset_info: Dict[str, Any], project_root: Path):
        """
        Args:
            dataset_info: データセット情報
            project_root: プロジェクトルート
        """
        self.dataset_info = dataset_info
        self.project_root = Path(project_root)
        self.graph = None
        self._load_graph()
    
    def _load_graph(self):
        """
        RDFファイルを rdflib.Graph にロード
        """
        file_path = self.dataset_info.get("path")
        if not file_path:
            raise ValueError("ファイルデータソースに path が指定されていません")
        
        # 絶対パスに変換
        if not Path(file_path).is_absolute():
            file_path = self.project_root / file_path
        else:
            file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"データセットファイルが見つかりません: {file_path}")
        
        # フォーマットを決定
        format_map = {
            "turtle": "turtle",
            "xml": "xml",
            "n3": "n3",
            "nt": "nt"
        }
        rdf_format = format_map.get(self.dataset_info.get("format", "turtle"), "turtle")
        
        self.graph = rdflib.Graph()
        try:
            # 構文エラーに寛容なパースを試みる
            self.graph.parse(str(file_path), format=rdf_format)
        except Exception as e:
            # エラーメッセージを記録するが、空のグラフで続行を試みる
            print(f"    警告: RDFファイルのパース中にエラー: {file_path}")
            print(f"    エラー詳細: {str(e)[:200]}")
            # 再試行：より寛容なパーサーオプションで
            try:
                import xml.etree.ElementTree as ET
                # 別のアプローチ：rdf/xmlとして再パース
                if rdf_format == "xml":
                    from rdflib.plugins.parsers.rdfxml import RDFXMLParser
                    parser = RDFXMLParser()
                    # 厳格モードを無効化して再試行
                    with open(file_path, 'rb') as f:
                        self.graph.parse(f, format=rdf_format)
            except Exception as e2:
                # 完全に失敗した場合は元のエラーを投げる
                raise RuntimeError(f"RDFファイルのパースに失敗: {file_path}, エラー: {e}")
    
    def query(self, sparql_query: str, timeout: int = 60) -> List[Dict[str, Any]]:
        """
        SPARQLクエリを実行（rdflibバグ対策を含む）
        
        Args:
            sparql_query: SPARQL クエリ文字列
            timeout: タイムアウト秒数（デフォルト60秒）
            
        Returns:
            クエリ結果のリスト
        """
        if not self.graph:
            raise RuntimeError("グラフがロードされていません")

        # signal.SIGALRM をクロスプラットフォームな concurrent.futures ベースに統一。
        # 方法1: 通常のクエリ実行
        def _do_query():
            # rdflibのprepareQueryを使用
            from rdflib.plugins.sparql import prepareQuery
            try:
                prepared = prepareQuery(sparql_query)
                results = self.graph.query(prepared)
                return self._convert_results(results)
            except Exception:
                # 直接実行を試みる
                results = self.graph.query(sparql_query)
                return self._convert_results(results)

        try:
            return _run_with_timeout(_do_query, timeout)
        except TimeoutError:
            # 下のexcept Exceptionに握られてRuntimeErrorへ握り替わり、
            # 呼び出し側がtimeoutとerrorを区別できなくなるのを防ぐ（merged側と同じ修正）。
            raise
        except Exception as e:
            error_msg = str(e)

            # rdflib内部エラーの場合
            if "postParse" in error_msg or "tokenList" in error_msg or "<lambda>" in error_msg:
                # 方法2: クエリを簡略化
                try:
                    import re
                    simplified = re.sub(r'\s+', ' ', sparql_query).strip()
                    if simplified != sparql_query:
                        results = self.graph.query(simplified)
                        return self._convert_results(results)
                except Exception:
                    pass

                # 握り潰さず伝播（呼び出し側が「エラー」と「0件」を区別できるように）。
                # 以前はここで return [] していたため rdflib 内部エラーが「該当0件」と混同され、
                # 緩和が誤起動していた。
                raise RuntimeError(f"SPARQL 実行失敗(rdflib内部エラー・簡略化リトライも不可): {error_msg}")
            else:
                raise RuntimeError(f"SPARQL クエリの実行に失敗: {e}")
    
    def _convert_results(self, results) -> List[Dict[str, Any]]:
        """
        rdflib の結果を辞書リストに変換（postParse2エラー対策 + 無限ループ対策）

        Args:
            results: rdflib.query.Result

        Returns:
            結果の辞書リスト
        """
        converted = []
        # 10000件の打ち切りを撤廃（ローカルrdflibのため撤廃コストは低い。
        # 打ち切りは92/1067クエリ、回復のうち5件のF1を汚染していた）。
        # CAP_REFERENCE は打ち切らず、cap_hit（旧上限を超えていたか）の記録にのみ使う。
        CAP_REFERENCE = 10000
        self.last_result_true_count = None
        self.last_result_cap_hit = False
        try:
            # results.varsを先に取得（遅延評価を回避）
            try:
                vars_list = list(results.vars) if hasattr(results, 'vars') else []
            except Exception:
                # varsの取得に失敗した場合、結果を直接処理
                vars_list = []

            # 全行を変換してから安定ソート→先頭 max_results 件を採る（決定化）。
            # 以前は islice で先頭 max_results 件のみ取得しており、rdflib のイテレーション順が
            # 非決定的なため run 毎に異なる部分集合が返っていた。
            for row in results:
                row_dict = {}
                if vars_list:
                    # 変数名が取得できた場合
                    for var in vars_list:
                        try:
                            value = row[var]
                            if value is not None:
                                row_dict[str(var)] = str(value)
                        except (KeyError, IndexError):
                            continue
                else:
                    # 変数名が取得できなかった場合、rowから直接変数を抽出
                    if hasattr(row, 'asdict'):
                        row_dict = {k: str(v) for k, v in row.asdict().items() if v is not None}
                    elif hasattr(row, '__iter__'):
                        # タプルの場合、s, p, o などの標準変数名を使用
                        for i, value in enumerate(row):
                            if value is not None:
                                row_dict[f"var{i}"] = str(value)

                if row_dict:  # 空でない場合のみ追加
                    converted.append(row_dict)

            converted.sort(key=_stable_row_key)
            self.last_result_true_count = len(converted)
            self.last_result_cap_hit = len(converted) > CAP_REFERENCE
            # 打ち切りなし: converted はスライスせずそのまま返す。

        except Exception as e:
            # 結果の変換中のエラー - より詳細な情報を提供
            error_msg = f"クエリ結果の変換に失敗: {type(e).__name__}: {str(e)[:200]}"
            raise RuntimeError(error_msg)
        return converted

    def get_type(self) -> str:
        return "file"


class EndpointDataSource:
    """
    エンドポイントベースのSPARQLデータソース
    SPARQLWrapper を使用してリモートエンドポイントにクエリ
    """
    
    def __init__(self, dataset_info: Dict[str, Any]):
        """
        Args:
            dataset_info: データセット情報（url を含む）
        """
        self.dataset_info = dataset_info
        self.endpoint_url = dataset_info.get("url")
        
        if not self.endpoint_url:
            raise ValueError("エンドポイントデータソースに url が指定されていません")
        
        self.sparql = SPARQLWrapper(self.endpoint_url)
        self.sparql.setReturnFormat(JSON)
        
        # タイムアウト設定（デフォルト60秒、設定で上書き可能）
        timeout = dataset_info.get("timeout", 60)
        self.sparql.setTimeout(timeout)
    
    def query(self, sparql_query: str, timeout: int = None) -> List[Dict[str, Any]]:
        """
        SPARQLクエリを実行
        
        Args:
            sparql_query: SPARQL クエリ文字列
            timeout: タイムアウト秒数（オプション、指定されない場合は初期化時の値を使用）
            
        Returns:
            クエリ結果のリスト
        """
        try:
            self.sparql.setQuery(sparql_query)
            # タイムアウトが指定されている場合は設定
            if timeout is not None:
                self.sparql.setTimeout(timeout)
            results = self.sparql.query().convert()
            return self._convert_results(results)
        except Exception as e:
            raise RuntimeError(f"エンドポイント {self.endpoint_url} へのクエリ実行に失敗: {e}")
    
    def _convert_results(self, results: Dict) -> List[Dict[str, Any]]:
        """
        SPARQLWrapper の JSON 結果を辞書リストに変換
        
        Args:
            results: SPARQLWrapper の結果
            
        Returns:
            結果の辞書リスト
        """
        if "results" not in results or "bindings" not in results["results"]:
            return []
        
        converted = []
        for binding in results["results"]["bindings"]:
            row_dict = {}
            for var, value in binding.items():
                row_dict[var] = value.get("value", "")
            converted.append(row_dict)
        return converted
    
    def get_type(self) -> str:
        return "endpoint"


class DataLoader:
    """
    データソースの統合管理クラス
    """
    
    def __init__(self, config_loader: ConfigLoader, rdfs_materialize: bool = False):
        """
        Args:
            config_loader: ConfigLoaderインスタンス
            rdfs_materialize: True なら rdfs5/7/9/11 のみを適用した限定的な
                RDFS materialization をロード後のグラフに施す（既定 False, 挙動不変）。
                rdfs2/3（domain/range からの型導出）は適用しない。
        """
        self.config_loader = config_loader
        self.sources_cache = {}
        self.rdfs_materialize = rdfs_materialize
        self._materialize_done = set()
        self.last_materialize_stats = {}
    
    def _load_dataset_list(self, dataset_list, pair_name, prefix):
        """データセットリストからデータソースをロード"""
        sources = []
        if not dataset_list:
            return sources
        
        for idx, dataset_dict in enumerate(dataset_list):
            cache_key = f"{pair_name}_{prefix}_{idx}"
            if cache_key not in self.sources_cache:
                source = DataSourceFactory.create_source(dataset_dict, self.config_loader)
                self.sources_cache[cache_key] = source
            sources.append(self.sources_cache[cache_key])
        
        return sources
    
    def _load_endpoint_dict(self, endpoint_dict):
        """エンドポイント辞書からデータソースをロード"""
        sources = []
        if not endpoint_dict:
            return sources
        
        for endpoint_id, endpoint_url in endpoint_dict.items():
            endpoint_key = f"endpoint_{endpoint_id}"
            if endpoint_key not in self.sources_cache:
                dataset_info = self.config_loader.get_dataset_info(endpoint_key)
                if dataset_info:
                    source = DataSourceFactory.create_source(dataset_info, self.config_loader)
                    self.sources_cache[endpoint_key] = source
            
            if endpoint_key in self.sources_cache:
                sources.append(self.sources_cache[endpoint_key])
        
        return sources
    
    def load_sources_for_pair(self, pair_name: str) -> Dict[str, Union[FileDataSource, EndpointDataSource]]:
        """
        アラインメントペアに必要な全データソースをロード
        
        Args:
            pair_name: アラインメントペア名
            
        Returns:
            データソースの辞書 {dataset_id: DataSource}
        """
        alignment_config = self.config_loader.load_alignment_config(pair_name)
        sources = {}
        
        # 後方互換性のため、旧形式も処理
        return self._load_sources_legacy(alignment_config, pair_name)
    
    def load_source_and_target_for_pair(self, pair_name: str) -> tuple:
        """
        アラインメントペアのソースとターゲットのデータソースを分けてロード
        複数のファイルデータソースがある場合は統合グラフを作成してパフォーマンスを向上
        
        Args:
            pair_name: アラインメントペア名
            
        Returns:
            (source_datasources, target_datasources) のタプル
        """
        alignment_config = self.config_loader.load_alignment_config(pair_name)
        
        # ソースデータソースをロード
        source_datasets = alignment_config.get("source_datasets", [])
        source_endpoints = alignment_config.get("source_endpoints", {})
        source_sources = self._load_dataset_list(source_datasets, pair_name, "source")
        source_sources.extend(self._load_endpoint_dict(source_endpoints))
        
        # ターゲットデータソースをロード
        target_datasets = alignment_config.get("target_datasets", [])
        target_endpoints = alignment_config.get("target_endpoints", {})
        target_sources = self._load_dataset_list(target_datasets, pair_name, "target")
        target_sources.extend(self._load_endpoint_dict(target_endpoints))
        
        # 複数のファイルデータソースがある場合は統合（パフォーマンス最適化）
        source_sources = self._merge_file_sources(source_sources, f"{pair_name}_source_merged")
        target_sources = self._merge_file_sources(target_sources, f"{pair_name}_target_merged")

        # RDFS limited materialization（既定OFF。ONの場合のみロード後のグラフに適用）
        if self.rdfs_materialize:
            self._apply_rdfs_materialize(source_sources, source_datasets, pair_name, 'source')
            self._apply_rdfs_materialize(target_sources, target_datasets, pair_name, 'target')

        return (source_sources, target_sources)

    def _apply_rdfs_materialize(self, sources, dataset_configs, pair_name, side):
        """sources[0].graph に対して rdfs5/7/9/11 の限定的 materialization を適用（既定OFF時は未呼出）。
        キャッシュは data/datasets/_materialized/ にソート済み .nt。元の .ttl/.owl は変更しない。"""
        if not sources or not hasattr(sources[0], 'graph'):
            return
        cache_key = f"{pair_name}_{side}"
        if cache_key in self._materialize_done:
            return
        import os as _os
        import time as _time
        from modules.rdfs_materializer import load_or_build, DEFAULT_RULES
        project_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        cache_dir = _os.path.join(project_root, 'data', 'datasets', '_materialized')
        file_paths = []
        for d in dataset_configs:
            p = d.get('path')
            if p:
                fp = p if _os.path.isabs(p) else _os.path.join(project_root, p)
                file_paths.append(fp)
        if not file_paths:
            return
        graph = sources[0].graph
        before = len(graph)
        t0 = _time.time()
        stats = load_or_build(graph, file_paths, cache_dir, rules=DEFAULT_RULES, verbose=True)
        elapsed = _time.time() - t0
        after = len(graph)
        print(f"  [rdfs-materialize] {pair_name}/{side}: {before} -> {after} triples "
              f"(+{after-before}, {elapsed:.2f}s) rules={stats.get('rules')} cache_hit={stats.get('cache_hit')}")
        self._materialize_done.add(cache_key)
        self.last_materialize_stats[cache_key] = {
            'pair_name': pair_name, 'side': side,
            'triples_before': before, 'triples_after': after,
            'elapsed_sec': round(elapsed, 3), 'rules': stats.get('rules'),
            'cache_hit': stats.get('cache_hit'),
        }
        alignment_config = self.config_loader.load_alignment_config(pair_name)
        sources = {}
        
        # ファイルベースのデータセット
        if "datasets" in alignment_config and alignment_config["datasets"]:
            datasets = alignment_config["datasets"]
            
            # 新形式（文字列のリスト）か旧形式（辞書のリスト）かを判定
            if isinstance(datasets, list) and len(datasets) > 0:
                if isinstance(datasets[0], str):
                    # 新形式: datasets_registry.json のIDを参照
                    for dataset_id in datasets:
                        if dataset_id not in self.sources_cache:
                            dataset_info = self.config_loader.get_dataset_info(dataset_id)
                            if dataset_info:
                                source = DataSourceFactory.create_source(dataset_info, self.config_loader)
                                self.sources_cache[dataset_id] = source
                        
                        if dataset_id in self.sources_cache:
                            sources[dataset_id] = self.sources_cache[dataset_id]
                
                elif isinstance(datasets[0], dict):
                    # 旧形式: alignment.json 内に直接定義
                    # この場合は datasets_registry.json を使わず、直接ロード
                    for idx, dataset_dict in enumerate(datasets):
                        cache_key = f"{pair_name}_dataset_{idx}"
                        if cache_key not in self.sources_cache:
                            source = DataSourceFactory.create_source(dataset_dict, self.config_loader)
                            self.sources_cache[cache_key] = source
                        sources[cache_key] = self.sources_cache[cache_key]
        
        # エンドポイントベースのデータセット
        if "endpoints" in alignment_config and alignment_config["endpoints"]:
            for endpoint_id, endpoint_url in alignment_config["endpoints"].items():
                endpoint_key = f"endpoint_{endpoint_id}"
                if endpoint_key not in self.sources_cache:
                    dataset_info = self.config_loader.get_dataset_info(endpoint_key)
                    if dataset_info:
                        source = DataSourceFactory.create_source(dataset_info, self.config_loader)
                        self.sources_cache[endpoint_key] = source
                
                if endpoint_key in self.sources_cache:
                    sources[endpoint_id] = self.sources_cache[endpoint_key]
        
        return sources
    
    def _merge_file_sources(self, sources: List, cache_key: str) -> List:
        """
        複数のファイルデータソースを統合グラフに結合
        パフォーマンス最適化のため、クエリ実行のたびに統合するのではなく事前に統合
        
        Args:
            sources: データソースのリスト
            cache_key: キャッシュキー
            
        Returns:
            統合されたデータソースのリスト（1つまたは元のまま）
        """
        if not sources:
            return sources
        
        # エンドポイントベースの場合は統合不要
        if not hasattr(sources[0], 'graph'):
            return sources
        
        # 1つだけの場合は統合不要
        if len(sources) == 1:
            return sources
        
        # キャッシュをチェック
        if cache_key in self.sources_cache:
            return [self.sources_cache[cache_key]]
        
        # 複数のファイルデータソースを統合
        print(f"  - {len(sources)}個のファイルデータソースを統合中...")
        merged_graph = rdflib.Graph()
        for source in sources:
            merged_graph += source.graph
        
        # 統合グラフを持つ新しいデータソースを作成(フォールバック機能付き)
        class MergedFileDataSource:
            def __init__(self, graph, individual_sources):
                self.graph = graph
                self.individual_sources = individual_sources  # フォールバック用
                self.dataset_info = {"type": "file", "merged": True}
            
            def query(self, sparql_query, timeout: int = 60):
                """クエリを実行（rdflibバグ対策 + 個別ファイルフォールバック + タイムアウト）
                signal.SIGALRM をクロスプラットフォームな concurrent.futures ベースに統一。"""
                # 方法1: 統合グラフで実行
                try:
                    from rdflib.plugins.sparql import prepareQuery

                    def _try_prepared():
                        prepared = prepareQuery(sparql_query)
                        results = self.graph.query(prepared)
                        return self._convert_results(results)

                    try:
                        return _run_with_timeout(_try_prepared, timeout)
                    except TimeoutError:
                        raise
                    except Exception:
                        def _try_direct():
                            results = self.graph.query(sparql_query)
                            return self._convert_results(results)
                        return _run_with_timeout(_try_direct, timeout)

                except TimeoutError:
                    # 内側の re-raise (566-567行) を、この外側の
                    # except Exception (旧コードでは無条件) が RuntimeError に
                    # 握り替えてしまい、呼び出し側が timeout と error を区別できなかった
                    # バグを修正（10000件上限撤廃で初めて>60秒クエリが実運用に現れ発覚）。
                    raise
                except Exception as e:
                    error_msg = str(e)

                    # rdflib内部エラーの場合、個別ファイルで試す
                    if "postParse" in error_msg or "tokenList" in error_msg or "<lambda>" in error_msg:
                        import sys as _sys
                        print(f"[SWALLOW-BRANCH] merged rdflib内部エラー→個別ソースfallback入り: {error_msg[:100]}",
                              file=_sys.stderr, flush=True)  # A1/A4: ログのみ・挙動不変
                        # 方法2: 個別ファイルに対してクエリを実行し、結果をマージ
                        try:
                            return self._query_individual_sources(sparql_query, timeout)
                        except:
                            pass

                        # 方法3: クエリを簡略化
                        try:
                            import re
                            simplified = re.sub(r'\s+', ' ', sparql_query).strip()
                            if simplified != sparql_query:
                                def _try_simplified():
                                    results = self.graph.query(simplified)
                                    return self._convert_results(results)
                                return _run_with_timeout(_try_simplified, timeout)
                        except Exception:
                            pass

                        # 握り潰さず伝播（呼び出し側が「エラー」と「0件」を区別できるように）。
                        # exp1 はこのマージグラフ経路を通る。以前の return [] は rdflib 内部エラーを
                        # 「該当0件」と混同させ、緩和を誤起動させていた。
                        raise RuntimeError(f"SPARQL 実行失敗(rdflib内部エラー・全フォールバック失敗): {error_msg}")
                    else:
                        raise RuntimeError(f"SPARQL クエリの実行に失敗: {e}")
            
            def _query_individual_sources(self, sparql_query, timeout: int = 60):
                """個別のデータソースに対してクエリを実行し、結果をマージ"""
                all_results = []
                seen_results = set()  # 重複を避けるため
                
                for source in self.individual_sources:
                    try:
                        source_results = source.query(sparql_query, timeout)
                        for result in source_results:
                            # 結果を文字列化して重複チェック
                            result_str = str(sorted(result.items()))
                            if result_str not in seen_results:
                                seen_results.add(result_str)
                                all_results.append(result)
                    except:
                        import sys as _sys
                        _ei = _sys.exc_info()[0]
                        print(f"[SWALLOW-611] 個別ソースクエリのエラーを握り潰し(continue): "
                              f"{_ei.__name__ if _ei else '?'}", file=_sys.stderr, flush=True)  # A1/A4: ログのみ・挙動不変
                        # 個別ソースのエラーは無視して続行
                        continue
                
                return all_results
            
            def _convert_results(self, results):
                """rdflib の結果を辞書リストに変換（postParse2エラー対策 + 無限ループ対策）"""
                converted = []
                # 10000件の打ち切りを撤廃（単純クラス側と同じ理由・同じ扱い）。
                CAP_REFERENCE = 10000
                self.last_result_true_count = None
                self.last_result_cap_hit = False
                try:
                    # results.varsを先に取得（遅延評価を回避）
                    try:
                        vars_list = list(results.vars) if hasattr(results, 'vars') else []
                    except Exception:
                        # varsの取得に失敗した場合、結果を直接処理
                        vars_list = []

                    # 全行を変換してから安定ソート→先頭 max_results 件を採る（決定化）。
                    # 以前は islice で先頭 max_results 件のみ取得しており、rdflib のイテレーション順が
                    # 非決定的なため run 毎に異なる部分集合が返っていた。
                    for row in results:
                        row_dict = {}
                        if vars_list:
                            # 変数名が取得できた場合
                            for var in vars_list:
                                try:
                                    value = row[var]
                                    if value is not None:
                                        row_dict[str(var)] = str(value)
                                except (KeyError, IndexError):
                                    continue
                        else:
                            # 変数名が取得できなかった場合、rowから直接変数を抽出
                            if hasattr(row, 'asdict'):
                                row_dict = {k: str(v) for k, v in row.asdict().items() if v is not None}
                            elif hasattr(row, '__iter__'):
                                # タプルの場合、s, p, o などの標準変数名を使用
                                for i, value in enumerate(row):
                                    if value is not None:
                                        row_dict[f"var{i}"] = str(value)

                        if row_dict:  # 空でない場合のみ追加
                            converted.append(row_dict)

                    converted.sort(key=_stable_row_key)
                    self.last_result_true_count = len(converted)
                    self.last_result_cap_hit = len(converted) > CAP_REFERENCE
                    # 打ち切りなし: converted はスライスせずそのまま返す。

                except Exception as e:
                    # 結果の変換中のエラー - より詳細な情報を提供
                    error_msg = f"クエリ結果の変換に失敗: {type(e).__name__}: {str(e)[:200]}"
                    raise RuntimeError(error_msg)
                return converted

            def get_type(self):
                return "file"
        
        merged_source = MergedFileDataSource(merged_graph, sources)
        self.sources_cache[cache_key] = merged_source
        
        print(f"  - 統合完了: {len(merged_graph)} トリプル")
        return [merged_source]
    
    def _load_sources_legacy(self, alignment_config, pair_name):
        """旧形式のデータソースロード（後方互換性）"""
        sources = {}
        
        # ファイルベースのデータセット
        if "datasets" in alignment_config and alignment_config["datasets"]:
            datasets = alignment_config["datasets"]
            
            # 新形式（文字列のリスト）か旧形式（辞書のリスト）かを判定
            if isinstance(datasets, list) and len(datasets) > 0:
                if isinstance(datasets[0], str):
                    # 新形式: datasets_registry.json のIDを参照
                    for dataset_id in datasets:
                        if dataset_id not in self.sources_cache:
                            dataset_info = self.config_loader.get_dataset_info(dataset_id)
                            if dataset_info:
                                source = DataSourceFactory.create_source(dataset_info, self.config_loader)
                                self.sources_cache[dataset_id] = source
                        
                        if dataset_id in self.sources_cache:
                            sources[dataset_id] = self.sources_cache[dataset_id]
                
                elif isinstance(datasets[0], dict):
                    # 旧形式: alignment.json 内に直接定義
                    for idx, dataset_dict in enumerate(datasets):
                        cache_key = f"{pair_name}_dataset_{idx}"
                        if cache_key not in self.sources_cache:
                            source = DataSourceFactory.create_source(dataset_dict, self.config_loader)
                            self.sources_cache[cache_key] = source
                        sources[cache_key] = self.sources_cache[cache_key]
        
        # エンドポイントベースのデータセット
        if "endpoints" in alignment_config and alignment_config["endpoints"]:
            for endpoint_id, endpoint_url in alignment_config["endpoints"].items():
                endpoint_key = f"endpoint_{endpoint_id}"
                if endpoint_key not in self.sources_cache:
                    dataset_info = self.config_loader.get_dataset_info(endpoint_key)
                    if dataset_info:
                        source = DataSourceFactory.create_source(dataset_info, self.config_loader)
                        self.sources_cache[endpoint_key] = source
                
                if endpoint_key in self.sources_cache:
                    sources[endpoint_id] = self.sources_cache[endpoint_key]
        
        return sources
