"""
config_loader.py
データセット設定とアラインメント設定を読み込むモジュール

設計原則:
- datasets_registry.json の厳密な解釈
- alignment.json の type フィールドに基づく分岐
- コンテキスト無視の禁止 (Prohibition.md Section 3)
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any


class ConfigLoader:
    """
    統合設定ローダー
    datasets_registry.json と個別の alignment.json を読み込む
    """
    
    def __init__(self, project_root: str):
        """
        Args:
            project_root: プロジェクトのルートディレクトリ絶対パス
        """
        self.project_root = Path(project_root).resolve()
        self.datasets_registry_path = self.project_root / "data" / "datasets" / "datasets_registry.json"
        self.alignment_base_dir = self.project_root / "data" / "alignment"
        
        # データセットレジストリをロード
        self.datasets_registry = self._load_datasets_registry()
    
    def _load_datasets_registry(self) -> Dict[str, Any]:
        """
        datasets_registry.json を読み込む
        
        Returns:
            データセットレジストリの辞書
            
        Raises:
            FileNotFoundError: ファイルが存在しない場合
            json.JSONDecodeError: JSON形式が不正な場合
        """
        if not self.datasets_registry_path.exists():
            raise FileNotFoundError(
                f"datasets_registry.json が見つかりません: {self.datasets_registry_path}"
            )
        
        with open(self.datasets_registry_path, 'r', encoding='utf-8') as f:
            registry = json.load(f)
        
        return registry
    
    def get_dataset_info(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        """
        データセットIDから詳細情報を取得
        
        Args:
            dataset_id: データセットの識別子
            
        Returns:
            データセット情報の辞書、存在しない場合はNone
        """
        return self.datasets_registry.get("datasets", {}).get(dataset_id)
    
    def load_alignment_config(self, pair_name: str) -> Dict[str, Any]:
        """
        個別のアラインメントペア設定を読み込む
        
        Args:
            pair_name: アラインメントペア名（例: "agro-dbpedia", "cmt-confOf"）
            
        Returns:
            アラインメント設定の辞書
            
        Raises:
            FileNotFoundError: alignment.json が存在しない場合
        """
        alignment_dir = self.alignment_base_dir / pair_name
        alignment_config_path = alignment_dir / "alignment.json"
        
        if not alignment_config_path.exists():
            raise FileNotFoundError(
                f"alignment.json が見つかりません: {alignment_config_path}"
            )
        
        with open(alignment_config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 相対パスを絶対パスに変換
        config = self._resolve_paths(config, alignment_dir)
        
        return config
    
    def _resolve_paths(self, config: Dict[str, Any], base_dir: Path) -> Dict[str, Any]:
        """
        設定内の相対パスを絶対パスに変換
        
        Args:
            config: アラインメント設定
            base_dir: ベースディレクトリ（アラインメントペアのディレクトリ）
            
        Returns:
            パスが解決された設定
        """
        resolved_config = config.copy()
        
        # alignment_file の解決
        if "alignment_file" in config and config["alignment_file"]:
            alignment_file = Path(config["alignment_file"])
            if not alignment_file.is_absolute():
                # プロジェクトルートからの相対パスとして解釈
                resolved_config["alignment_file"] = str(self.project_root / alignment_file)
        
        # queries_dir の解決
        if "queries_dir" in config and config["queries_dir"]:
            queries_dir = Path(config["queries_dir"])
            if not queries_dir.is_absolute():
                # プロジェクトルートからの相対パスとして解釈
                resolved_config["queries_dir"] = str(self.project_root / queries_dir)
        
        # expected_output_dir の解決
        if "expected_output_dir" in config and config["expected_output_dir"]:
            expected_output_dir = Path(config["expected_output_dir"])
            if not expected_output_dir.is_absolute():
                # プロジェクトルートからの相対パスとして解釈
                resolved_config["expected_output_dir"] = str(self.project_root / expected_output_dir)
        
        return resolved_config
    
    def get_pair_type(self, pair_name: str) -> str:
        """
        ペアがファイルベースかエンドポイントベースかを判定
        
        Args:
            pair_name: アラインメントペア名
            
        Returns:
            "file", "endpoint", "hybrid" のいずれか
        """
        config = self.load_alignment_config(pair_name)
        
        has_datasets = bool(config.get("datasets"))
        has_endpoints = bool(config.get("endpoints"))
        
        if has_datasets and has_endpoints:
            return "hybrid"
        elif has_endpoints:
            return "endpoint"
        else:
            return "file"
    
    def list_all_pairs(self) -> List[str]:
        """
        利用可能な全アラインメントペアをリストアップ
        
        Returns:
            ペア名のリスト
        """
        if not self.alignment_base_dir.exists():
            return []
        
        pairs = []
        for item in self.alignment_base_dir.iterdir():
            if item.is_dir():
                alignment_json = item / "alignment.json"
                if alignment_json.exists():
                    pairs.append(item.name)
        
        return sorted(pairs)
