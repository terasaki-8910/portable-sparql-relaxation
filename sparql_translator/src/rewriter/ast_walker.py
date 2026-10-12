import pprint

class AstWalker:
    """
    SPARQLのJSON ASTを再帰的に巡回し、ノードを書き換えるための基本クラス。
    """

    def walk(self, node):
        """
        指定されたノードからASTの巡回を開始する。
        """
        return self._walk_node(node)

    def _walk_node(self, node):
        """
        ノードの型に応じて、適切なvisitメソッドを呼び出すディスパッチャ。
        """
        if not isinstance(node, dict):
            return node

        node_type = node.get('type')
        visit_method_name = f'visit_{node_type}'
        visit_method = getattr(self, visit_method_name, self.visit_default)
        
        return visit_method(node)

    def visit_default(self, node):
        """
        特定のvisitメソッドが定義されていないノードのためのデフォルト処理。
        子のノードを再帰的に処理する。
        """
        new_node = {}
        for key, value in node.items():
            if isinstance(value, list):
                # リストの各要素を処理し、結果がリストの場合は展開する
                new_list = []
                for item in value:
                    result = self._walk_node(item)
                    # 結果がリストの場合は展開（flatten）
                    if isinstance(result, list):
                        new_list.extend(result)
                    else:
                        new_list.append(result)
                new_node[key] = new_list
            elif isinstance(value, dict):
                new_node[key] = self._walk_node(value)
            else:
                new_node[key] = value
        return new_node

    # --- 具体的なノードタイプのvisitメソッド (今後拡張していく) ---

    def visit_uri(self, node):
        """URIノードを処理する。"""
        # ここでURIの置換ロジックを実装する
        print(f"Visiting URI: {node['value']}")
        return node

    def visit_variable(self, node):
        """変数ノードを処理する。"""
        return node

    def visit_literal(self, node):
        """リテラルノードを処理する。"""
        return node


if __name__ == '__main__':
    # --- テスト用のサンプルAST ---
    sample_ast = {
        'ast': {
            'patterns': [
                {'triples': [
                    {'object': {'type': 'variable', 'value': 'label'},
                     'predicate': {'type': 'uri', 'value': 'http://example.com/old_predicate'},
                     'subject': {'type': 'variable', 'value': 's'},
                     'type': 'triple'}
                ],
                'type': 'bgp'}
            ],
            'type': 'group'
        },
        'prefixes': {}
    }

    print("--- Original AST ---")
    pprint.pprint(sample_ast)

    # ASTウォーカーを実行
    walker = AstWalker()
    rewritten_ast = walker.walk(sample_ast)

    print("\n--- Rewritten AST (no changes yet) ---")
    pprint.pprint(rewritten_ast)