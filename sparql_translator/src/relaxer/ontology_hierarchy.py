"""
オントロジー階層構造パーサー

.schema.owl ファイルから rdfs:subClassOf と rdfs:subPropertyOf を抽出し、
階層的緩和のための親クラス/親プロパティを取得する。
"""

import os
import re
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
import xml.etree.ElementTree as ET
import logging

logger = logging.getLogger(__name__)


@dataclass
class OntologyHierarchy:
    """オントロジーの階層情報"""
    namespace: str
    # クラス階層: class_uri -> [parent_class_uri, ...]
    class_hierarchy: Dict[str, List[str]] = field(default_factory=dict)
    # プロパティ階層: property_uri -> [parent_property_uri, ...]
    property_hierarchy: Dict[str, List[str]] = field(default_factory=dict)


class OntologyHierarchyParser:
    """
    OWLスキーマファイルをパースして階層情報を抽出
    """
    
    # RDF/OWL名前空間
    NAMESPACES = {
        'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
        'rdfs': 'http://www.w3.org/2000/01/rdf-schema#',
        'owl': 'http://www.w3.org/2002/07/owl#',
        'xsd': 'http://www.w3.org/2001/XMLSchema#',
    }
    
    def __init__(self, schema_dir: str = None):
        """
        Args:
            schema_dir: .schema.owl ファイルが格納されているディレクトリ
        """
        if schema_dir is None:
            # デフォルトパス
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            schema_dir = os.path.join(base_dir, 'data', 'datasets')
        
        self.schema_dir = schema_dir
        self._cache: Dict[str, OntologyHierarchy] = {}
    
    def get_hierarchy(self, ontology_name: str) -> Optional[OntologyHierarchy]:
        """
        オントロジーの階層情報を取得
        
        Args:
            ontology_name: オントロジー名（例: 'conference', 'cmt'）
            
        Returns:
            OntologyHierarchy または None（スキーマが見つからない場合）
        """
        if ontology_name in self._cache:
            return self._cache[ontology_name]
        
        schema_file = os.path.join(self.schema_dir, f"{ontology_name}.schema.owl")
        if not os.path.exists(schema_file):
            logger.warning(f"Schema file not found: {schema_file}")
            return None
        
        hierarchy = self._parse_owl_file(schema_file, ontology_name)
        self._cache[ontology_name] = hierarchy
        return hierarchy
    
    def _parse_owl_file(self, filepath: str, ontology_name: str) -> OntologyHierarchy:
        """
        OWLファイルをパースして階層情報を抽出
        
        Args:
            filepath: OWLファイルパス
            ontology_name: オントロジー名
            
        Returns:
            OntologyHierarchy
        """
        class_hierarchy: Dict[str, List[str]] = {}
        property_hierarchy: Dict[str, List[str]] = {}
        
        # 名前空間を推定
        namespace = f"http://{ontology_name}#"
        
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            
            # xml:base から名前空間を取得
            base = root.attrib.get('{http://www.w3.org/XML/1998/namespace}base', '')
            if base:
                namespace = base if base.endswith('#') else base + '#'
            
            # すべての要素を走査
            for elem in root.iter():
                tag = self._strip_namespace(elem.tag)
                
                # owl:Class の処理
                if tag == 'Class':
                    class_uri = self._get_uri(elem, namespace)
                    if class_uri:
                        parents = self._extract_subclass_of(elem, namespace)
                        if parents:
                            class_hierarchy[class_uri] = parents
                
                # owl:ObjectProperty / owl:DatatypeProperty の処理
                elif tag in ('ObjectProperty', 'DatatypeProperty'):
                    prop_uri = self._get_uri(elem, namespace)
                    if prop_uri:
                        parents = self._extract_subproperty_of(elem, namespace)
                        if parents:
                            property_hierarchy[prop_uri] = parents
            
            logger.info(f"Parsed {ontology_name}: {len(class_hierarchy)} classes, {len(property_hierarchy)} properties with hierarchy")
            
        except ET.ParseError as e:
            logger.error(f"XML parse error in {filepath}: {e}")
        except Exception as e:
            logger.error(f"Error parsing {filepath}: {e}")
        
        return OntologyHierarchy(
            namespace=namespace,
            class_hierarchy=class_hierarchy,
            property_hierarchy=property_hierarchy
        )
    
    def _strip_namespace(self, tag: str) -> str:
        """タグから名前空間プレフィックスを除去"""
        if tag.startswith('{'):
            return tag.split('}')[1]
        return tag
    
    def _get_uri(self, elem: ET.Element, base_namespace: str) -> Optional[str]:
        """要素からURIを取得"""
        # rdf:ID
        rdf_id = elem.attrib.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}ID')
        if rdf_id:
            return base_namespace + rdf_id
        
        # rdf:about
        rdf_about = elem.attrib.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about')
        if rdf_about:
            if rdf_about.startswith('#'):
                return base_namespace + rdf_about[1:]
            return rdf_about
        
        return None
    
    def _extract_subclass_of(self, class_elem: ET.Element, base_namespace: str) -> List[str]:
        """rdfs:subClassOf を抽出"""
        parents = []
        
        for sub in class_elem:
            tag = self._strip_namespace(sub.tag)
            if tag == 'subClassOf':
                parent_uri = self._get_resource_uri(sub, base_namespace)
                if parent_uri and not parent_uri.startswith('http://www.w3.org/2002/07/owl#'):
                    # owl:Thing などのOWL組み込みクラスは除外しない（緩和候補として有効）
                    parents.append(parent_uri)
        
        return parents
    
    def _extract_subproperty_of(self, prop_elem: ET.Element, base_namespace: str) -> List[str]:
        """rdfs:subPropertyOf を抽出"""
        parents = []
        
        for sub in prop_elem:
            tag = self._strip_namespace(sub.tag)
            if tag == 'subPropertyOf':
                parent_uri = self._get_resource_uri(sub, base_namespace)
                if parent_uri:
                    parents.append(parent_uri)
        
        return parents
    
    def _get_resource_uri(self, elem: ET.Element, base_namespace: str) -> Optional[str]:
        """rdf:resource 属性からURIを取得"""
        resource = elem.attrib.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource')
        if resource:
            if resource.startswith('#'):
                return base_namespace + resource[1:]
            return resource
        
        # ネストした要素（rdf:Description や owl:Class）を探す
        for child in elem:
            uri = self._get_uri(child, base_namespace)
            if uri:
                return uri
        
        return None
    
    def get_parent_classes(self, ontology_name: str, class_uri: str) -> List[str]:
        """
        指定クラスの親クラスリストを取得（階層順）
        
        Args:
            ontology_name: オントロジー名
            class_uri: クラスURI
            
        Returns:
            親クラスのリスト（直接の親から順に）
        """
        hierarchy = self.get_hierarchy(ontology_name)
        if not hierarchy:
            return []
        
        parents = []
        visited = set()
        current = class_uri
        
        while current and current not in visited:
            visited.add(current)
            direct_parents = hierarchy.class_hierarchy.get(current, [])
            if direct_parents:
                # 最初の親のみを辿る（多重継承の場合は最初のパスのみ）
                parent = direct_parents[0]
                parents.append(parent)
                current = parent
            else:
                break
        
        return parents
    
    def get_parent_properties(self, ontology_name: str, property_uri: str) -> List[str]:
        """
        指定プロパティの親プロパティリストを取得（階層順）
        
        Args:
            ontology_name: オントロジー名
            property_uri: プロパティURI
            
        Returns:
            親プロパティのリスト（直接の親から順に）
        """
        hierarchy = self.get_hierarchy(ontology_name)
        if not hierarchy:
            return []
        
        parents = []
        visited = set()
        current = property_uri
        
        while current and current not in visited:
            visited.add(current)
            direct_parents = hierarchy.property_hierarchy.get(current, [])
            if direct_parents:
                parent = direct_parents[0]
                parents.append(parent)
                current = parent
            else:
                break
        
        return parents
    
    def get_all_classes(self, ontology_name: str) -> List[str]:
        """
        指定オントロジーの全クラスURIを取得
        
        Args:
            ontology_name: オントロジー名
            
        Returns:
            クラスURIのリスト
        """
        hierarchy = self.get_hierarchy(ontology_name)
        if not hierarchy:
            return []
        
        # 階層に含まれるクラスを収集
        all_classes = set()
        for class_uri, parents in hierarchy.class_hierarchy.items():
            all_classes.add(class_uri)
            all_classes.update(parents)
        
        return list(all_classes)
    
    def get_all_properties(self, ontology_name: str) -> List[str]:
        """
        指定オントロジーの全プロパティURIを取得
        
        Args:
            ontology_name: オントロジー名
            
        Returns:
            プロパティURIのリスト
        """
        hierarchy = self.get_hierarchy(ontology_name)
        if not hierarchy:
            return []
        
        # 階層に含まれるプロパティを収集
        all_props = set()
        for prop_uri, parents in hierarchy.property_hierarchy.items():
            all_props.add(prop_uri)
            all_props.update(parents)
        
        return list(all_props)


