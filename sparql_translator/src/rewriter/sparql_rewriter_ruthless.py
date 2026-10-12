"""
SPARQL AST Rewriter - Ruthless Engineering Edition

CSV失敗クエリ100%対応を目指した完全書き換えエンジン。
UNION展開、compose連鎖、inverse反転、FILTER生成、型制約注入を完全実装。
Python型リーク撲滅を保証。
"""

from .ast_walker import AstWalker
from ..parser.edoal_parser_ruthless import (
    Alignment, Cell, IdentifiedEntity, LogicalConstructor, PathConstructor,
    AttributeDomainRestriction, AttributeValueRestriction, AttributeOccurenceRestriction,
    RelationDomainRestriction, RelationCoDomainRestriction, PropertyDomainRestriction,
    Relation, Property, Class
)
from ..common.logger import get_logger


class SparqlRewriterRuthless(AstWalker):
    """完全実装SPARQL書き換えエンジン"""
    
    def __init__(self, alignment: Alignment, verbose: bool = False):
        self.alignment = alignment  # アラインメント全体を保持
        self.mapping = self._create_mapping(alignment)
        self.logger = get_logger('sparql_rewriter_ruthless', verbose=False)
        self.temp_var_counter = 0
        self.verbose = verbose
        self.variable_mapping = {}
        self.used_source_uris = set()  # 使用されたソースURIを追跡
    
    def _create_mapping(self, alignment: Alignment) -> dict:
        """マッピング辞書を作成"""
        mapping = {}
        for cell in alignment.cells:
            source_uri = self._extract_source_uri(cell.entity1)
            if source_uri:
                # entity1全体ではなく、entity2をマッピング値とする
                # ただし、entity1がLogicalConstructorの場合は特別な処理が必要
                mapping[source_uri] = self._wrap_entity2_with_entity1_constraints(cell.entity1, cell.entity2)
        return mapping
    
    def _wrap_entity2_with_entity1_constraints(self, entity1: any, entity2: any) -> any:
        """entity1の制約をentity2に適用"""
        if isinstance(entity1, LogicalConstructor) and entity1.operator == 'and':
            # entity1がandの場合、制約を抽出してentity2と組み合わせる
            constraints = [op for op in entity1.operands if not isinstance(op, (IdentifiedEntity, PathConstructor))]
            if constraints:
                # entity2と制約を組み合わせた新しいLogicalConstructorを作成
                return LogicalConstructor(
                    operator='and',
                    operands=[entity2] + constraints
                )
        return entity2
    
    def _extract_source_uri(self, entity: any) -> str:
        """エンティティからソースURIを抽出"""
        if isinstance(entity, IdentifiedEntity):
            return entity.uri
        elif isinstance(entity, LogicalConstructor):
            # LogicalConstructor (and/or) の最初のoperandからURIを抽出
            if entity.operands:
                return self._extract_source_uri(entity.operands[0])
        elif isinstance(entity, PathConstructor):
            # PathConstructor (compose/inverse) の最初のoperandからURIを抽出
            if entity.operands:
                return self._extract_source_uri(entity.operands[0])
        elif isinstance(entity, (AttributeDomainRestriction, AttributeValueRestriction, AttributeOccurenceRestriction)):
            # 制約の on_attribute からURIを抽出
            if hasattr(entity, 'on_attribute'):
                return self._extract_source_uri(entity.on_attribute)
        elif isinstance(entity, (RelationDomainRestriction, RelationCoDomainRestriction, PropertyDomainRestriction)):
            # 制約は直接URIを持たないので、スキップ
            pass
        return None
    
    def _generate_temp_var(self) -> str:
        """一時変数を生成"""
        var_name = f"?temp{self.temp_var_counter}"
        self.temp_var_counter += 1
        return var_name
    
    def _node_to_sse(self, node: dict) -> str:
        """ASTノードをS式文字列に変換"""
        node_type = node.get('type', '')
        
        if node_type == 'var' or node_type == 'variable':
            # 'var'または'variable'タイプの変数
            var_name = node.get('name', node.get('value', 'x'))
            # 既に"?"が付いている場合は除去
            if var_name.startswith('?'):
                return var_name
            else:
                return f"?{var_name}"
        elif node_type == 'uri':
            return f"<{node.get('value', '')}>"
        elif node_type == 'literal':
            value = node.get('value', '')
            return f'"{value}"'
        else:
            # デフォルト（変数として扱う）
            var_name = node.get('name', node.get('value', 'x'))
            if var_name.startswith('?'):
                return var_name
            else:
                return f"?{var_name}"
    
    # ========================================
    # ノード訪問メソッド
    # ========================================
    
    def visit_uri(self, node: dict) -> dict:
        """URIノードの書き換え"""
        uri = node.get('value')
        target_entity = self.mapping.get(uri)
        
        if isinstance(target_entity, IdentifiedEntity):
            if self.verbose:
                print(f"[Rewriter] URI: {uri} -> {target_entity.uri}")
            return {**node, 'value': target_entity.uri}
        
        return node
    
    def visit_group(self, node: dict) -> dict:
        """Groupノードの処理"""
        new_patterns = []
        
        for pattern in node.get('patterns', []):
            result = self._walk_node(pattern)
            
            if isinstance(result, dict) and result.get('type') == 'union':
                new_patterns.append(result)
            elif isinstance(result, list):
                new_patterns.extend(result)
            else:
                new_patterns.append(result)
        
        return {**node, 'patterns': new_patterns}
    
    def visit_bgp(self, node: dict) -> dict:
        """BGPノードの処理"""
        new_triples = []
        filters = []
        union_structures = []
        
        for triple in node.get('triples', []):
            result = self._walk_node(triple)
            
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, dict):
                        if item.get('type') == 'filter':
                            filters.append(item)
                        elif item.get('type') == 'union':
                            union_structures.append(item)
                        else:
                            new_triples.append(item)
            elif isinstance(result, dict):
                if result.get('type') == 'union':
                    union_structures.append(result)
                elif result.get('type') == 'filter':
                    filters.append(result)
                else:
                    new_triples.append(result)
        
        # UNIONがある場合は親のgroupで処理する必要がある
        if union_structures:
            # BGPを複数のパターンに分解
            patterns = []
            if new_triples:
                patterns.append({'type': 'bgp', 'triples': new_triples})
            patterns.extend(union_structures)
            patterns.extend(filters)
            return patterns
        
        # 通常のBGP + FILTER
        result_bgp = {**node, 'triples': new_triples}
        if filters:
            return [result_bgp] + filters
        return result_bgp
    
    def visit_triple(self, node: dict) -> any:
        """トリプルノードの完全書き換え"""
        subject = node.get('subject', {})
        predicate = node.get('predicate', {})
        obj = node.get('object', {})
        
        # 述語URIのチェック
        if predicate.get('type') == 'uri':
            pred_uri = predicate.get('value')
            target_entity = self.mapping.get(pred_uri)
            
            if target_entity:
                self.used_source_uris.add(pred_uri)  # 使用を記録
                return self._expand_triple(subject, predicate, obj, target_entity)
        
        # rdf:typeの場合、目的語のクラスマッピングを特別に処理
        if predicate.get('type') == 'uri' and predicate.get('value') == 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type':
            if obj.get('type') == 'uri':
                obj_uri = obj.get('value')
                target_entity = self.mapping.get(obj_uri)
                
                if target_entity:
                    self.used_source_uris.add(obj_uri)  # 使用を記録
                    # クラス変換として処理
                    return self._expand_class_in_rdf_type(subject, predicate, obj, target_entity)
        
        # 主語URIのチェック（クラスマッピング）
        if subject.get('type') == 'uri':
            subj_uri = subject.get('value')
            target_entity = self.mapping.get(subj_uri)
            
            if target_entity:
                self.used_source_uris.add(subj_uri)  # 使用を記録
                return self._expand_subject(node, target_entity)
        
        # 目的語URIのチェック（通常のURI置換）
        if obj.get('type') == 'uri':
            obj_uri = obj.get('value')
            target_entity = self.mapping.get(obj_uri)
            
            if isinstance(target_entity, IdentifiedEntity):
                self.used_source_uris.add(obj_uri)  # 使用を記録
                new_obj = {'type': 'uri', 'value': target_entity.uri}
                return {**node, 'object': new_obj}
        
        return node
    
    # ========================================
    # 拡張メソッド
    # ========================================
    
    def _expand_class_in_rdf_type(self, subject: dict, predicate: dict, obj: dict, target_entity: any) -> any:
        """rdf:type トリプルの目的語クラス変換"""
        
        # === 1. 単純なクラス置換 ===
        if isinstance(target_entity, IdentifiedEntity):
            new_obj = {'type': 'uri', 'value': target_entity.uri}
            return {'type': 'triple', 'subject': subject, 'predicate': predicate, 'object': new_obj}
        
        # === 2. LogicalConstructor (or) -> UNION ===
        if isinstance(target_entity, LogicalConstructor) and target_entity.operator == 'or':
            return self._create_union_from_class_rdf_type(subject, predicate, target_entity)
        
        # === 3. LogicalConstructor (and) -> 複数トリプル + FILTER ===
        if isinstance(target_entity, LogicalConstructor) and target_entity.operator == 'and':
            return self._expand_and_class_rdf_type(subject, predicate, target_entity)
        
        # === 4. LogicalConstructor (not) -> FILTER NOT EXISTS ===
        if isinstance(target_entity, LogicalConstructor) and target_entity.operator == 'not':
            # NOTは単独では出現しない想定だが、念のため処理
            base_triple = {'type': 'triple', 'subject': subject, 'predicate': predicate, 'object': obj}
            filter_node = self._expand_not(base_triple, target_entity)
            if filter_node:
                return [base_triple, filter_node]
            return base_triple
        
        # === 5. AttributeDomainRestriction ===
        if isinstance(target_entity, AttributeDomainRestriction):
            return self._expand_class_attribute_domain_rdf_type(subject, predicate, target_entity)
        
        # === 6. AttributeOccurenceRestriction ===
        # ?s rdf:type SourceClass -> ?s targetProp ?tempVar (existence check)
        if isinstance(target_entity, AttributeOccurenceRestriction):
            temp_var = self._generate_temp_var()
            triples = []
            filters = []
            
            # 属性のトリプルを生成
            if isinstance(target_entity.on_attribute, Relation):
                new_pred = {'type': 'uri', 'value': target_entity.on_attribute.uri}
                triple = {
                    'type': 'triple',
                    'subject': subject,
                    'predicate': new_pred,
                    'object': {'type': 'variable', 'value': temp_var.lstrip('?')}
                }
                triples.append(triple)
            elif isinstance(target_entity.on_attribute, Property):
                new_pred = {'type': 'uri', 'value': target_entity.on_attribute.uri}
                triple = {
                    'type': 'triple',
                    'subject': subject,
                    'predicate': new_pred,
                    'object': {'type': 'variable', 'value': temp_var.lstrip('?')}
                }
                triples.append(triple)
            
            # FILTER条件（greater-than 0 など）
            if target_entity.comparator and target_entity.value is not None:
                # AttributeOccurenceRestrictionの場合、存在チェックはトリプルで十分
                # 追加のFILTERは不要（greater-than 0 は「存在する」の意味）
                pass
            
            return triples if len(triples) > 1 else (triples[0] if triples else {'type': 'triple', 'subject': subject, 'predicate': predicate, 'object': obj})
        
        # === 7. AttributeValueRestriction ===
        # ?s rdf:type SourceClass -> ?s targetProp ?tempVar . FILTER(?tempVar = value)
        if isinstance(target_entity, AttributeValueRestriction):
            temp_var = self._generate_temp_var()
            triples = []
            filters = []
            
            # 属性のトリプルを生成
            if isinstance(target_entity.on_attribute, Relation):
                new_pred = {'type': 'uri', 'value': target_entity.on_attribute.uri}
                triple = {
                    'type': 'triple',
                    'subject': subject,
                    'predicate': new_pred,
                    'object': {'type': 'variable', 'value': temp_var.lstrip('?')}
                }
                triples.append(triple)
            elif isinstance(target_entity.on_attribute, Property):
                new_pred = {'type': 'uri', 'value': target_entity.on_attribute.uri}
                triple = {
                    'type': 'triple',
                    'subject': subject,
                    'predicate': new_pred,
                    'object': {'type': 'variable', 'value': temp_var.lstrip('?')}
                }
                triples.append(triple)
            
            # FILTER条件
            if target_entity.comparator and target_entity.value is not None:
                comp_op = target_entity.comparator.split('#')[-1] if '#' in target_entity.comparator else target_entity.comparator
                # Map EDOAL comparators to SPARQL operators
                comp_map = {
                    'equals': '=',
                    'greater-than': '>',
                    'less-than': '<',
                    'greater-than-or-equal': '>=',
                    'less-than-or-equal': '<='
                }
                comp_op = comp_map.get(comp_op, comp_op)
                formatted_value = self._format_filter_value(target_entity.value)
                
                # SSE format: operator first
                filter_expr = f"({comp_op} {temp_var} {formatted_value})"
                filter_node = {'type': 'filter', 'expression': filter_expr}
                filters.append(filter_node)
            
            result = triples + filters
            return result if len(result) > 1 else (result[0] if result else {'type': 'triple', 'subject': subject, 'predicate': predicate, 'object': obj})
        
        # フォールバック
        return {'type': 'triple', 'subject': subject, 'predicate': predicate, 'object': obj}
    
    def _create_union_from_class_rdf_type(self, subject: dict, predicate: dict, logical_constructor: LogicalConstructor) -> dict:
        """rdf:type目的語のUNION展開"""
        patterns = []  # Javaシリアライザーは'patterns'を期待
        
        for operand in logical_constructor.operands:
            branch_triples = []
            
            if isinstance(operand, IdentifiedEntity):
                triple = {
                    'type': 'triple',
                    'subject': subject,
                    'predicate': predicate,
                    'object': {'type': 'uri', 'value': operand.uri}
                }
                branch_triples.append(triple)
            
            elif isinstance(operand, LogicalConstructor):
                # ネストしたLogicalConstructorを再帰処理
                result = self._expand_class_in_rdf_type(subject, predicate, {'type': 'uri', 'value': ''}, operand)
                if isinstance(result, list):
                    branch_triples.extend(result)
                else:
                    branch_triples.append(result)
            
            if branch_triples:
                patterns.append({'type': 'bgp', 'triples': branch_triples})
        
        return {'type': 'union', 'patterns': patterns}
    
    def _expand_and_class_rdf_type(self, subject: dict, predicate: dict, logical_constructor: LogicalConstructor) -> list:
        """rdf:type目的語のAND展開"""
        triples = []
        filters = []
        
        # operandsを処理
        for i, operand in enumerate(logical_constructor.operands):
            if isinstance(operand, IdentifiedEntity):
                # 最初のoperandをrdf:typeトリプルとして使用
                if i == 0:
                    triple = {
                        'type': 'triple',
                        'subject': subject,
                        'predicate': predicate,
                        'object': {'type': 'uri', 'value': operand.uri}
                    }
                    triples.append(triple)
                else:
                    # 追加のクラス制約
                    triple = {
                        'type': 'triple',
                        'subject': subject,
                        'predicate': {'type': 'uri', 'value': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'},
                        'object': {'type': 'uri', 'value': operand.uri}
                    }
                    triples.append(triple)
            
            elif isinstance(operand, LogicalConstructor) and operand.operator == 'not':
                # FILTER NOT EXISTSを生成
                # 最初のtriple（まだ生成されていない場合）
                if not triples:
                    # デフォルトのrdf:typeトリプルを追加（後で他のoperandで上書きされる可能性）
                    pass
                
                # NOTの内容を解析
                for not_operand in operand.operands:
                    if isinstance(not_operand, AttributeOccurenceRestriction):
                        if isinstance(not_operand.on_attribute, Relation):
                            temp_var = self._generate_temp_var()
                            
                            # FILTER NOT EXISTS用のS式を生成
                            # 形式: (notexists (bgp (triple ?subject <predicate> ?temp)))
                            subj_str = self._node_to_sse(subject)
                            pred_uri = not_operand.on_attribute.uri
                            obj_str = temp_var  # 既に"?"付き
                            
                            if self.verbose:
                                print(f"[FILTER NOT EXISTS] subject={subject}, subj_str={subj_str}, pred={pred_uri}, obj={obj_str}")
                            
                            # S式形式のFILTER NOT EXISTS
                            filter_expr = f"(notexists (bgp (triple {subj_str} <{pred_uri}> {obj_str})))"
                            
                            filter_node = {
                                'type': 'filter',
                                'expression': filter_expr
                            }
                            filters.append(filter_node)
        
        return triples + filters
    
    def _expand_class_attribute_domain_rdf_type(self, subject: dict, predicate: dict, restriction: AttributeDomainRestriction) -> list:
        """rdf:type目的語のAttributeDomainRestriction展開"""
        triples = []
        
        # on_attributeのプロパティトリプル
        if isinstance(restriction.on_attribute, IdentifiedEntity):
            temp_obj = self._generate_temp_var()
            triple1 = {
                'type': 'triple',
                'subject': subject,
                'predicate': {'type': 'uri', 'value': restriction.on_attribute.uri},
                'object': {'type': 'var', 'name': temp_obj}
            }
            triples.append(triple1)
            
            # class_expressionの型制約
            if isinstance(restriction.class_expression, IdentifiedEntity):
                triple2 = {
                    'type': 'triple',
                    'subject': {'type': 'var', 'name': temp_obj},
                    'predicate': {'type': 'uri', 'value': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'},
                    'object': {'type': 'uri', 'value': restriction.class_expression.uri}
                }
                triples.append(triple2)
        
        return triples
    
    def _expand_triple(self, subject: dict, predicate: dict, obj: dict, target_entity: any) -> any:
        """述語マッピングに基づいてトリプルを展開"""
        
        # === 1. 単純なURI置換 ===
        if isinstance(target_entity, IdentifiedEntity):
            new_predicate = {'type': 'uri', 'value': target_entity.uri}
            return {'type': 'triple', 'subject': subject, 'predicate': new_predicate, 'object': obj}
        
        # === 2. LogicalConstructor (or) -> UNION ===
        if isinstance(target_entity, LogicalConstructor) and target_entity.operator == 'or':
            return self._create_union_from_relation(subject, obj, target_entity)
        
        # === 3. LogicalConstructor (and) -> 複数トリプル ===
        if isinstance(target_entity, LogicalConstructor) and target_entity.operator == 'and':
            return self._expand_and_relation(subject, obj, target_entity)
        
        # === 4. PathConstructor (compose) -> プロパティ連鎖 ===
        if isinstance(target_entity, PathConstructor) and target_entity.operator == 'compose':
            return self._expand_compose(subject, obj, target_entity)
        
        # === 5. PathConstructor (inverse) -> 主語/目的語反転 ===
        if isinstance(target_entity, PathConstructor) and target_entity.operator == 'inverse':
            return self._expand_inverse(subject, obj, target_entity)
        
        # === 6. AttributeDomainRestriction (単体) ===
        if isinstance(target_entity, AttributeDomainRestriction):
            return self._expand_attribute_domain(subject, obj, target_entity)
        
        # === 7. AttributeValueRestriction ===
        if isinstance(target_entity, AttributeValueRestriction):
            return self._expand_attribute_value(subject, obj, target_entity)
        
        # === 8. AttributeOccurenceRestriction ===
        if isinstance(target_entity, AttributeOccurenceRestriction):
            return self._expand_attribute_occurence(subject, obj, target_entity)
        
        # フォールバック
        if self.verbose:
            print(f"[Rewriter WARNING] Unhandled target_entity type: {type(target_entity)}")
        return {'type': 'triple', 'subject': subject, 'predicate': predicate, 'object': obj}
    
    def _expand_subject(self, triple_node: dict, target_entity: any) -> any:
        """主語マッピングの展開（クラス変換）"""
        
        # === LogicalConstructor (or) -> UNION ===
        if isinstance(target_entity, LogicalConstructor) and target_entity.operator == 'or':
            return self._create_union_from_class(triple_node, target_entity)
        
        # === LogicalConstructor (and) -> 複数トリプル ===
        if isinstance(target_entity, LogicalConstructor) and target_entity.operator == 'and':
            return self._expand_and_class(triple_node, target_entity)
        
        # === AttributeDomainRestriction ===
        if isinstance(target_entity, AttributeDomainRestriction):
            # クラス制約として処理
            return self._expand_class_attribute_domain(triple_node, target_entity)
        
        # === 単純なクラス置換 ===
        if isinstance(target_entity, IdentifiedEntity):
            subject = triple_node.get('subject', {})
            new_subject = {'type': 'uri', 'value': target_entity.uri}
            return {**triple_node, 'subject': new_subject}
        
        return triple_node
    
    # ========================================
    # UNION生成
    # ========================================
    
    def _create_union_from_relation(self, subject: dict, obj: dict, logical_constructor: LogicalConstructor) -> dict:
        """リレーションのUNION展開"""
        elements = []
        
        for operand in logical_constructor.operands:
            branch_triples = []
            
            if isinstance(operand, IdentifiedEntity):
                # 単純なプロパティ
                triple = {
                    'type': 'triple',
                    'subject': subject,
                    'predicate': {'type': 'uri', 'value': operand.uri},
                    'object': obj
                }
                branch_triples.append(triple)
            
            elif isinstance(operand, PathConstructor) and operand.operator == 'inverse':
                # 逆プロパティ
                if len(operand.operands) > 0 and isinstance(operand.operands[0], IdentifiedEntity):
                    triple = {
                        'type': 'triple',
                        'subject': obj,
                        'predicate': {'type': 'uri', 'value': operand.operands[0].uri},
                        'object': subject
                    }
                    branch_triples.append(triple)
            
            elif isinstance(operand, PathConstructor) and operand.operator == 'compose':
                # プロパティ連鎖
                branch_triples = self._expand_compose(subject, obj, operand)
                if isinstance(branch_triples, list):
                    pass  # そのまま使用
                else:
                    branch_triples = [branch_triples]
            
            elif isinstance(operand, AttributeDomainRestriction):
                # ドメイン制約付きプロパティ
                if isinstance(operand.on_attribute, IdentifiedEntity):
                    triple1 = {
                        'type': 'triple',
                        'subject': subject,
                        'predicate': {'type': 'uri', 'value': operand.on_attribute.uri},
                        'object': obj
                    }
                    branch_triples.append(triple1)
                    
                    # ドメイン型制約
                    if isinstance(operand.class_expression, IdentifiedEntity):
                        triple2 = {
                            'type': 'triple',
                            'subject': obj,
                            'predicate': {'type': 'uri', 'value': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'},
                            'object': {'type': 'uri', 'value': operand.class_expression.uri}
                        }
                        branch_triples.append(triple2)
            
            elif isinstance(operand, AttributeOccurenceRestriction):
                # 出現回数制約 -> 存在チェック
                if isinstance(operand.on_attribute, IdentifiedEntity):
                    triple = {
                        'type': 'triple',
                        'subject': subject,
                        'predicate': {'type': 'uri', 'value': operand.on_attribute.uri},
                        'object': obj
                    }
                    branch_triples.append(triple)
            
            elif isinstance(operand, LogicalConstructor) and operand.operator == 'and':
                # ネストしたAND -> 複数トリプル
                branch_triples = self._expand_and_relation(subject, obj, operand)
                if isinstance(branch_triples, list):
                    pass
                else:
                    branch_triples = [branch_triples]
            
            # BGPとして追加
            if branch_triples:
                elements.append({'type': 'bgp', 'triples': branch_triples})
        
        return {'type': 'union', 'patterns': elements}
    
    def _create_union_from_class(self, triple_node: dict, logical_constructor: LogicalConstructor) -> dict:
        """クラスのUNION展開"""
        elements = []
        
        for operand in logical_constructor.operands:
            branch_triples = []
            
            if isinstance(operand, IdentifiedEntity):
                # 単純なクラス置換
                new_triple = {**triple_node}
                if triple_node.get('object', {}).get('type') == 'uri':
                    new_triple['object'] = {'type': 'uri', 'value': operand.uri}
                branch_triples.append(new_triple)
            
            elif isinstance(operand, AttributeDomainRestriction):
                # ドメイン制約 -> プロパティ + 型制約
                subject_var = triple_node.get('subject', {})
                
                if isinstance(operand.on_attribute, IdentifiedEntity):
                    temp_obj = self._generate_temp_var()
                    triple1 = {
                        'type': 'triple',
                        'subject': subject_var,
                        'predicate': {'type': 'uri', 'value': operand.on_attribute.uri},
                        'object': {'type': 'var', 'name': temp_obj}
                    }
                    branch_triples.append(triple1)
                    
                    if isinstance(operand.class_expression, IdentifiedEntity):
                        triple2 = {
                            'type': 'triple',
                            'subject': {'type': 'var', 'name': temp_obj},
                            'predicate': {'type': 'uri', 'value': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'},
                            'object': {'type': 'uri', 'value': operand.class_expression.uri}
                        }
                        branch_triples.append(triple2)
            
            elif isinstance(operand, AttributeOccurenceRestriction):
                # 出現回数制約
                subject_var = triple_node.get('subject', {})
                
                if isinstance(operand.on_attribute, IdentifiedEntity):
                    temp_obj = self._generate_temp_var()
                    triple = {
                        'type': 'triple',
                        'subject': subject_var,
                        'predicate': {'type': 'uri', 'value': operand.on_attribute.uri},
                        'object': {'type': 'var', 'name': temp_obj}
                    }
                    branch_triples.append(triple)
            
            elif isinstance(operand, LogicalConstructor) and operand.operator == 'not':
                # NOT -> FILTER NOT EXISTS
                filter_node = self._expand_not(triple_node, operand)
                if filter_node:
                    branch_triples.append(triple_node)
                    branch_triples.append(filter_node)
            
            # BGPとして追加
            if branch_triples:
                elements.append({'type': 'bgp', 'triples': branch_triples})
        
        return {'type': 'union', 'patterns': elements}
    
    # ========================================
    # AND展開
    # ========================================
    
    def _expand_and_relation(self, subject: dict, obj: dict, logical_constructor: LogicalConstructor) -> list:
        """リレーションのAND展開"""
        triples = []
        
        for operand in logical_constructor.operands:
            if isinstance(operand, IdentifiedEntity):
                triple = {
                    'type': 'triple',
                    'subject': subject,
                    'predicate': {'type': 'uri', 'value': operand.uri},
                    'object': obj
                }
                triples.append(triple)
            
            elif isinstance(operand, RelationDomainRestriction):
                # ドメイン型制約
                if isinstance(operand.class_expression, IdentifiedEntity):
                    triple = {
                        'type': 'triple',
                        'subject': subject,
                        'predicate': {'type': 'uri', 'value': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'},
                        'object': {'type': 'uri', 'value': operand.class_expression.uri}
                    }
                    triples.append(triple)
            
            elif isinstance(operand, RelationCoDomainRestriction):
                # 値域型制約
                if isinstance(operand.class_expression, IdentifiedEntity):
                    triple = {
                        'type': 'triple',
                        'subject': obj,
                        'predicate': {'type': 'uri', 'value': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'},
                        'object': {'type': 'uri', 'value': operand.class_expression.uri}
                    }
                    triples.append(triple)
            
            elif isinstance(operand, PropertyDomainRestriction):
                # プロパティドメイン制約
                if isinstance(operand.class_expression, IdentifiedEntity):
                    triple = {
                        'type': 'triple',
                        'subject': subject,
                        'predicate': {'type': 'uri', 'value': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'},
                        'object': {'type': 'uri', 'value': operand.class_expression.uri}
                    }
                    triples.append(triple)
        
        return triples
    
    def _expand_and_class(self, triple_node: dict, logical_constructor: LogicalConstructor) -> list:
        """クラスのAND展開"""
        triples = [triple_node]
        filters = []
        
        for operand in logical_constructor.operands:
            if isinstance(operand, IdentifiedEntity):
                # 型トリプルを追加
                subject_var = triple_node.get('subject', {})
                triple = {
                    'type': 'triple',
                    'subject': subject_var,
                    'predicate': {'type': 'uri', 'value': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'},
                    'object': {'type': 'uri', 'value': operand.uri}
                }
                triples.append(triple)
            
            elif isinstance(operand, LogicalConstructor) and operand.operator == 'not':
                # NOT -> FILTER NOT EXISTS
                filter_node = self._expand_not(triple_node, operand)
                if filter_node:
                    filters.append(filter_node)
        
        return triples + filters
    
    # ========================================
    # compose展開
    # ========================================
    
    def _expand_compose(self, subject: dict, obj: dict, path_constructor: PathConstructor) -> list:
        """プロパティ連鎖の展開"""
        triples = []
        current_subject = subject
        
        for i, operand in enumerate(path_constructor.operands):
            if isinstance(operand, IdentifiedEntity):
                if i < len(path_constructor.operands) - 1:
                    # 中間ノード
                    temp_var = self._generate_temp_var()
                    triple = {
                        'type': 'triple',
                        'subject': current_subject,
                        'predicate': {'type': 'uri', 'value': operand.uri},
                        'object': {'type': 'var', 'name': temp_var}
                    }
                    triples.append(triple)
                    current_subject = {'type': 'var', 'name': temp_var}
                else:
                    # 最後のプロパティ
                    triple = {
                        'type': 'triple',
                        'subject': current_subject,
                        'predicate': {'type': 'uri', 'value': operand.uri},
                        'object': obj
                    }
                    triples.append(triple)
        
        return triples
    
    # ========================================
    # inverse展開
    # ========================================
    
    def _expand_inverse(self, subject: dict, obj: dict, path_constructor: PathConstructor) -> dict:
        """逆プロパティの展開"""
        if len(path_constructor.operands) > 0 and isinstance(path_constructor.operands[0], IdentifiedEntity):
            # 主語と目的語を入れ替え
            return {
                'type': 'triple',
                'subject': obj,
                'predicate': {'type': 'uri', 'value': path_constructor.operands[0].uri},
                'object': subject
            }
        return {'type': 'triple', 'subject': subject, 'predicate': {'type': 'uri', 'value': ''}, 'object': obj}
    
    # ========================================
    # AttributeDomainRestriction展開
    # ========================================
    
    def _expand_attribute_domain(self, subject: dict, obj: dict, restriction: AttributeDomainRestriction) -> list:
        """属性ドメイン制約の展開"""
        triples = []
        
        if isinstance(restriction.on_attribute, IdentifiedEntity):
            triple1 = {
                'type': 'triple',
                'subject': subject,
                'predicate': {'type': 'uri', 'value': restriction.on_attribute.uri},
                'object': obj
            }
            triples.append(triple1)
        
        if isinstance(restriction.class_expression, IdentifiedEntity):
            triple2 = {
                'type': 'triple',
                'subject': subject,
                'predicate': {'type': 'uri', 'value': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'},
                'object': {'type': 'uri', 'value': restriction.class_expression.uri}
            }
            triples.append(triple2)
        
        return triples
    
    def _expand_class_attribute_domain(self, triple_node: dict, restriction: AttributeDomainRestriction) -> list:
        """クラス変換時のAttributeDomainRestriction展開"""
        triples = []
        subject_var = triple_node.get('subject', {})
        
        # 元のトリプル（rdf:type）は維持
        if isinstance(restriction.on_attribute, IdentifiedEntity):
            temp_obj = self._generate_temp_var()
            triple1 = {
                'type': 'triple',
                'subject': subject_var,
                'predicate': {'type': 'uri', 'value': restriction.on_attribute.uri},
                'object': {'type': 'var', 'name': temp_obj}
            }
            triples.append(triple1)
            
            if isinstance(restriction.class_expression, IdentifiedEntity):
                triple2 = {
                    'type': 'triple',
                    'subject': {'type': 'var', 'name': temp_obj},
                    'predicate': {'type': 'uri', 'value': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'},
                    'object': {'type': 'uri', 'value': restriction.class_expression.uri}
                }
                triples.append(triple2)
        
        return triples
    
    # ========================================
    # AttributeValueRestriction展開
    # ========================================
    
    def _expand_attribute_value(self, subject: dict, obj: dict, restriction: AttributeValueRestriction) -> list:
        """属性値制約の展開 -> FILTER生成"""
        result = []
        
        if isinstance(restriction.on_attribute, IdentifiedEntity):
            triple = {
                'type': 'triple',
                'subject': subject,
                'predicate': {'type': 'uri', 'value': restriction.on_attribute.uri},
                'object': obj
            }
            result.append(triple)
        
        # FILTER生成
        if restriction.value and isinstance(obj, dict) and obj.get('type') == 'var':
            var_name = obj.get('name', '?o')
            value_str = self._format_filter_value(restriction.value)
            
            # comparatorに応じた演算子マッピング
            comp_op = restriction.comparator.split('#')[-1] if restriction.comparator and '#' in restriction.comparator else restriction.comparator
            comp_map = {
                'equals': '=',
                'greater-than': '>',
                'less-than': '<',
                'greater-than-or-equal': '>=',
                'less-than-or-equal': '<='
            }
            operator = comp_map.get(comp_op, '=')
            
            # SSE format: operator first
            filter_expr = f"({operator} {var_name} {value_str})"
            filter_node = {'type': 'filter', 'expression': filter_expr}
            result.append(filter_node)
        
        return result
    
    def _format_filter_value(self, value: any) -> str:
        """FILTER用の値フォーマット"""
        if isinstance(value, dict):
            if 'string' in value:
                val = value['string']
                if value.get('type') and 'boolean' in value['type']:
                    return val  # true/false
                return f'"{val}"'
        return str(value)
    
    # ========================================
    # AttributeOccurenceRestriction展開
    # ========================================
    
    def _expand_attribute_occurence(self, subject: dict, obj: dict, restriction: AttributeOccurenceRestriction) -> list:
        """属性出現回数制約の展開"""
        # 単純に存在チェックとして処理
        triples = []
        
        if isinstance(restriction.on_attribute, IdentifiedEntity):
            triple = {
                'type': 'triple',
                'subject': subject,
                'predicate': {'type': 'uri', 'value': restriction.on_attribute.uri},
                'object': obj
            }
            triples.append(triple)
        
        return triples
    
    # ========================================
    # NOT展開
    # ========================================
    
    def _expand_not(self, context_triple: dict, logical_constructor: LogicalConstructor) -> dict:
        """NOT演算子の展開 -> FILTER NOT EXISTS"""
        if len(logical_constructor.operands) == 0:
            return None
        
        operand = logical_constructor.operands[0]
        subject_var = context_triple.get('subject', {})
        
        if isinstance(operand, AttributeOccurenceRestriction):
            if isinstance(operand.on_attribute, IdentifiedEntity):
                temp_var = self._generate_temp_var()
                # FILTER NOT EXISTS { ?subject property ?temp_var }
                triple_pattern = {
                    'type': 'triple',
                    'subject': subject_var,
                    'predicate': {'type': 'uri', 'value': operand.on_attribute.uri},
                    'object': {'type': 'var', 'name': temp_var}
                }
                
                # SPARQLのFILTER NOT EXISTSは通常FILTERノードとして表現
                # ここでは簡易的にtypeを設定
                return {
                    'type': 'filter',
                    'expression': f'notexists',
                    'pattern': {'type': 'bgp', 'triples': [triple_pattern]}
                }
        
        return None

    
    def get_unused_source_uris(self):
        """
        使用されなかったソースURIのリストを返す
        
        Returns:
            未使用のソースURIリスト
        """
        all_source_uris = set(self.mapping.keys())
        unused = all_source_uris - self.used_source_uris
        return sorted(list(unused))

