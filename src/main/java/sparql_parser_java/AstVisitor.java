package sparql_parser_java;

import org.apache.jena.graph.Node;
import org.apache.jena.graph.Triple;
import org.apache.jena.sparql.core.TriplePath;
import org.apache.jena.sparql.expr.Expr;
import org.apache.jena.sparql.path.*;
import org.apache.jena.sparql.syntax.*;

import java.util.*;

/**
 * JenaのAST (Element) を再帰的に訪問し、
 * JSONにシリアライズ可能なMap/Listの構造に変換するVisitor。
 */
public class AstVisitor implements ElementVisitor {

    private final Stack<Object> stack = new Stack<>();

    public Object getAstRoot() {
        return stack.isEmpty() ? null : stack.peek();
    }

    private Map<String, Object> nodeToMap(Node node) {
        Map<String, Object> map = new LinkedHashMap<>();
        if (node == null) return map;

        if (node.isURI()) {
            map.put("type", "uri");
            map.put("value", node.getURI());
        } else if (node.isLiteral()) {
            map.put("type", "literal");
            map.put("value", node.getLiteralLexicalForm());
            if (node.getLiteralDatatypeURI() != null) {
                map.put("datatype", node.getLiteralDatatypeURI());
            }
            if (node.getLiteralLanguage() != null && !node.getLiteralLanguage().isEmpty()) {
                map.put("lang", node.getLiteralLanguage());
            }
        } else if (node.isVariable()) {
            map.put("type", "variable");
            map.put("value", node.getName());
        } else if (node.isBlank()) {
            map.put("type", "blank");
            map.put("value", node.getBlankNodeId().toString());
        } else {
            map.put("type", "unknown");
            map.put("value", node.toString());
        }
        return map;
    }
    
    /**
     * プロパティパスを構造化されたMapに変換
     */
    private Map<String, Object> pathToMap(Path path) {
        Map<String, Object> map = new LinkedHashMap<>();
        
        if (path instanceof P_Link) {
            // 単純なプロパティ（URIリンク）
            P_Link link = (P_Link) path;
            map.put("type", "link");
            map.put("uri", link.getNode().getURI());
        } else if (path instanceof P_Mod) {
            // 修飾子付きパス（*, +, ?）
            P_Mod mod = (P_Mod) path;
            map.put("type", "mod");
            map.put("subPath", pathToMap(mod.getSubPath()));
            
            long min = mod.getMin();
            long max = mod.getMax();
            
            if (min == 0 && max == -1) {
                map.put("modifier", "*");  // ZeroOrMore
            } else if (min == 1 && max == -1) {
                map.put("modifier", "+");  // OneOrMore
            } else if (min == 0 && max == 1) {
                map.put("modifier", "?");  // ZeroOrOne
            } else {
                map.put("modifier", "custom");
                map.put("min", min);
                map.put("max", max);
            }
        } else if (path.getClass().getSimpleName().equals("P_OneOrMore1") ||
                   path.getClass().getSimpleName().equals("P_ZeroOrMore1") ||
                   path.getClass().getSimpleName().equals("P_ZeroOrOne1")) {
            // Jenaの最適化されたOneOrMore/ZeroOrMore/ZeroOrOneクラス
            // これらはP_Modのサブクラスではないが、同等の機能を持つ
            // リフレクションでsubPathを取得
            try {
                java.lang.reflect.Method getSubPathMethod = path.getClass().getMethod("getSubPath");
                Path subPath = (Path) getSubPathMethod.invoke(path);
                
                map.put("type", "mod");
                map.put("subPath", pathToMap(subPath));
                
                String className = path.getClass().getSimpleName();
                if (className.equals("P_OneOrMore1")) {
                    map.put("modifier", "+");
                } else if (className.equals("P_ZeroOrMore1")) {
                    map.put("modifier", "*");
                } else if (className.equals("P_ZeroOrOne1")) {
                    map.put("modifier", "?");
                }
            } catch (Exception e) {
                // リフレクション失敗時は"complex"として扱う
                map.put("type", "complex");
                map.put("pathString", path.toString());
            }
        } else if (path instanceof P_Inverse) {
            // 逆方向パス (^)
            P_Inverse inv = (P_Inverse) path;
            map.put("type", "inverse");
            map.put("subPath", pathToMap(inv.getSubPath()));
        } else if (path instanceof P_Seq) {
            // シーケンス（パスの連結 /）
            P_Seq seq = (P_Seq) path;
            map.put("type", "seq");
            map.put("left", pathToMap(seq.getLeft()));
            map.put("right", pathToMap(seq.getRight()));
        } else if (path instanceof P_Alt) {
            // 選択（パスの選択肢 |）
            P_Alt alt = (P_Alt) path;
            map.put("type", "alt");
            map.put("left", pathToMap(alt.getLeft()));
            map.put("right", pathToMap(alt.getRight()));
        } else {
            // その他の複雑なパス
            map.put("type", "complex");
            map.put("pathString", path.toString());
        }
        
        return map;
    }
    
