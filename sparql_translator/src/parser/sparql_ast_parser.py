import subprocess
import json
import os

class SparqlAstParser:
    """
    Javaで実装されたSPARQLパーサーを呼び出し、
    クエリ文字列をJSON形式のASTに変換するラッパー。
    """

    def __init__(self, project_root: str):
        """
        プロジェクトのルートディレクトリを初期化時に受け取る。
        """
        self.project_root = project_root
        # ビルド済みjarファイルのパス
        self.jar_path = os.path.join(project_root, 'build', 'libs', 'sparql-translator-complex-alignment.jar')

        # OSに応じてJava実行ファイルを設定
        if os.name == 'nt':  # Windows
            self.java_exe = os.path.join('C:\\Program Files\\Java\\jdk-21\\bin\\java.exe')
            if not os.path.exists(self.java_exe):
                self.java_exe = 'java.exe'  # フォールバック
        else:  # Unix系 (Linux, macOS)
            self.java_exe = 'java'

    def parse(self, sparql_file_path: str) -> dict:
        """
        指定されたSPARQLファイルをパースし、JSON形式のASTを返す。

        :param sparql_file_path: パース対象のSPARQLファイルへのパス。
        :return: パースされたASTを表す辞書。
        :raises RuntimeError: Javaプログラムの実行に失敗した場合。
        """
        # jarファイルの存在確認
        if not os.path.exists(self.jar_path):
            raise RuntimeError(f"Could not find jar file at {self.jar_path}. "
                             "Please run './gradlew build' first.")

        # Javaプログラムを直接実行するためのコマンドを構築
        command = [
            self.java_exe,
            '-jar',
            self.jar_path,
            sparql_file_path
        ]

        try:
            # サブプロセスとしてJavaプログラムを実行
            result = subprocess.run(
                command,
                cwd=self.project_root, # プロジェクトのルートで実行
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                check=True,  # エラーが発生したら例外をスロー
                timeout=30  # タイムアウト設定
            )

            # JSON出力をパース
            try:
                return json.loads(result.stdout.strip())
            except json.JSONDecodeError:
                # 先頭のメッセージ行を削除して再試行
                output_str = result.stdout.strip()
                json_start = output_str.find('{')
                json_end = output_str.rfind('}')

                if json_start != -1 and json_end != -1:
                    json_str = output_str[json_start:json_end+1]
                    return json.loads(json_str)
                else:
                    raise RuntimeError(f"Could not find JSON in the output from Java parser.\nRaw output:\n{output_str}")

        except subprocess.CalledProcessError as e:
            # Javaプログラムがエラーを返した場合
            error_message = f"SPARQL AST Parser (Java) failed with exit code {e.returncode}.\n"
            error_message += f"Stderr:\n{e.stderr}\n"
            error_message += f"Stdout:\n{e.stdout}"
            raise RuntimeError(error_message)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"SPARQL AST Parser timed out after 30 seconds.")
        except FileNotFoundError:
            raise RuntimeError(f"Could not find Java executable at {self.java_exe}. "
                             "Ensure Java is installed and available.")
        except json.JSONDecodeError as e:
            # JSONのパースに失敗した場合
            error_message = f"Failed to decode JSON output from Java parser.\n"
            error_message += f"Error: {e}\n"
            error_message += f"Raw output:\n{result.stdout}"
            raise RuntimeError(error_message)


if __name__ == '__main__':
    # このモジュールを直接実行した場合のテスト用コード
    # プロジェクトルートからの相対パスでテストファイルを実行
    
    # このファイルの場所からプロジェクトルートを特定
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
    
    test_sparql_file = os.path.join(project_root, 'jar utiles/data/agro-db/IN1.sparql')

    print(f"Project Root: {project_root}")
    print(f"Parsing SPARQL file: {test_sparql_file}")
    
    try:
        parser = SparqlAstParser(project_root)
        ast_json = parser.parse(test_sparql_file)
        
        print("\n--- Successfully parsed SPARQL to JSON AST ---")
        import pprint
        pprint.pprint(ast_json)
        
    except RuntimeError as e:
        print(f"\n--- An error occurred ---")
        print(e)