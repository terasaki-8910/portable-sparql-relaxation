import subprocess
import json
import os

class AstSerializer:
    """
    Javaで実装されたSPARQLシリアライザーを呼び出し、
    書き換え後のJSON ASTをSPARQLクエリ文字列に変換するラッパー。
    """

    def __init__(self, project_root: str = None):
        """
        プロジェクトのルートディレクトリを初期化時に受け取る。

        :param project_root: プロジェクトのルートディレクトリへのパス。
                            Noneの場合は、このファイルから相対的に推測する。
        """
        if project_root is None:
            # このファイルの場所からプロジェクトルートを推測
            current_dir = os.path.dirname(os.path.abspath(__file__))
            self.project_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
        else:
            self.project_root = project_root

        # ビルド済みjarファイルのパス
        self.jar_path = os.path.join(self.project_root, 'build', 'libs', 'sparql-translator-complex-alignment.jar')

        # OSに応じてJava実行ファイルを設定
        if os.name == 'nt':  # Windows
            self.java_exe = os.path.join('C:\\Program Files\\Java\\jdk-21\\bin\\java.exe')
            if not os.path.exists(self.java_exe):
                self.java_exe = 'java.exe'  # フォールバック
        else:  # Unix系 (Linux, macOS)
            self.java_exe = 'java'

    def serialize(self, ast: dict) -> str:
        """
        書き換え後のJSON ASTをSPARQLクエリ文字列に変換する。

        :param ast: 書き換え後のJSON AST（辞書形式）
        :return: シリアライズされたSPARQLクエリ文字列
        :raises RuntimeError: Javaプログラムの実行に失敗した場合
        """
        # jarファイルの存在確認
        if not os.path.exists(self.jar_path):
            raise RuntimeError(f"Could not find jar file at {self.jar_path}. "
                             "Please run './gradlew build' first.")

        # ASTをJSON文字列に変換
        ast_json_string = json.dumps(ast)

        # Javaプログラムを直接実行するためのコマンドを構築
        # SPARQLシリアライザーのメインクラスを指定
        command = [
            self.java_exe,
            '-cp',
            self.jar_path,
            'sparql_serializer_java.SparqlAstSerializer'
        ]

        try:
            # サブプロセスとしてJavaプログラムを実行し、ASTをstdinに渡す
            result = subprocess.run(
                command,
                cwd=self.project_root,
                input=ast_json_string,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                check=True,
                timeout=30  # タイムアウト設定
            )

            # 標準出力からSPARQLクエリ文字列を取得
            output_str = result.stdout.strip()

            if not output_str:
                raise RuntimeError("Java serializer returned empty output.")

            return output_str

        except subprocess.CalledProcessError as e:
            # Javaプログラムがエラーを返した場合
            error_message = f"SPARQL AST Serializer (Java) failed with exit code {e.returncode}.\n"
            error_message += f"Stderr:\n{e.stderr}\n"
            error_message += f"Stdout:\n{e.stdout}"
            raise RuntimeError(error_message)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"SPARQL AST Serializer timed out after 30 seconds.")
        except FileNotFoundError:
            raise RuntimeError(f"Could not find Java executable at {self.java_exe}. "
                             "Ensure Java is installed and available.")


if __name__ == '__main__':
    # このモジュールを直接実行した場合のテスト用コード
    import pprint
    
    # テスト用の書き換え済みAST
    test_ast = {
        'prefixes': {
            '': 'http://ekaw#',
            'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
        },
        'ast': {
            'type': 'group',
            'patterns': [
                {
                    'type': 'bgp',
                    'triples': [
                        {
                            'type': 'triple',
                            'subject': {'type': 'variable', 'value': 'paper'},
                            'predicate': {'type': 'uri', 'value': 'http://cmt#readByReviewer'},
                            'object': {'type': 'variable', 'value': 'reviewer'}
                        },
                        {
                            'type': 'triple',
                            'subject': {'type': 'variable', 'value': 'paper'},
                            'predicate': {'type': 'uri', 'value': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'},
                            'object': {'type': 'uri', 'value': 'http://cmt#Paper'}
                        }
                    ]
                }
            ]
        },
        'queryType': 'SELECT',
        'isDistinct': False,
        'selectVariables': ['reviewer'],
        'orderBy': [],
        'limit': None,
        'offset': None
    }

    print("--- Input AST ---")
    pprint.pprint(test_ast)

    # このファイルの場所からプロジェクトルートを特定
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))

    try:
        serializer = AstSerializer(project_root)
        sparql_query = serializer.serialize(test_ast)
        
        print("\n--- Serialized SPARQL Query ---")
        print(sparql_query)
        
    except RuntimeError as e:
        print(f"\n--- An error occurred ---")
        print(e)
