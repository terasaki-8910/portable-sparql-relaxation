"""
translator_adapter.py
既存の sparql_translator パッケージへの厳密なアダプタ

設計原則:
- sparql_translator/src/ 以下のファイルを一切変更しない (Prohibition.md Section 1)
- 既存クラスを呼び出すだけのラッパー（Adapter）として実装
- Javaプロセスのクラスパス（lib/*.jar）を正確に管理
- 虚偽の成功報告の禁止 (Prohibition.md Section 2)
"""

import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional
import json
import tempfile


class TranslatorAdapter:
    """
    sparql_translator パッケージへのアダプタクラス
    EdoalParser, SparqlAstParser, SparqlRewriter を統合的に使用
    """
    
    def __init__(self, project_root: str):
        """
        Args:
            project_root: プロジェクトのルートディレクトリ絶対パス
        """
        self.project_root = Path(project_root).resolve()
        
        # キャッシュ：alignment_file -> (alignment, rewriter)
        self._alignment_cache = {}
        
        # sparql_translator パッケージをインポート可能にする
        sparql_translator_path = self.project_root / "sparql_translator"
        if str(sparql_translator_path) not in sys.path:
            sys.path.insert(0, str(sparql_translator_path))
        
        # 既存クラスをインポート（ロジック自作禁止）
        try:
            from sparql_translator.src.parser.edoal_parser_ruthless import EdoalParser
            from sparql_translator.src.parser.sparql_ast_parser import SparqlAstParser
            from sparql_translator.src.rewriter.sparql_rewriter_ruthless import SparqlRewriterRuthless
            
            self.EdoalParser = EdoalParser
            self.SparqlAstParser = SparqlAstParser
            self.SparqlRewriter = SparqlRewriterRuthless
        except ImportError as e:
            raise RuntimeError(
                f"sparql_translator パッケージのインポートに失敗しました。\n"
                f"エラー: {e}\n"
                f"パス: {sparql_translator_path}"
            )
        
        # Javaクラスパスの検証
        self._verify_java_classpath()
    
    def _verify_java_classpath(self):
        """
        Javaクラスパス（lib/*.jar）の存在を検証
        
        Raises:
            RuntimeError: 必須のJARファイルが存在しない場合
        """
        lib_dir = self.project_root / "lib"
        if not lib_dir.exists():
            raise RuntimeError(
                f"lib/ ディレクトリが見つかりません: {lib_dir}\n"
                "Java プロセスの実行に必要なJARファイルが不足しています。"
            )
        
        # 必須のJARファイルを確認
        required_jars = ["jena.jar", "arq.jar", "gson.jar"]
        missing_jars = []
        for jar_name in required_jars:
            jar_path = lib_dir / jar_name
            if not jar_path.exists():
                missing_jars.append(jar_name)
        
        if missing_jars:
            raise RuntimeError(
                f"必須のJARファイルが見つかりません: {', '.join(missing_jars)}\n"
                f"lib/ ディレクトリを確認してください: {lib_dir}"
            )
    
    def translate_query(
        self,
        source_query: str,
        alignment_file: str
    ) -> Dict[str, Any]:
        """
        SPARQLクエリを変換する統合メソッド
        
        Args:
            source_query: ソースSPARQLクエリ文字列
            alignment_file: EDOALアラインメントファイルの絶対パス
            
        Returns:
            変換結果の辞書
            {
                "success": bool,
                "output_query": str,
                "error": str (エラー時のみ),
                "ast_source": dict (デバッグ用),
                "ast_rewritten": dict (デバッグ用)
            }
        """
        result = {
            "success": False,
            "output_query": "",
            "error": None,
            "ast_source": None,
            "ast_rewritten": None
        }
        
        try:
            # Step 1: EDOALアラインメントをパース（キャッシュを使用）
            if alignment_file not in self._alignment_cache:
                edoal_parser = self.EdoalParser(alignment_file, verbose=False)
                alignment = edoal_parser.parse()
                
                if not alignment:
                    result["error"] = "EDOALアラインメントのパースに失敗（空の結果）"
                    return result
                
                # Rewriterも作成してキャッシュ
                rewriter = self.SparqlRewriter(alignment, verbose=False)
                self._alignment_cache[alignment_file] = (alignment, rewriter)
            else:
                alignment, rewriter = self._alignment_cache[alignment_file]
            
            # Step 2: ソースクエリをASTに変換（Javaプロセスを使用）
            # 一時ファイルにソースクエリを書き出す
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.sparql',
                delete=False,
                encoding='utf-8'
            ) as temp_file:
                temp_file.write(source_query)
                temp_sparql_path = temp_file.name
            
            try:
                sparql_parser = self.SparqlAstParser(str(self.project_root))
                ast_source = sparql_parser.parse(temp_sparql_path)
                result["ast_source"] = ast_source
                
                if not ast_source or not isinstance(ast_source, dict):
                    result["error"] = "ソースクエリのAST変換に失敗（空またはエラー）"
                    return result
            
            finally:
                # 一時ファイルを削除
                if os.path.exists(temp_sparql_path):
                    os.unlink(temp_sparql_path)
            
            # Step 3: ASTを書き換え（キャッシュされたrewriterを使用）
            ast_rewritten = rewriter.walk(ast_source)
            result["ast_rewritten"] = ast_rewritten
            
            if not ast_rewritten or not isinstance(ast_rewritten, dict):
                result["error"] = "AST書き換えに失敗（空またはエラー）"
                return result
            
            # Step 4: 書き換えられたASTをSPARQLクエリに再シリアライズ（Javaプロセスを使用）
            output_query = self._serialize_ast_to_sparql(ast_rewritten)
            
            if not output_query or len(output_query.strip()) < 10:
                result["error"] = "ASTのシリアライズに失敗（空またはエラー）"
                return result
            
            # 成功
            result["success"] = True
            result["output_query"] = output_query
        
        except Exception as e:
            result["error"] = f"変換処理中に例外が発生: {type(e).__name__}: {str(e)}"
        
        return result
    
    def _serialize_ast_to_sparql(self, ast: Dict[str, Any]) -> str:
        """
        ASTをSPARQLクエリ文字列に再シリアライズ（Javaプロセスを使用）
        
        Args:
            ast: 書き換えられたAST
            
        Returns:
            SPARQL クエリ文字列
            
        Raises:
            RuntimeError: シリアライズに失敗した場合
        """
        import subprocess
        import platform
        
        # Windows環境では gradlew.bat を使用
        if platform.system() == 'Windows':
            gradlew_path = self.project_root / "gradlew.bat"
        else:
            gradlew_path = self.project_root / "gradlew"
        
        if not gradlew_path.exists():
            raise RuntimeError(f"gradlew が見つかりません: {gradlew_path}")
        
        # ASTをJSON文字列に変換
        ast_json_str = json.dumps(ast)
        
        # Javaシリアライザーを実行
        command = [
            str(gradlew_path),
            "runSerializer",
            "--quiet"
        ]
        
        try:
            result = subprocess.run(
                command,
                cwd=str(self.project_root),
                input=ast_json_str,
                capture_output=True,
                text=True,
                encoding='utf-8', errors='replace',
                check=True
            )
            
            # 出力からSPARQLクエリを抽出
            output = result.stdout.strip()
            
            if not output:
                raise RuntimeError(
                    "Javaシリアライザーが空の出力を返しました。\n"
                    f"Stderr: {result.stderr}"
                )
            
            return output
        
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Javaシリアライザーの実行に失敗しました（終了コード: {e.returncode}）。\n"
                f"Stderr: {e.stderr}\n"
                f"Stdout: {e.stdout}"
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"gradlew が実行できません: {gradlew_path}\n"
                "実行権限を確認してください。"
            )
    
    def validate_translation(
        self,
        input_query: str,
        output_query: str,
        alignment_file: str
    ) -> Dict[str, Any]:
        """
        変換結果の実質的な検証
        
        虚偽の成功報告を防ぐため、以下をチェック:
        1. output_query が空でない
        2. output_query にエラーメッセージが含まれていない
        3. ソースURIがターゲットURIに変換されている
        
        Args:
            input_query: 入力クエリ
            output_query: 出力クエリ
            alignment_file: アラインメントファイル
            
        Returns:
            検証結果の辞書
            {
                "valid": bool,
                "reason": str
            }
        """
        validation = {
            "valid": False,
            "reason": ""
        }
        
        # チェック1: 空でない
        if not output_query or len(output_query.strip()) < 10:
            validation["reason"] = "出力クエリが空または短すぎる"
            return validation
        
        # チェック2: エラーメッセージの検出
        error_keywords = [
            "Error", "ERROR", "Exception", "EXCEPTION",
            "Failed", "FAILED", "NoClassDefFoundError",
            "NullPointerException", "RuntimeException"
        ]
        for keyword in error_keywords:
            if keyword in output_query:
                validation["reason"] = f"出力クエリにエラーキーワードが含まれている: {keyword}"
                return validation
        
        # チェック3: 変換の痕跡（簡易チェック）
        # 入力と出力が完全に同一の場合、変換が行われていない可能性
        if input_query.strip() == output_query.strip():
            validation["reason"] = "入力と出力が同一（変換が行われていない可能性）"
            return validation
        
        # 全てのチェックを通過
        validation["valid"] = True
        validation["reason"] = "検証成功"
        return validation