# グローバルインスタンス
_parser: Optional[OntologyHierarchyParser] = None


def get_parser() -> OntologyHierarchyParser:
    """シングルトンパーサーを取得"""
    global _parser
    if _parser is None:
        _parser = OntologyHierarchyParser()
    return _parser


def get_parent_classes(ontology_name: str, class_uri: str) -> List[str]:
    """便利関数: 親クラスリストを取得"""
    return get_parser().get_parent_classes(ontology_name, class_uri)


def get_parent_properties(ontology_name: str, property_uri: str) -> List[str]:
    """便利関数: 親プロパティリストを取得"""
    return get_parser().get_parent_properties(ontology_name, property_uri)


if __name__ == '__main__':
    # テスト
    logging.basicConfig(level=logging.INFO)
    
    parser = OntologyHierarchyParser()
    
    for ont_name in ['conference', 'cmt', 'edas', 'ekaw', 'confOf']:
        print(f"\n=== {ont_name} ===")
        hierarchy = parser.get_hierarchy(ont_name)
        if hierarchy:
            print(f"Namespace: {hierarchy.namespace}")
            print(f"Classes with parents: {len(hierarchy.class_hierarchy)}")
            print(f"Properties with parents: {len(hierarchy.property_hierarchy)}")
            
            # サンプル表示
            if hierarchy.class_hierarchy:
                sample_class = list(hierarchy.class_hierarchy.keys())[0]
                print(f"  Sample class: {sample_class}")
                print(f"    Parents: {hierarchy.class_hierarchy[sample_class]}")
            
            if hierarchy.property_hierarchy:
                sample_prop = list(hierarchy.property_hierarchy.keys())[0]
                print(f"  Sample property: {sample_prop}")
                print(f"    Parents: {hierarchy.property_hierarchy[sample_prop]}")
