"""
EDOAL完全パーサー - Ruthless Engineering Edition

CSV失敗クエリ100%対応を目指した完全再実装。
再帰パース、全制約対応、Python型リーク撲滅を実現。
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Any, Optional

# ========================================
# データクラス定義
# ========================================

@dataclass
class EDOALEntity:
    """EDOAL内の任意のエンティティの基底クラス"""
    pass


@dataclass
class IdentifiedEntity(EDOALEntity):
    """URIで識別されるエンティティ"""
    uri: str


@dataclass
class Class(IdentifiedEntity):
    """OWLクラス"""
    pass


@dataclass
class Property(IdentifiedEntity):
    """プロパティ（属性）"""
    pass


@dataclass
class Relation(IdentifiedEntity):
    """関係（リレーション）"""
    pass


@dataclass
class Instance(IdentifiedEntity):
    """個体（インスタンス）"""
    pass


@dataclass
class LogicalConstructor(EDOALEntity):
    """論理構成子 (and/or/not)"""
    operator: str  # 'and', 'or', 'not'
    operands: List[EDOALEntity] = field(default_factory=list)


@dataclass
class PathConstructor(EDOALEntity):
    """パス構成子 (compose/inverse/transitive)"""
    operator: str  # 'compose', 'inverse', 'transitive'
    operands: List[EDOALEntity] = field(default_factory=list)


@dataclass
class Restriction(EDOALEntity):
    """制約の基底クラス"""
    on_attribute: EDOALEntity


@dataclass
class AttributeValueRestriction(Restriction):
    """属性値制約"""
    comparator: str
    value: Any


@dataclass
class AttributeDomainRestriction(Restriction):
    """属性ドメイン制約"""
    class_expression: EDOALEntity


@dataclass
class AttributeOccurenceRestriction(Restriction):
    """属性出現回数制約"""
    comparator: str
    value: Any


@dataclass
class RelationDomainRestriction(EDOALEntity):
    """リレーションドメイン制約"""
    on_relation: EDOALEntity = None
    class_expression: EDOALEntity = None


@dataclass
class RelationCoDomainRestriction(EDOALEntity):
    """リレーション値域制約"""
    on_relation: EDOALEntity = None
    class_expression: EDOALEntity = None


@dataclass
class PropertyDomainRestriction(EDOALEntity):
    """プロパティドメイン制約"""
    class_expression: EDOALEntity


@dataclass
@dataclass
class Cell:
    """アラインメントセル"""
    entity1: EDOALEntity
    entity2: EDOALEntity
    relation: str
    measure: float
    id: str = ""  # セルのID(rdf:about値)


@dataclass
class Alignment:
    """アラインメント全体"""
    onto1: str = ""
    onto2: str = ""
    cells: List[Cell] = field(default_factory=list)


# ========================================
# パーサー本体
# ========================================

class EdoalParser:
    """EDOAL完全パーサー - 再帰処理・全制約対応"""
    
    def __init__(self, file_path: str = None, xml_string: str = None, verbose: bool = False):
        self.file_path = file_path
        self.verbose = verbose
        
        # XML解析
        if xml_string:
            self.root = ET.fromstring(xml_string)
        elif file_path:
            self.tree = ET.parse(file_path)
            self.root = self.tree.getroot()
        else:
            raise ValueError("file_path or xml_string must be provided")
        
        # 名前空間マッピング
        self.namespaces = self._extract_namespaces()
    
    @classmethod
    def parse_from_string(cls, xml_string: str, verbose: bool = False):
        """文字列からパース"""
        parser = cls(xml_string=xml_string, verbose=verbose)
        return parser.parse()
    
    def _extract_namespaces(self) -> dict:
        """XML名前空間を抽出"""
        ns = {
            'align': 'http://knowledgeweb.semanticweb.org/heterogeneity/alignment',
            'edoal': 'http://ns.inria.org/edoal/1.0/#',
            'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
            'xsd': 'http://www.w3.org/2001/XMLSchema#',
            'rdfs': 'http://www.w3.org/2000/01/rdf-schema#'
        }
        
        # XML root から動的に抽出（上書き）
        for key, value in self.root.attrib.items():
            if key.startswith('{http://www.w3.org/2000/xmlns/}'):
                prefix = key.split('}')[1]
                ns[prefix] = value
        
        return ns
    
    def parse(self) -> Alignment:
        """メインパース処理"""
        alignment = Alignment()
        
        # Cell要素を走査 (align:プレフィックスなしでも検索)
        # アライメントファイルではCellはデフォルトネームスペースに定義されているため
        for cell_elem in self.root.findall('.//{http://knowledgeweb.semanticweb.org/heterogeneity/alignment#}Cell'):
            cell = self._parse_cell(cell_elem)
            if cell:
                alignment.cells.append(cell)
        
        if self.verbose:
            print(f"[EdoalParser] Parsed {len(alignment.cells)} cells")
        
        return alignment
    
    def _parse_cell(self, cell_elem: ET.Element) -> Optional[Cell]:
        """Cellをパース"""
        # フルネームスペースURIで検索
        ns = 'http://knowledgeweb.semanticweb.org/heterogeneity/alignment#'
        entity1_elem = cell_elem.find(f'{{{ns}}}entity1')
        entity2_elem = cell_elem.find(f'{{{ns}}}entity2')
        relation_elem = cell_elem.find(f'{{{ns}}}relation')
        measure_elem = cell_elem.find(f'{{{ns}}}measure')
        
        if entity1_elem is None or entity2_elem is None:
            return None
        
        # entity1とentity2の最初の子要素を再帰パース
        entity1 = None
        entity2 = None
        
        for child in entity1_elem:
            entity1 = self._parse_entity(child)
            if entity1:
                break
        
        for child in entity2_elem:
            entity2 = self._parse_entity(child)
            if entity2:
                break
        
        if not entity1 or not entity2:
            return None
        
        relation = relation_elem.text.strip() if relation_elem is not None else "Equivalence"
        measure = float(measure_elem.text.strip()) if measure_elem is not None else 1.0
        
        cell_id = cell_elem.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about', '')
        
        return Cell(entity1, entity2, relation, measure, cell_id)
        return Cell(entity1, entity2, relation, measure)
    
    def _parse_entity(self, element: ET.Element) -> Optional[EDOALEntity]:
        """エンティティを再帰的にパース（完全実装）"""
        if element is None:
            return None
        
        # タグのローカル名を取得
        tag = element.tag.split('}')[-1] if '}' in element.tag else element.tag
        
        # rdf:about属性の確認
        rdf_about = element.get(f'{{{self.namespaces["rdf"]}}}about')
        if not rdf_about:
            rdf_about = element.get('rdf:about')
        
        # === 1. 単純なURI識別エンティティ ===
        if rdf_about:
            if tag == 'Class':
                return Class(uri=rdf_about)
            if tag == 'Property':
                return Property(uri=rdf_about)
            if tag == 'Relation':
                return Relation(uri=rdf_about)
            if tag == 'Instance':
                return Instance(uri=rdf_about)
        
        # === 2. 複合エンティティ（子要素を持つ） ===
        if tag in ['Class', 'Property', 'Relation'] and len(element) > 0:
            # 最初の子要素を再帰パース
            for child in element:
                parsed = self._parse_entity(child)
                if parsed:
                    return parsed
        
        # === 3. 論理構成子 (and, or, not) ===
        if tag in ['and', 'or', 'not']:
            operands = []
            for child in element:
                parsed = self._parse_entity(child)
                if parsed:
                    operands.append(parsed)
            
            if self.verbose:
                print(f"[EdoalParser] LogicalConstructor '{tag}' with {len(operands)} operands")
            
            return LogicalConstructor(operator=tag, operands=operands)
        
        # === 4. パス構成子 (compose, inverse, transitive) ===
        if tag in ['compose', 'inverse', 'transitive']:
            operands = []
            for child in element:
                parsed = self._parse_entity(child)
                if parsed:
                    operands.append(parsed)
            
            if self.verbose:
                print(f"[EdoalParser] PathConstructor '{tag}' with {len(operands)} operands")
            
            return PathConstructor(operator=tag, operands=operands)
        
        # === 5. AttributeDomainRestriction ===
        if tag == 'AttributeDomainRestriction':
            on_attr_elem = element.find('edoal:onAttribute', self.namespaces)
            class_elem = element.find('edoal:class', self.namespaces)
            
            on_attribute = None
            class_expression = None
            
            if on_attr_elem is not None and len(on_attr_elem) > 0:
                on_attribute = self._parse_entity(on_attr_elem[0])
            
            if class_elem is not None and len(class_elem) > 0:
                class_expression = self._parse_entity(class_elem[0])
            
            return AttributeDomainRestriction(
                on_attribute=on_attribute,
                class_expression=class_expression
            )
        
        # === 6. AttributeValueRestriction ===
        if tag == 'AttributeValueRestriction':
            on_attr_elem = element.find('edoal:onAttribute', self.namespaces)
            comparator_elem = element.find('edoal:comparator', self.namespaces)
            value_elem = element.find('edoal:value', self.namespaces)
            
            on_attribute = None
            if on_attr_elem is not None and len(on_attr_elem) > 0:
                on_attribute = self._parse_entity(on_attr_elem[0])
            
            comparator = None
            if comparator_elem is not None:
                comparator = comparator_elem.get(f'{{{self.namespaces["rdf"]}}}resource')
                if not comparator:
                    comparator = comparator_elem.get('rdf:resource')
            
            value = None
            if value_elem is not None and len(value_elem) > 0:
                value_child = value_elem[0]
                value_tag = value_child.tag.split('}')[-1] if '}' in value_child.tag else value_child.tag
                
                if value_tag == 'Literal':
                    # Literalの解析
                    string_val = value_child.get(f'{{{self.namespaces["edoal"]}}}string')
                    if not string_val:
                        string_val = value_child.get('edoal:string')
                    
                    type_val = value_child.get(f'{{{self.namespaces["edoal"]}}}type')
                    if not type_val:
                        type_val = value_child.get('edoal:type')
                    
                    value = {'string': string_val or '', 'type': type_val or ''}
                else:
                    # その他のエンティティ
                    value = self._parse_entity(value_child)
            
            return AttributeValueRestriction(
                on_attribute=on_attribute,
                comparator=comparator,
                value=value
            )
        
        # === 7. AttributeOccurenceRestriction ===
        if tag == 'AttributeOccurenceRestriction':
            on_attr_elem = element.find('edoal:onAttribute', self.namespaces)
            comparator_elem = element.find('edoal:comparator', self.namespaces)
            value_elem = element.find('edoal:value', self.namespaces)
            
            on_attribute = None
            if on_attr_elem is not None and len(on_attr_elem) > 0:
                on_attribute = self._parse_entity(on_attr_elem[0])
            
            comparator = None
            if comparator_elem is not None:
                comparator = comparator_elem.get(f'{{{self.namespaces["rdf"]}}}resource')
                if not comparator:
                    comparator = comparator_elem.get('rdf:resource')
            
            value = None
            if value_elem is not None:
                value_text = value_elem.text
                if value_text:
                    try:
                        value = int(value_text)
                    except ValueError:
                        value = value_text
            
            return AttributeOccurenceRestriction(
                on_attribute=on_attribute,
                comparator=comparator,
                value=value
            )
        
        # === 8. RelationDomainRestriction ===
        if tag == 'RelationDomainRestriction':
            class_elem = element.find('edoal:class', self.namespaces)
            class_expression = None
            
            if class_elem is not None and len(class_elem) > 0:
                class_expression = self._parse_entity(class_elem[0])
            
            return RelationDomainRestriction(class_expression=class_expression)
        
        # === 9. RelationCoDomainRestriction ===
        if tag == 'RelationCoDomainRestriction':
            class_elem = element.find('edoal:class', self.namespaces)
            class_expression = None
            
            if class_elem is not None and len(class_elem) > 0:
                class_expression = self._parse_entity(class_elem[0])
            
            return RelationCoDomainRestriction(class_expression=class_expression)
        
        # === 10. PropertyDomainRestriction ===
        if tag == 'PropertyDomainRestriction':
            class_elem = element.find('edoal:class', self.namespaces)
            class_expression = None
            
            if class_elem is not None and len(class_elem) > 0:
                class_expression = self._parse_entity(class_elem[0])
            
            return PropertyDomainRestriction(class_expression=class_expression)
        
        # === フォールバック ===
        if self.verbose:
            print(f"[EdoalParser WARNING] Unknown tag: {tag}")
        
        return None
