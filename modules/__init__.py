"""
SPARQL Translation System - Adapter Layer
このパッケージは既存のsparql_translatorパッケージへの厳密なアダプタレイヤーとして機能します。

禁止事項遵守:
- sparql_translator/src/ 以下のファイルを変更しない
- EDOALパース、SPARQL AST解析、クエリ書き換えロジックを再実装しない
- 既存クラスを呼び出すだけのラッパー（Adapter）として実装
"""

__version__ = "2.0.0"
__all__ = [
    "config_loader",
    "data_loader",
    "translator_adapter",
    "evaluator",
    "logger"
]
