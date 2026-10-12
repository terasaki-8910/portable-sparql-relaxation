"""
AlignmentFilter: EDOALアライメントに基づいてSPARQLクエリをフィルタリングするモジュール

判定ロジック:
1. EDOALのDOCTYPE <!ENTITY> 宣言を正規表現で解析 → namespace map を取得
2. <onto1>/<Ontology rdf:about="..."> からソースnamespaceを特定
3. <entity1> 配下の全URIを正規表現 + 実体参照展開で収集
4. クエリのURIをソースnsで絞り込み、entity1 URI集合との積集合をチェック
5. 積集合が空なら「アライメントなし」と判定

注意:
- 全解析を正規表現ベースで実装し、ElementTreeの DOCTYPE エンティティ展開に依存しない
  （xml.etree.ElementTree はカスタムエンティティ &xxx; の展開が不安定なため）
- SPARQLクエリの <full_uri> 形式と PREFIX+QName 形式の両方に対応
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


class AlignmentFilter:
    """
    EDOALファイルを解析し、SPARQLクエリにアライメントが存在するかを判定する。

    すべての解析は正規表現ベースで行い、ElementTreeのエンティティ展開に依存しない。
    PREFIX + QName 形式のクエリ（agro:Taxon 等）にも対応。
    """

    def __init__(self, edoal_path: Path):
        """
        Args:
            edoal_path: EDOALファイルのパス

        Raises:
            FileNotFoundError: EDOALファイルが存在しない場合
        """
        self.edoal_path = Path(edoal_path)
        if not self.edoal_path.exists():
            raise FileNotFoundError(f"EDOALファイルが見つかりません: {self.edoal_path}")

        with open(self.edoal_path, 'r', encoding='utf-8') as f:
            self._raw_text = f.read()

        self.entity_decls: Dict[str, str] = self._parse_entity_decls()
        self.source_namespace: str = self._parse_source_namespace()
        self.entity1_uris: Set[str] = self._collect_entity1_uris()

    # ─────────────────────────────────────────────────────────────────
    # 内部解析メソッド (正規表現ベース)
    # ─────────────────────────────────────────────────────────────────

    def _parse_entity_decls(self) -> Dict[str, str]:
        """
        DOCTYPE 内の <!ENTITY name "uri"> 宣言を正規表現で全件抽出し dict に変換。
        ダブルクォート・シングルクォートの両形式に対応。
        """
        decls: Dict[str, str] = {}
        for m in re.finditer(r'<!ENTITY\s+(\w+)\s+"([^"]*)"', self._raw_text):
            decls[m.group(1)] = m.group(2)
        for m in re.finditer(r"<!ENTITY\s+(\w+)\s+'([^']*)'", self._raw_text):
            if m.group(1) not in decls:
                decls[m.group(1)] = m.group(2)
        return decls

    def _expand_entity_refs(self, text: str) -> str:
        """&name; 形式の XML 実体参照を entity_decls に基づいて展開する。"""
        def replace(m: re.Match) -> str:
            return self.entity_decls.get(m.group(1), m.group(0))
        return re.sub(r'&(\w+);', replace, text)

    def _parse_source_namespace(self) -> str:
        """
        <onto1> ブロック内の <Ontology rdf:about="..."> からソース ontology namespace を取得。
        &xxx; 形式の実体参照は展開する。
        namespace prefix (align:onto1 等) の有無を問わず対応。
        """
        m = re.search(
            r'<(?:\w+:)?onto1\b[^>]*>(.*?)</(?:\w+:)?onto1>',
            self._raw_text, re.DOTALL
        )
        if not m:
            return ''

        onto1_content = m.group(1)

        for pattern in (r'rdf:about="([^"]*)"', r"rdf:about='([^']*)'"):
            about_m = re.search(pattern, onto1_content)
            if about_m:
                return self._expand_entity_refs(about_m.group(1))

        return ''

    def _collect_entity1_uris(self) -> Set[str]:
        """
        全 <entity1> ブロック内の rdf:about 属性値を収集し、実体参照を展開した URI セットを返す。

        Class / Property / Relation / edoal:and / edoal:or / edoal:compose / edoal:inverse 等、
        ネストした複合構造も含め、ブロック内すべての rdf:about を再帰的に収集する。
        """
        uris: Set[str] = set()
        for m in re.finditer(
            r'<(?:\w+:)?entity1\b[^>]*>(.*?)</(?:\w+:)?entity1>',
            self._raw_text, re.DOTALL
        ):
            block = m.group(1)
            for pattern in (r'rdf:about="([^"]*)"', r"rdf:about='([^']*)'"):
                for about in re.findall(pattern, block):
                    expanded = self._expand_entity_refs(about)
                    if expanded.startswith('http'):
                        uris.add(expanded)
        return uris

    # ─────────────────────────────────────────────────────────────────
    # クエリ URI 抽出
    # ─────────────────────────────────────────────────────────────────

    def extract_query_uris(self, query: str) -> Set[str]:
        """
        SPARQL クエリから URI を全件抽出する。

        対応形式:
        - <http://...> 形式 (full URI)
        - PREFIX prefix: <base_uri> + prefix:localname 形式 (QName)
        - PREFIX : <base_uri> + :localname 形式 (default prefix / empty prefix)

        PREFIX 宣言のベース URI そのものは URI として収集しない。
        """
        uris: Set[str] = set()

        # ── PREFIX 宣言を解析 ──
        # PREFIX word: <uri> または PREFIX : <uri> (空プレフィックス)
        prefix_map: Dict[str, str] = {}
        for m in re.finditer(
            r'(?i)\bPREFIX\s+(\w*)\s*:\s*<([^>]+)>',
            query
        ):
            prefix_map[m.group(1)] = m.group(2)

        prefix_bases: Set[str] = set(prefix_map.values())

        # ── <full_uri> 形式を収集（PREFIX 宣言のベース URI は除外）──
        for m in re.finditer(r'<(https?://[^>\s]+)>', query):
            uri = m.group(1)
            if uri not in prefix_bases:
                uris.add(uri)

        # ── QName を展開（PREFIX 宣言行を除いたクエリ本体でスキャン）──
        # PREFIX/BASE 宣言行をクエリから除去してボディを取得
        body = re.sub(
            r'(?i)^\s*(?:PREFIX|BASE)\s+\w*\s*:\s*<[^>]+>\s*$',
            '',
            query,
            flags=re.MULTILINE
        )

        for prefix, base_uri in prefix_map.items():
            if prefix:
                # 通常プレフィックス: prefix:localname
                # localname は英字/アンダースコアで始まり、末尾の . や - は除外する
                # （SPARQL のトリプル終端 `.` や `-` が localname に混入するのを防ぐ）
                pattern = r'\b' + re.escape(prefix) + r':([A-Za-z_][A-Za-z0-9_\-\.]*)'
                for m in re.finditer(pattern, body):
                    local_name = m.group(1).rstrip('.-')
                    if local_name:
                        uris.add(base_uri + local_name)
            else:
                # 空プレフィックス (default prefix): :localname
                for m in re.finditer(r'(?<!\w):([A-Za-z_][A-Za-z0-9_\-\.]*)', body):
                    local_name = m.group(1).rstrip('.-')
                    if local_name:
                        uris.add(base_uri + local_name)

        return uris

    def filter_by_source_namespace(self, uris: Set[str]) -> Set[str]:
        """ソース ontology namespace に属する URI のみに絞り込む。"""
        if not self.source_namespace:
            return uris
        return {uri for uri in uris if uri.startswith(self.source_namespace)}

    # ─────────────────────────────────────────────────────────────────
    # 公開フィルタリング API
    # ─────────────────────────────────────────────────────────────────

    def has_alignment(self, query: str) -> bool:
        """
        クエリにアライメントが存在するか判定（True/False のみ返却）。

        判定フロー:
        1. クエリから全 URI を抽出
        2. ソース namespace に属する URI のみに絞り込む
        3. 絞り込んだ URI と entity1_uris の積集合が空でなければ True
        """
        query_uris = self.extract_query_uris(query)
        source_uris = self.filter_by_source_namespace(query_uris)
        return bool(source_uris & self.entity1_uris)

    def check_alignment(self, query: str) -> dict:
        """
        クエリにアライメントが存在するか詳細チェック（デバッグ用）。

        Returns:
            dict with keys:
                has_alignment (bool)
                reason (str): 'matched' | 'no_source_uris' | 'no_entity1_match'
                all_query_uris (list): クエリから抽出した全 URI
                source_uris (list): ソース ns 絞り込み後の URI
                matched_uris (list): entity1 との交差 URI
        """
        query_uris = self.extract_query_uris(query)
        source_uris = self.filter_by_source_namespace(query_uris)
        matched_uris = source_uris & self.entity1_uris

        if matched_uris:
            reason = 'matched'
        elif not source_uris:
            reason = 'no_source_uris'
        else:
            reason = 'no_entity1_match'

        return {
            'has_alignment': bool(matched_uris),
            'reason': reason,
            'all_query_uris': sorted(query_uris),
            'source_uris': sorted(source_uris),
            'matched_uris': sorted(matched_uris),
        }

    # ─────────────────────────────────────────────────────────────────
    # デバッグ出力
    # ─────────────────────────────────────────────────────────────────

    def dump_state(
        self,
        output_path: Path,
        excluded_queries: Optional[List[dict]] = None,
        included_queries: Optional[List[str]] = None,
    ) -> None:
        """
        デバッグ用: AlignmentFilter の内部状態とフィルタ結果を JSON に保存。

        Args:
            output_path: 出力 JSON ファイルのパス
            excluded_queries: 除外されたクエリのリスト（query_file・reason 等を含む dict）
            included_queries: 含まれるクエリのファイル名リスト
        """
        state = {
            'edoal_file': str(self.edoal_path),
            'entity_decls': self.entity_decls,
            'source_namespace': self.source_namespace,
            'entity1_uris': sorted(self.entity1_uris),
            'entity1_count': len(self.entity1_uris),
            'excluded_count': len(excluded_queries or []),
            'included_count': len(included_queries or []),
            'excluded_queries': excluded_queries or [],
            'included_queries': included_queries or [],
        }
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
