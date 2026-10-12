# -*- coding: utf-8 -*-
"""
RDFS 限定 materialization（rdfs5, rdfs7, rdfs9, rdfs11 のみ。rdfs2/3 は適用しない）。
owlrl を使わず4規則を自前展開。決定的（同一入力→同一 .nt, ソート出力）。
元の .ttl/.owl は変更しない。キャッシュは data/datasets/_materialized/ に置く。

規則:
  rdfs11: (C subClassOf D)(D subClassOf E) => (C subClassOf E)   [subClassOf 推移閉包]
  rdfs5 : (P subPropertyOf Q)(Q subPropertyOf R) => (P subPropertyOf R) [subPropertyOf 推移閉包]
  rdfs9 : (X type C)(C subClassOf* D) => (X type D)              [型の上位伝播]
  rdfs7 : (X P Y)(P subPropertyOf* Q) => (X Q Y)                 [述語の上位伝播]

注意: 明示 subClassOf/subPropertyOf は「名前付き資源（非BNode）」のみ対象。
"""
import os, hashlib
from collections import defaultdict
import rdflib
from rdflib import Graph, RDF, RDFS, URIRef

DEFAULT_RULES = ('rdfs5', 'rdfs7', 'rdfs9', 'rdfs11')


def _transitive_closure(pairs):
    """pairs: iterable of (a, b)。推移閉包 {(a, c)} を返す（反射は含めない）。"""
    succ = defaultdict(set)
    for a, b in pairs:
        succ[a].add(b)
    closure = set()
    for start in list(succ.keys()):
        stack = list(succ[start])
        seen = set()
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            closure.add((start, n))
            stack.extend(succ.get(n, ()))
    return closure


def materialize(graph, rules=DEFAULT_RULES):
    """graph（rdflib.Graph）に rules を適用して新規トリプルを add。統計を返す。破壊的（同 graph に add）。"""
    rules = set(rules)
    # 名前付き subClassOf / subPropertyOf を収集
    sco = [(s, o) for s, o in graph.subject_objects(RDFS.subClassOf)
           if isinstance(s, URIRef) and isinstance(o, URIRef)]
    spo = [(s, o) for s, o in graph.subject_objects(RDFS.subPropertyOf)
           if isinstance(s, URIRef) and isinstance(o, URIRef)]
    sco_clo = _transitive_closure(sco)
    spo_clo = _transitive_closure(spo)
    sco_anc = defaultdict(set)
    for a, b in sco_clo:
        sco_anc[a].add(b)
    spo_anc = defaultdict(set)
    for a, b in spo_clo:
        spo_anc[a].add(b)

    new = []  # 追加候補（既存重複は後で除外）
    counts = {'rdfs11': 0, 'rdfs5': 0, 'rdfs9': 0, 'rdfs7': 0}

    if 'rdfs11' in rules:
        for a, b in sco_clo:
            t = (a, RDFS.subClassOf, b)
            if t not in graph:
                new.append(t); counts['rdfs11'] += 1
    if 'rdfs5' in rules:
        for a, b in spo_clo:
            t = (a, RDFS.subPropertyOf, b)
            if t not in graph:
                new.append(t); counts['rdfs5'] += 1
    if 'rdfs9' in rules:
        for s, c in graph.subject_objects(RDF.type):
            for d in sco_anc.get(c, ()):
                t = (s, RDF.type, d)
                if t not in graph:
                    new.append(t); counts['rdfs9'] += 1
    if 'rdfs7' in rules:
        # subPropertyOf を持つ述語ごとに、その使用トリプルへ上位述語版を追加
        for p, supers in spo_anc.items():
            triples = list(graph.subject_objects(p))
            for s, o in triples:
                for q in supers:
                    t = (s, q, o)
                    if t not in graph:
                        new.append(t); counts['rdfs7'] += 1

    before = len(graph)
    for t in new:
        graph.add(t)
    after = len(graph)
    return {
        'rules': sorted(rules),
        'triples_before': before,
        'triples_after': after,
        'added_total': after - before,
        'added_by_rule': counts,
    }


def _fingerprint(file_paths, rules):
    """入力ファイル集合（パス＋mtime＋size）と規則から決定的ハッシュ。"""
    h = hashlib.sha256()
    for p in sorted(file_paths):
        h.update(p.encode('utf-8'))
        try:
            st = os.stat(p)
            h.update(f'{st.st_size}:{int(st.st_mtime)}'.encode())
        except OSError:
            h.update(b'MISSING')
    h.update(','.join(sorted(rules)).encode())
    return h.hexdigest()[:16]


def materialized_cache_path(cache_dir, file_paths, rules):
    return os.path.join(cache_dir, f'mat_{_fingerprint(file_paths, rules)}.nt')


def load_or_build(graph, file_paths, cache_dir, rules=DEFAULT_RULES, verbose=True):
    """
    graph: 既に元データをロード済みの rdflib.Graph（materialize は破壊的に add する）。
    file_paths: 元データファイル一覧（フィンガープリント用。元ファイルは変更しない）。
    cache_dir: data/datasets/_materialized/ 等。存在するキャッシュ .nt があれば graph にマージ、無ければ生成して保存。
    戻り値: 統計 dict（cache ヒット有無・追加トリプル数）。
    """
    os.makedirs(cache_dir, exist_ok=True)
    cache = materialized_cache_path(cache_dir, file_paths, rules)
    if os.path.exists(cache):
        cg = Graph()
        cg.parse(cache, format='nt')
        before = len(graph)
        for t in cg:
            graph.add(t)
        if verbose:
            print(f'  [rdfs] cache hit: {cache} (+{len(graph)-before} triples merged)')
        return {'cache_hit': True, 'cache': cache, 'added_total': len(graph) - before, 'rules': sorted(set(rules))}
    stats = materialize(graph, rules)
    # 追加分のみを決定的にソート出力（元データは書かない。materialize 済み差分を .nt キャッシュ）
    # 追加分を得るため、再計算ではなく graph 全体から「元に無かった分」を出すのは高コストなので、
    # ここでは graph 全体をソート出力せず、追加規則で得た new を別途保存する方式に変更する。
    # → materialize() が追加した triple を安全に再現するため、キャッシュには graph 全体を .nt でソート保存する。
    lines = sorted(_nt_line(s, p, o) for s, p, o in graph)
    with open(cache, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + ('\n' if lines else ''))
    stats['cache_hit'] = False
    stats['cache'] = cache
    if verbose:
        print(f'  [rdfs] built cache: {cache} (+{stats["added_total"]} triples)')
    return stats


def _nt_line(s, p, o):
    """rdflib 項を N-Triples 行に（決定的）。"""
    def term(t):
        if isinstance(t, URIRef):
            return f'<{t}>'
        if isinstance(t, rdflib.BNode):
            return f'_:{t}'
        # Literal
        val = str(t).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        lit = f'"{val}"'
        if t.language:
            lit += f'@{t.language}'
        elif t.datatype:
            lit += f'^^<{t.datatype}>'
        return lit
    return f'{term(s)} {term(p)} {term(o)} .'