    private Map<String, Object> tripleToMap(Triple triple) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("type", "triple");
        map.put("subject", nodeToMap(triple.getSubject()));
        map.put("predicate", nodeToMap(triple.getPredicate()));
        map.put("object", nodeToMap(triple.getObject()));
        return map;
    }

    @Override
    public void visit(ElementTriplesBlock el) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("type", "bgp"); // Basic Graph Pattern
        List<Object> triples = new ArrayList<>();
        for (Triple triple : el.getPattern()) {
            triples.add(tripleToMap(triple));
        }
        map.put("triples", triples);
        stack.push(map);
    }

    @Override
    public void visit(ElementFilter el) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("type", "filter");
        // Exprの変換は複雑なので、ここでは単純にtoString()で表現
        map.put("expression", el.getExpr().toString());
        stack.push(map);
    }

    @Override
    public void visit(ElementGroup el) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("type", "group");
        List<Object> patterns = new ArrayList<>();
        for (Element element : el.getElements()) {
            element.visit(this);
            patterns.add(stack.pop());
        }
        map.put("patterns", patterns);
        stack.push(map);
    }

    // --- 他のElementタイプのvisitメソッドも同様に実装 ---
    // 今回のサンプルクエリでは上記3つが主ですが、網羅性を高めるために追加します。

    @Override
    public void visit(ElementUnion el) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("type", "union");
        List<Object> patterns = new ArrayList<>();
        for (Element element : el.getElements()) {
            element.visit(this);
            patterns.add(stack.pop());
        }
        map.put("patterns", patterns);
        stack.push(map);
    }

    @Override
    public void visit(ElementOptional el) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("type", "optional");
        el.getOptionalElement().visit(this);
        map.put("pattern", stack.pop());
        stack.push(map);
    }

    @Override
    public void visit(ElementPathBlock el) {
        // プロパティパスを含むトリプルパターンを処理
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("type", "bgp"); // BGP (Basic Graph Pattern) として扱う
        List<Object> triples = new ArrayList<>();
        
        for (TriplePath triplePath : el.getPattern()) {
            if (triplePath.isTriple()) {
                // 単純なトリプル
                triples.add(tripleToMap(triplePath.asTriple()));
            } else {
                // プロパティパスを含むトリプル
                Map<String, Object> pathTriple = new LinkedHashMap<>();
                pathTriple.put("type", "path_triple");
                pathTriple.put("subject", nodeToMap(triplePath.getSubject()));
                pathTriple.put("path", pathToMap(triplePath.getPath()));
                pathTriple.put("object", nodeToMap(triplePath.getObject()));
                triples.add(pathTriple);
            }
        }
        
        map.put("triples", triples);
        stack.push(map);
    }

    // 以下、今回は利用しないがインターフェースとして必要なメソッド
    @Override public void visit(ElementData el) { stack.push(Collections.singletonMap("type", "data")); }
    @Override public void visit(ElementDataset el) { stack.push(Collections.singletonMap("type", "dataset")); }
    @Override public void visit(ElementNamedGraph el) { stack.push(Collections.singletonMap("type", "namedgraph")); }
    @Override public void visit(ElementExists el) { stack.push(Collections.singletonMap("type", "exists")); }
    @Override public void visit(ElementNotExists el) { stack.push(Collections.singletonMap("type", "notexists")); }
    @Override public void visit(ElementMinus el) { stack.push(Collections.singletonMap("type", "minus")); }
    @Override public void visit(ElementService el) { stack.push(Collections.singletonMap("type", "service")); }
    @Override public void visit(ElementSubQuery el) { stack.push(Collections.singletonMap("type", "subquery")); }
    @Override public void visit(ElementAssign el) { stack.push(Collections.singletonMap("type", "assign")); }
    @Override public void visit(ElementBind el) { stack.push(Collections.singletonMap("type", "bind")); }
    @Override public void visit(ElementLateral el) { stack.push(Collections.singletonMap("type", "lateral")); }
}