package sparql_serializer_java;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import org.apache.jena.graph.Node;
import org.apache.jena.graph.NodeFactory;
import org.apache.jena.graph.Triple;
import org.apache.jena.query.Query;
import org.apache.jena.query.QueryFactory;
import org.apache.jena.query.SortCondition;
import org.apache.jena.sparql.core.Var;
import org.apache.jena.sparql.core.TriplePath;
import org.apache.jena.sparql.expr.Expr;
import org.apache.jena.sparql.expr.ExprVar;
import org.apache.jena.sparql.path.*;
import org.apache.jena.sparql.sse.SSE;
import org.apache.jena.sparql.syntax.*;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * JSON AST（書き換え済み）を標準入力から読み取り、
 * Jena Queryオブジェクトを再構築してSPARQL文字列として標準出力に書き出す。
 */
public class SparqlAstSerializer {

    public static void main(String[] args) {
        try {
            // 標準入力からJSON ASTを読み取る
            BufferedReader reader = new BufferedReader(new InputStreamReader(System.in));
            StringBuilder jsonBuilder = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                jsonBuilder.append(line);
            }
            String jsonString = jsonBuilder.toString();

            // JSONをパース
            Gson gson = new Gson();
            JsonObject astJson = gson.fromJson(jsonString, JsonObject.class);

            // Queryオブジェクトを再構築
            Query query = reconstructQuery(astJson);

            // SPARQL文字列として出力
            System.out.println(query.serialize());

        } catch (Exception e) {
            System.err.println("Error serializing AST to SPARQL:");
            e.printStackTrace(System.err);
            System.exit(1);
        }
    }

    /**
     * JSON ASTからJena Queryオブジェクトを再構築する
     */
    private static Query reconstructQuery(JsonObject astJson) {
        Query query = QueryFactory.create();

        // Prefixマッピングを設定
        if (astJson.has("prefixes")) {
            JsonObject prefixes = astJson.getAsJsonObject("prefixes");
            for (Map.Entry<String, JsonElement> entry : prefixes.entrySet()) {
                query.setPrefix(entry.getKey(), entry.getValue().getAsString());
            }
        }

        // クエリタイプを設定
        String queryType = astJson.has("queryType") ? astJson.get("queryType").getAsString() : "SELECT";
        switch (queryType) {
            case "SELECT":
                query.setQuerySelectType();
                break;
            case "CONSTRUCT":
                query.setQueryConstructType();
                break;
            case "DESCRIBE":
                query.setQueryDescribeType();
                break;
            case "ASK":
                query.setQueryAskType();
                break;
        }

        // DISTINCT フラグを設定
        if (astJson.has("isDistinct") && astJson.get("isDistinct").getAsBoolean()) {
            query.setDistinct(true);
        }

        // SELECT変数を設定
        if (astJson.has("selectVariables")) {
            JsonArray selectVars = astJson.getAsJsonArray("selectVariables");
            for (JsonElement varElement : selectVars) {
                query.addResultVar(varElement.getAsString());
            }
        }

        // WHERE句（ASTパターン）を設定
        if (astJson.has("ast")) {
            JsonObject astNode = astJson.getAsJsonObject("ast");
            Element whereClause = reconstructElement(astNode);
            query.setQueryPattern(whereClause);
        }

        // ORDER BY を設定
        if (astJson.has("orderBy") && astJson.getAsJsonArray("orderBy").size() > 0) {
            JsonArray orderByArray = astJson.getAsJsonArray("orderBy");
            for (JsonElement orderElement : orderByArray) {
                String orderStr = orderElement.getAsString();
                // "(SortCondition ?var)" のような文字列から変数名を抽出
                // 簡易実装: ?で始まる変数名を抽出
                if (orderStr.contains("?")) {
                    String varName = orderStr.substring(orderStr.indexOf("?") + 1);
                    varName = varName.replaceAll("[^a-zA-Z0-9_]", ""); // 記号を除去
                    Expr expr = new ExprVar(varName);
                    query.addOrderBy(expr, Query.ORDER_ASCENDING);
                }
            }
        }

        // LIMIT を設定
        if (astJson.has("limit") && !astJson.get("limit").isJsonNull()) {
            query.setLimit(astJson.get("limit").getAsLong());
        }

        // OFFSET を設定
        if (astJson.has("offset") && !astJson.get("offset").isJsonNull()) {
            query.setOffset(astJson.get("offset").getAsLong());
        }

        return query;
    }

    /**
     * JSON ASTのノードからJena Elementを再構築する（再帰的）
     */
    private static Element reconstructElement(JsonObject node) {
        String type = node.has("type") ? node.get("type").getAsString() : "";

        switch (type) {
            case "group":
                return reconstructGroup(node);
            case "bgp":
                return reconstructBGP(node);
            case "union":
                return reconstructUnion(node);
            case "optional":
                return reconstructOptional(node);
            case "filter":
                return reconstructFilter(node);
            default:
                // 未対応のノードタイプは空のグループを返す
                return new ElementGroup();
        }
    }

    /**
     * グループノードを再構築
     */
    private static ElementGroup reconstructGroup(JsonObject node) {
        ElementGroup group = new ElementGroup();
        if (node.has("patterns")) {
            JsonArray patterns = node.getAsJsonArray("patterns");
            for (JsonElement patternElement : patterns) {
                if (patternElement.isJsonObject()) {
                    Element element = reconstructElement(patternElement.getAsJsonObject());
                    group.addElement(element);
                }
            }
        }
        return group;
    }

    /**
     * BGP (Basic Graph Pattern) ノードを再構築
     * プロパティパスを含むトリプルにも対応
     */
    private static Element reconstructBGP(JsonObject node) {
        // トリプルパスを含む可能性があるため、ElementPathBlockを使用
        ElementPathBlock pathBlock = new ElementPathBlock();
        boolean hasPath = false;
        
        if (node.has("triples")) {
            JsonArray triples = node.getAsJsonArray("triples");
            for (JsonElement tripleElement : triples) {
                if (tripleElement.isJsonObject()) {
                    JsonObject tripleObj = tripleElement.getAsJsonObject();
                    String tripleType = tripleObj.has("type") ? tripleObj.get("type").getAsString() : "triple";
                    
                    if ("path_triple".equals(tripleType)) {
                        // プロパティパスを含むトリプル
                        hasPath = true;
                        Node subject = reconstructNode(tripleObj.getAsJsonObject("subject"));
                        Path path = reconstructPath(tripleObj.getAsJsonObject("path"));
                        Node object = reconstructNode(tripleObj.getAsJsonObject("object"));
                        pathBlock.addTriplePath(new TriplePath(subject, path, object));
                    } else {
                        // 通常のトリプル
                        Triple triple = reconstructTriple(tripleObj);
                        pathBlock.addTriple(triple);
                    }
                }
            }
        }
        
        return pathBlock;
    }
    
    /**
     * プロパティパスを再構築
     */
    private static Path reconstructPath(JsonObject pathJson) {
        String type = pathJson.has("type") ? pathJson.get("type").getAsString() : "";
        
        switch (type) {
            case "link":
                // 単純なプロパティリンク
                String uri = pathJson.get("uri").getAsString();
                return new P_Link(NodeFactory.createURI(uri));
                
            case "mod":
                // 修飾子付きパス (*, +, ?)
                Path subPath = reconstructPath(pathJson.getAsJsonObject("subPath"));
                String modifier = pathJson.get("modifier").getAsString();
                
                switch (modifier) {
                    case "*":
                        return new P_Mod(subPath, 0, -1);  // ZeroOrMore
                    case "+":
                        return new P_Mod(subPath, 1, -1);  // OneOrMore
                    case "?":
                        return new P_Mod(subPath, 0, 1);   // ZeroOrOne
                    case "custom":
                        long min = pathJson.get("min").getAsLong();
                        long max = pathJson.get("max").getAsLong();
                        return new P_Mod(subPath, min, max);
                    default:
                        throw new RuntimeException("Unknown path modifier: " + modifier);
                }
                
            case "inverse":
                // 逆方向パス (^)
                Path invSubPath = reconstructPath(pathJson.getAsJsonObject("subPath"));
                return new P_Inverse(invSubPath);
                
            case "seq":
                // シーケンス (/)
                Path left = reconstructPath(pathJson.getAsJsonObject("left"));
                Path right = reconstructPath(pathJson.getAsJsonObject("right"));
                return new P_Seq(left, right);
                
            case "alt":
                // 選択 (|)
                Path altLeft = reconstructPath(pathJson.getAsJsonObject("left"));
                Path altRight = reconstructPath(pathJson.getAsJsonObject("right"));
                return new P_Alt(altLeft, altRight);
                
            default:
                throw new RuntimeException("Unknown path type: " + type);
        }
    }

    /**
     * UNIONノードを再構築
     */
    private static ElementUnion reconstructUnion(JsonObject node) {
        ElementUnion union = new ElementUnion();
        if (node.has("patterns")) {
            JsonArray patterns = node.getAsJsonArray("patterns");
            for (JsonElement patternElement : patterns) {
                if (patternElement.isJsonObject()) {
                    Element element = reconstructElement(patternElement.getAsJsonObject());
                    union.addElement(element);
                }
            }
        }
        return union;
    }

    /**
     * OPTIONALノードを再構築
     */
    private static ElementOptional reconstructOptional(JsonObject node) {
        if (node.has("pattern")) {
            Element optElement = reconstructElement(node.getAsJsonObject("pattern"));
            return new ElementOptional(optElement);
        }
        return new ElementOptional(new ElementGroup());
    }

    /**
     * FILTERノードを再構築
     */
    private static ElementFilter reconstructFilter(JsonObject node) {
        // FILTER の式はS式形式（Lisp形式）で保存されているので、SSE.parseExpr() を使用
        if (node.has("expression")) {
            String exprString = node.get("expression").getAsString();
            
            try {
                // S式（例: "(regex ?label \"pattern\" \"i\")"）をJena Exprオブジェクトにパース
                Expr expr = SSE.parseExpr(exprString);
                return new ElementFilter(expr);
            } catch (Exception ex) {
                System.err.println("Error: Could not parse FILTER expression using SSE: " + exprString);
                System.err.println("  Error: " + ex.getMessage());
                throw new RuntimeException("Failed to parse FILTER expression: " + exprString, ex);
            }
        }
        
        // ここに到達することは想定外
        throw new RuntimeException("FILTER node has no expression");
    }

    /**
     * トリプルを再構築
     */
    private static Triple reconstructTriple(JsonObject tripleNode) {
        Node subject = reconstructNode(tripleNode.getAsJsonObject("subject"));
        Node predicate = reconstructNode(tripleNode.getAsJsonObject("predicate"));
        Node object = reconstructNode(tripleNode.getAsJsonObject("object"));
        return new Triple(subject, predicate, object);
    }

    /**
     * ノード（主語、述語、目的語）を再構築
     */
    private static Node reconstructNode(JsonObject nodeJson) {
        String type = nodeJson.has("type") ? nodeJson.get("type").getAsString() : "";
        String value = nodeJson.has("value") ? nodeJson.get("value").getAsString() : "";

        switch (type) {
            case "uri":
                return NodeFactory.createURI(value);
            case "variable":
                return Var.alloc(value).asNode();
            case "literal":
                // リテラルの完全な処理（言語タグ、データタイプ）
                if (nodeJson.has("datatype")) {
                    String datatype = nodeJson.get("datatype").getAsString();
                    return NodeFactory.createLiteral(value, NodeFactory.getType(datatype));
                } else if (nodeJson.has("language")) {
                    String language = nodeJson.get("language").getAsString();
                    return NodeFactory.createLiteral(value, language);
                } else {
                    return NodeFactory.createLiteral(value);
                }
            default:
                // デフォルトは変数として扱う
                return Var.alloc("unknown").asNode();
        }
    }
}
