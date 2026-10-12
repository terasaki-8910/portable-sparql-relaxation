#!/usr/bin/env python3
"""
reproduce_tables.py -- recompute every experimental number reported in the
paper "Toward Portable SPARQL Queries across Linked Open Data: A Query
Relaxation Approach to Cross-Dataset Rewriting" from frozen per-query CSVs.

Standard library only (csv for reading; argparse, decimal, hashlib for the CLI,
rounding and input fingerprints). No pandas, no network, no writes.

Every input is optional. A section whose input is not given is skipped, and so
are its --check-paper assertions.

    python reproduce_tables.py \
        --table1-csv    results/paper/table1/query_failure_classification_v3.csv \
        --cqa-csv       results/paper/exp1/full_pipeline_results.csv \
        --cqa-allowlist data/populations/cqa_545.txt \
        --manual-csv    results/paper/manual90/relaxation_query_results.csv \
        --check-paper

In the review artifact, running the script without any input argument uses
the frozen files under results/paper/ (and data/populations/cqa_545.txt as the
CQA allowlist); only the files that exist are read.

Definitions (they reproduce how the paper's numbers were derived):

Table 1 (preliminary failure study; query_failure_classification_v3.csv)
    population    rows with input_count > 0 (source query non-empty)
    pattern       primary_category (one pattern per query); ratio = count / n

Experiment 1, CQA (full_pipeline_results.csv; columns custom_*)
    population    rows whose (pair_name, query_file) is in --cqa-allowlist (if
                  given) AND custom_initial_source_count > 0 (the paper's
                  source-side exclusion; an empty reference set makes P/R/F1
                  undefined)
    strict        custom_initial_result_count > 0
    failing       custom_initial_result_count == 0 and initial_status == 'empty_success'
                  (queries whose initial execution errored or timed out are counted
                  separately as timeout_or_error and are never relaxed)
    recovered     relaxation_applied == True AND custom_final_result_count > 0
    not recovered failing - recovered
    full pipeline custom_final_result_count > 0
    recovery rate recovered / failing
    mean F1/P/R   macro average of the per-query columns custom_{initial,final}_
                  {f1,precision,recall} over the population (the CSV stores
                  them rounded to 4 decimals; a full-precision recomputation
                  from tp/fp/fn is printed as a sensitivity check)
    F1 strict     mean custom_final_f1 over strict rows (identical to initial)
    F1 recovered  mean custom_final_f1 over recovered rows
    phase         relaxation_phase of a recovered row (Phase1_... -> L1, ...)

Experiment 1, Manual 90 (relaxation_query_results.csv)
    population    source_count > 0 (all 90 rows)
    strict        translated_empty == False
    failing       translated_empty == True
    recovered     all_conditions_met == True
    full pipeline final count > 0, where final = relaxation_count if
                  relaxation_applied else translated_count
    F1 recovered  mean f1 over recovered rows (f1 is only computed by
                  evaluate_relaxation_test.py for relaxation_success rows; it is
                  a default 0.0 elsewhere, so no all-query F1 is reported)

Rounding is half-up at the precision printed in the paper; Python's round()
(round-half-even on binary floats) is not used.

--check-paper compares against the PAPER table below, which transcribes the
values printed in the current main.tex (with line references). When main.tex
numbers change (e.g. after a re-run), update PAPER in the same commit.
Exit status: 0 = all checks passed (or no --check-paper), 1 = at least one
mismatch, 2 = no input given and no frozen input file found.
"""

import argparse
import csv
import hashlib
import os
import sys
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

PHASES = [  # (short, relaxation_phase value, Table 4 row label)
    ('L1', 'Phase1_ResidualDeletion', 'L1: Residual-URI deletion'),
    ('L2', 'Phase2_FilterRemoval', 'L2: FILTER removal'),
    ('L3', 'Phase3_Optionalization', 'L3: OPTIONAL-ization'),
    ('L4a', 'Phase4a_ClassHierarchy', 'L4a: Class hierarchy'),
    ('L4b', 'Phase4b_PropertyHierarchy', 'L4b: Property hierarchy'),
    ('L5', 'Phase5_TypeRemoval', 'L5: Type-constraint removal'),
]
PHASE_OF = {name: short for short, name, _ in PHASES}
# Table 4 prints L4b and L5 in one row.
TABLE4_ROWS = [('L1',), ('L2',), ('L3',), ('L4a',), ('L4b', 'L5')]
TABLE4_LABELS = {('L1',): 'L1: Residual-URI deletion', ('L2',): 'L2: FILTER removal',
                 ('L3',): 'L3: OPTIONAL-ization', ('L4a',): 'L4a: Class hierarchy',
                 ('L4b', 'L5'): 'L4b / L5'}
CAUSES = [  # Sect. 7.1 grouping of phases by failure cause
    ('vocabulary-correspondence gap (L1)', ('L1',)),
    ('structural divergence (L2+L3)', ('L2', 'L3')),
    ('granularity mismatch (L4a+L4b+L5)', ('L4a', 'L4b', 'L5')),
]
PATTERNS = [
    ('A', 'System error'), ('B', 'Rewriter inconsistency'),
    ('C', 'Partial vocabulary gap'), ('D', 'Constraint mismatch'),
    ('E', 'Composite-triple misalignment'), ('F', 'Concept-hierarchy misalignment'),
    ('G', 'Predicate misalignment'), ('H', 'Structural mismatch'),
]
CONFERENCE_TRACK = {'cmt', 'conference', 'confOf', 'edas', 'ekaw'}

# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _raise_csv_limit():
    limit = sys.maxsize
    while True:  # sys.maxsize overflows a C long on Windows
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def as_bool(s):
    return str(s).strip().lower() == 'true'


def as_int(s):
    s = str(s).strip()
    return int(float(s)) if s else 0


def as_float(s):
    s = str(s).strip()
    return float(s) if s else 0.0


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def pct(num, den):
    return 100.0 * num / den if den else None


def rnd(value, decimals):
    """Half-up rounding to `decimals` places, returned as text ('--' for None)."""
    if value is None:
        return '--'
    quantum = Decimal(1).scaleb(-decimals)
    return str(Decimal(repr(float(value))).quantize(quantum, rounding=ROUND_HALF_UP))


def sha256_16(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


def read_csv(path, required):
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        cols = reader.fieldnames or []
    missing = [c for c in required if c not in cols]
    if missing:
        sys.exit('ERROR: %s lacks required column(s): %s' % (path, ', '.join(missing)))
    return rows, cols


def read_allowlist(path):
    keys = []
    with open(path, encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            pair, _, query = line.partition(',')
            keys.append((pair.strip(), query.strip()))
    return keys


def prf1(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def phase_stats(recovered_rows, phase_col, f1_col=None):
    """count and mean F1 per phase short name over the recovered rows."""
    out, unknown = {}, []
    for short, _, _ in PHASES:
        out[short] = []
    for r in recovered_rows:
        short = PHASE_OF.get(r[phase_col].strip())
        if short is None:
            unknown.append(r[phase_col])
            continue
        out[short].append(as_float(r[f1_col]) if f1_col else None)
    return out, unknown


def add_phase_metrics(m, per_phase, n_recovered, with_f1):
    for short, vals in per_phase.items():
        m['phase_n:' + short] = len(vals)
        if with_f1:
            m['phase_f1:' + short] = mean(vals)
    for group in TABLE4_ROWS:
        key = '+'.join(group)
        vals = [v for s in group for v in per_phase[s]]
        m['phase_n:' + key] = len(vals)
        if with_f1:
            m['phase_f1:' + key] = mean(vals)
    m['phase_total'] = sum(len(v) for v in per_phase.values())
    for short, vals in per_phase.items():
        m['share:' + short] = pct(len(vals), n_recovered)
    for i, (_, group) in enumerate(CAUSES):
        m['cause:%d' % i] = pct(sum(len(per_phase[s]) for s in group), n_recovered)


# ---------------------------------------------------------------------------
# Table 1
# ---------------------------------------------------------------------------


def analyse_table1(path):
    rows, _ = read_csv(path, ['pair_name', 'query_file', 'input_count', 'primary_category'])
    pop = [r for r in rows if as_int(r['input_count']) > 0]
    m = {'rows_csv': len(rows), 'n': len(pop)}
    for p, _ in PATTERNS:
        m['count:' + p] = sum(1 for r in pop if r['primary_category'].strip() == p)
        m['ratio:' + p] = pct(m['count:' + p], len(pop))
    m['ratio:total'] = pct(sum(m['count:' + p] for p, _ in PATTERNS), len(pop))
    m['share:C+G'] = pct(m['count:C'] + m['count:G'], len(pop))
    m['share:E+G'] = pct(m['count:E'] + m['count:G'], len(pop))
    other = sorted('%s/%s' % (r['pair_name'], r['query_file']) for r in pop
                   if not set(r['pair_name'].split('-', 1)) <= CONFERENCE_TRACK)
    unknown = sorted({r['primary_category'] for r in pop} - {p for p, _ in PATTERNS})
    diag = [
        'population: input_count > 0 -> %d of %d rows (%d rows with input_count = 0 excluded)'
        % (len(pop), len(rows), len(rows) - len(pop)),
        'rows with output_count != 0 in population: %d (all analysed rewrites must be zero-result)'
        % sum(1 for r in pop if as_int(r.get('output_count', 0)) != 0),
        'population rows NOT from an OAEI Conference Track pair: %d %s'
        % (len(other), ('(' + ', '.join(other) + ')') if other else ''),
    ]
    if unknown:
        diag.append('WARNING unknown primary_category values: %s' % unknown)
    if 'is_input_zero' in rows[0]:
        mism = sum(1 for r in rows if as_bool(r['is_input_zero']) != (as_int(r['input_count']) == 0))
        diag.append('is_input_zero disagrees with input_count == 0 on %d rows' % mism)
    return m, diag


def print_table1(m, diag):
    print('\n== Table 1 (tab:patterns): failure patterns of zero-result strict rewrites ==')
    for d in diag:
        print('  ' + d)
    print('  %-7s %-32s %6s %9s' % ('Pattern', 'Name', 'Count', 'Ratio(%)'))
    for p, name in PATTERNS:
        print('  %-7s %-32s %6d %9s' % (p, name, m['count:' + p], rnd(m['ratio:' + p], 1)))
    print('  %-7s %-32s %6d %9s' % ('Total', '', m['n'], rnd(m['ratio:total'], 1)))
    print('  text: C+G = %d (%s%%), E+G = %d (%s%%)'
          % (m['count:C'] + m['count:G'], rnd(m['share:C+G'], 1),
             m['count:E'] + m['count:G'], rnd(m['share:E+G'], 1)))


# ---------------------------------------------------------------------------
# Experiment 1: CQA
# ---------------------------------------------------------------------------

CQA_REQUIRED = [
    'pair_name', 'query_file', 'input_query', 'custom_initial_source_count',
    'custom_initial_result_count', 'custom_initial_tp', 'custom_initial_fp',
    'custom_initial_fn', 'custom_initial_precision', 'custom_initial_recall',
    'custom_initial_f1', 'custom_final_result_count', 'custom_final_tp',
    'custom_final_fp', 'custom_final_fn', 'custom_final_precision',
    'custom_final_recall', 'custom_final_f1', 'relaxation_applied',
    'relaxation_phase', 'custom_translation_success',
]


def analyse_cqa(path, allowlist):
    rows, cols = read_csv(path, CQA_REQUIRED)
    key = lambda r: (r['pair_name'], r['query_file'])  # noqa: E731
    src = lambda r: as_int(r['custom_initial_source_count'])  # noqa: E731
    ini = lambda r: as_int(r['custom_initial_result_count'])  # noqa: E731
    fin = lambda r: as_int(r['custom_final_result_count'])  # noqa: E731
    diag = []
    keys = [key(r) for r in rows]
    if len(set(keys)) != len(keys):
        diag.append('WARNING duplicate (pair_name, query_file) keys in CSV: %d'
                    % (len(keys) - len(set(keys))))
    m = {'rows_csv': len(rows)}
    src0_csv = sorted('%s/%s' % key(r) for r in rows if src(r) == 0)
    m['src0_csv'] = len(src0_csv)
    pop = rows
    if allowlist:
        allow = read_allowlist(allowlist)
        aset = set(allow)
        missing = sorted(aset - set(keys))
        outside = sorted('%s/%s' % k for k in keys if k not in aset)
        pop = [r for r in rows if key(r) in aset]
        diag.append('allowlist: %d entries (%d unique); %d missing from CSV; %d CSV rows outside allowlist%s'
                    % (len(allow), len(aset), len(missing), len(outside),
                       (' (' + ', '.join(outside) + ')') if 0 < len(outside) <= 10 else ''))
        if missing:
            diag.append('WARNING allowlist entries missing from CSV: %s'
                        % ', '.join('%s/%s' % k for k in missing[:20]))
        diag.append('CSV rows outside allowlist == CSV rows with source_count == 0: %s'
                    % (sorted(outside) == src0_csv))
    src0_pop = sorted('%s/%s' % key(r) for r in pop if src(r) == 0)
    pop = [r for r in pop if src(r) > 0]
    diag.append('source_count == 0 in CSV: %d %s; removed from the population by the source-side rule: %d'
                % (len(src0_csv), ('(' + ', '.join(src0_csv) + ')') if 0 < len(src0_csv) <= 10 else '',
                   len(src0_pop)))
    n = len(pop)
    if not n:
        sys.exit('ERROR: empty CQA population after allowlist/source filters (%s)' % path)
    m['n'] = n
    strict = [r for r in pop if ini(r) > 0]
    # The paper counts as "initially failing" only the queries whose initial
    # execution returned zero results. Queries whose initial execution ended in
    # an error or hit the 60 s timeout are never relaxed, so they are reported
    # separately (Table 3 caption) and excluded from the recovery denominator.
    zero = [r for r in pop if ini(r) == 0]
    if 'initial_status' in (pop[0].keys() if pop else ()):
        failing = [r for r in zero if r['initial_status'] == 'empty_success']
        timedout = [r for r in zero if r['initial_status'] != 'empty_success']
    else:
        failing, timedout = zero, []
    m['timeout_or_error'] = len(timedout)
    recovered = [r for r in pop if as_bool(r['relaxation_applied']) and fin(r) > 0]
    full = [r for r in pop if fin(r) > 0]
    m.update({
        'strict': len(strict), 'strict_pct': pct(len(strict), n),
        'failing': len(failing), 'recovered': len(recovered),
        'not_recovered': len(failing) - len(recovered),
        'full': len(full), 'full_pct': pct(len(full), n),
        'rate': pct(len(recovered), len(failing)),
        'f1_initial': mean(as_float(r['custom_initial_f1']) for r in pop),
        'f1_final': mean(as_float(r['custom_final_f1']) for r in pop),
        'f1_strict': mean(as_float(r['custom_final_f1']) for r in strict),
        'f1_recovered': mean(as_float(r['custom_final_f1']) for r in recovered),
        'p_initial': 100 * mean(as_float(r['custom_initial_precision']) for r in pop),
        'p_final': 100 * mean(as_float(r['custom_final_precision']) for r in pop),
        'r_initial': 100 * mean(as_float(r['custom_initial_recall']) for r in pop),
        'r_final': 100 * mean(as_float(r['custom_final_recall']) for r in pop),
    })
    per_phase, unknown = phase_stats(recovered, 'relaxation_phase', 'custom_final_f1')
    add_phase_metrics(m, per_phase, len(recovered), with_f1=True)
    if unknown:
        diag.append('WARNING recovered rows with unknown relaxation_phase: %s' % unknown)

    # worked example of Sect. 4 (L1 on the residual cmt:title, cmt-conference)
    ex = [(r['query_file'], as_float(r['custom_final_f1'])) for r in recovered
          if r['pair_name'] == 'cmt-conference'
          and PHASE_OF.get(r['relaxation_phase'].strip()) == 'L1'
          and ('cmt:title' in r['input_query'] or 'http://cmt#title' in r['input_query'])]
    m['example_l1_title'] = ex
    vals = {rnd(f, 3) for _, f in ex}
    m['example_l1_title_f1'] = ex[0][1] if len(vals) == 1 else None

    # --- definition cross-checks -------------------------------------------
    rec_b = {key(r) for r in pop if ini(r) == 0 and fin(r) > 0}
    rec_c = {key(r) for r in pop if r['relaxation_phase'].strip() and fin(r) > 0}
    rec_a = {key(r) for r in recovered}
    diag.append('recovered: applied&final>0 = %d, initial==0&final>0 = %d, phase!=""&final>0 = %d, all equal: %s'
                % (len(rec_a), len(rec_b), len(rec_c), rec_a == rec_b == rec_c))
    diag.append('identity full == strict + recovered: %s (%d vs %d); rows with initial>0 but final==0: %d'
                % (len(full) == len(strict) + len(recovered), len(full),
                   len(strict) + len(recovered), sum(1 for r in pop if ini(r) > 0 and fin(r) == 0)))
    diag.append('strict rows whose final F1 differs from initial F1: %d'
                % sum(1 for r in strict if r['custom_final_f1'] != r['custom_initial_f1']))
    diag.append('custom_translation_success == False in population: %d'
                % sum(1 for r in pop if not as_bool(r['custom_translation_success'])))
    if 'initial_status' in cols:
        st = {}
        for r in failing:
            st[r['initial_status']] = st.get(r['initial_status'], 0) + 1
        diag.append('initially failing by initial_status: %s' % dict(sorted(st.items())))
        empty = [r for r in failing if r['initial_status'] == 'empty_success']
        errs = sorted('%s/%s' % key(r) for r in failing if r['initial_status'] != 'empty_success')
        if errs:
            diag.append('  failing rows that are execution errors/timeouts (never relaxed): %s'
                        % ', '.join(errs))
            diag.append('  alternative (true zero-result only): failing %d, recovered %d, rate %s%%'
                        % (len(empty), len(recovered), rnd(pct(len(recovered), len(empty)), 2)))
    if 'relaxation_attempted' in cols:
        diag.append('relaxation_attempted == True: %d'
                    % sum(1 for r in pop if as_bool(r['relaxation_attempted'])))
    if 'cap_hit' in cols:
        diag.append('cap_hit == True (true count above the old 10000 cap): %d'
                    % sum(1 for r in pop if as_bool(r['cap_hit'])))
    # rounding sensitivity: per-query metrics from tp/fp/fn at full precision
    full_prec = {}
    for stage in ('initial', 'final'):
        trip = [prf1(as_int(r['custom_%s_tp' % stage]), as_int(r['custom_%s_fp' % stage]),
                     as_int(r['custom_%s_fn' % stage])) for r in pop]
        full_prec['p_' + stage] = 100 * mean(t[0] for t in trip)
        full_prec['r_' + stage] = 100 * mean(t[1] for t in trip)
        full_prec['f1_' + stage] = mean(t[2] for t in trip)
        worst = max(abs(t[2] - as_float(r['custom_%s_f1' % stage])) for t, r in zip(trip, pop))
        diag.append('custom_%s_f1 column vs 2PR/(P+R) from tp/fp/fn: max |diff| = %.5f' % (stage, worst))
    flips = [k for k, d in (('f1_initial', 3), ('f1_final', 3), ('p_initial', 1),
                            ('p_final', 1), ('r_initial', 1), ('r_final', 1))
             if rnd(full_prec[k], d) != rnd(m[k], d)]
    diag.append('means from full-precision tp/fp/fn: F1 %.5f -> %.5f, P %.4f -> %.4f, R %.4f -> %.4f; '
                'printed values that would change: %s'
                % (full_prec['f1_initial'], full_prec['f1_final'], full_prec['p_initial'],
                   full_prec['p_final'], full_prec['r_initial'], full_prec['r_final'],
                   flips or 'none'))
    return m, diag


# ---------------------------------------------------------------------------
# Experiment 1: Manual 90
# ---------------------------------------------------------------------------

MANUAL_REQUIRED = [
    'pair_name', 'query_file', 'source_count', 'translation_success',
    'translated_count', 'translated_empty', 'relaxation_applied', 'relaxation_phase',
    'relaxation_count', 'relaxation_success', 'all_conditions_met', 'f1',
]


def analyse_manual(path):
    rows, _ = read_csv(path, MANUAL_REQUIRED)
    diag = []
    final = lambda r: (as_int(r['relaxation_count']) if as_bool(r['relaxation_applied'])  # noqa: E731
                       else as_int(r['translated_count']))
    src0 = [r for r in rows if as_int(r['source_count']) <= 0]
    pop = [r for r in rows if as_int(r['source_count']) > 0]
    n = len(pop)
    strict = [r for r in pop if not as_bool(r['translated_empty'])]
    failing = [r for r in pop if as_bool(r['translated_empty'])]
    recovered = [r for r in pop if as_bool(r['all_conditions_met'])]
    full = [r for r in pop if final(r) > 0]
    m = {
        'rows_csv': len(rows), 'src0_csv': len(src0), 'n': n,
        'strict': len(strict), 'strict_pct': pct(len(strict), n),
        'failing': len(failing), 'recovered': len(recovered),
        'not_recovered': len(failing) - len(recovered),
        'full': len(full), 'full_pct': pct(len(full), n),
        'rate': pct(len(recovered), len(failing)),
        'f1_recovered': mean(as_float(r['f1']) for r in recovered),
    }
    per_phase, unknown = phase_stats(recovered, 'relaxation_phase', 'f1')
    add_phase_metrics(m, per_phase, len(recovered), with_f1=True)
    if unknown:
        diag.append('WARNING recovered rows with unknown relaxation_phase: %s' % unknown)
    diag.append('population: source_count > 0 -> %d of %d rows' % (n, len(rows)))
    diag.append('translation_success == False: %d (a failed translation would leave translated_empty at its default False)'
                % sum(1 for r in pop if not as_bool(r['translation_success'])))
    diag.append('translated_empty disagrees with translated_count == 0: %d'
                % sum(1 for r in pop if as_bool(r['translated_empty']) != (as_int(r['translated_count']) == 0)))
    diag.append('all_conditions_met disagrees with relaxation_success: %d; recovered rows not initially failing: %d'
                % (sum(1 for r in pop if as_bool(r['all_conditions_met']) != as_bool(r['relaxation_success'])),
                   sum(1 for r in recovered if not as_bool(r['translated_empty']))))
    diag.append('identity full == strict + recovered: %s (%d vs %d)'
                % (len(full) == len(strict) + len(recovered), len(full), len(strict) + len(recovered)))
    diag.append('info: mean f1 over all %d rows = %.5f (non-recovered rows carry an uncomputed f1 = 0; not a paper metric)'
                % (n, mean(as_float(r['f1']) for r in pop)))
    return m, diag



# ---------------------------------------------------------------------------
# printing of the paper tables
# ---------------------------------------------------------------------------


def print_table3(settings):
    print('\n== Table 3 (tab:oaei): recovery results ==')
    head = ['%s (%d)' % (lab, m['n']) for lab, m, _ in settings]
    print('  %-30s' % '' + ''.join('%16s' % h for h in head))
    rows = [
        ('Non-empty, strict rewriting', lambda m: str(m['strict'])),
        ('Initially failing', lambda m: str(m['failing'])),
        ('Timed out or errored', lambda m: str(m.get('timeout_or_error', '--'))),
        ('Recovered', lambda m: str(m['recovered'])),
        ('Not recovered', lambda m: str(m['not_recovered'])),
        ('Non-empty, full pipeline', lambda m: str(m['full'])),
        ('Zero-result recovery rate', lambda m: rnd(m['rate'], 2) + '%'),
        ('Mean F1 (recovered)', lambda m: rnd(m.get('f1_recovered'), 3)),
    ]
    for label, f in rows:
        print('  %-30s' % label + ''.join('%16s' % f(m) for _, m, _ in settings))


def print_table4(settings):
    print('\n== Table 4 (tab:phasebreak): recoveries per phase (F1 = mean over that phase) ==')
    head = ''
    for lab, m, has_f1 in settings:
        head += '%12s' % (lab + ' n') + ('%12s' % (lab + ' F1') if has_f1 else '')
    print('  %-28s' % 'Phase' + head)
    for group in TABLE4_ROWS:
        k = '+'.join(group)
        line = '  %-28s' % TABLE4_LABELS[group]
        for _, m, has_f1 in settings:
            line += '%12d' % m['phase_n:' + k]
            if has_f1:
                line += '%12s' % rnd(m['phase_f1:' + k], 3)
        print(line)
    line = '  %-28s' % 'Total'
    for _, m, has_f1 in settings:
        line += '%12d' % m['phase_total'] + ('%12s' % '' if has_f1 else '')
    print(line)
    print('  (L4b and L5 separately: ' + '; '.join(
        '%s L4b %d, L5 %d' % (lab, m['phase_n:L4b'], m['phase_n:L5']) for lab, m, _ in settings) + ')')


def print_text_numbers(settings):
    print('\n== Numbers in the running text ==')
    for lab, m, _ in settings:
        if lab == 'CQA':
            print('  CQA: CSV rows %d, source_count == 0 in CSV %d, evaluated %d'
                  % (m['rows_csv'], m['src0_csv'], m['n']))
            print('  CQA: strict %d (%s%%), full pipeline %d (%s%%), %d of %d failing recovered (%s%%)'
                  % (m['strict'], rnd(m['strict_pct'], 1), m['full'], rnd(m['full_pct'], 1),
                     m['recovered'], m['failing'], rnd(m['rate'], 2)))
            print('  CQA: mean F1 %s -> %s (all %d); strict-success %s (n=%d); recovered %s (n=%d)'
                  % (rnd(m['f1_initial'], 3), rnd(m['f1_final'], 3), m['n'], rnd(m['f1_strict'], 3),
                     m['strict'], rnd(m['f1_recovered'], 3), m['recovered']))
            print('  CQA: raw means F1 %.5f -> %.5f, strict %.5f, recovered %s'
                  % (m['f1_initial'], m['f1_final'], m['f1_strict'],
                     '%.5f' % m['f1_recovered'] if m['f1_recovered'] is not None else '--'))
            print('  CQA: Precision %s%% -> %s%%, Recall %s%% -> %s%% (raw %.4f -> %.4f, %.4f -> %.4f)'
                  % (rnd(m['p_initial'], 1), rnd(m['p_final'], 1), rnd(m['r_initial'], 1),
                     rnd(m['r_final'], 1), m['p_initial'], m['p_final'], m['r_initial'], m['r_final']))
            ex = ', '.join('%s F1 %.4f' % e for e in m['example_l1_title']) or 'none'
            print('  CQA: L1 worked example (cmt-conference, residual cmt:title): %s' % ex)
        elif lab == 'Manual':
            print('  Manual: strict %d (%s%%), full pipeline %d (%s%%), %d of %d failing recovered (%s%%), '
                  'recovered mean F1 %s (raw %.5f)'
                  % (m['strict'], rnd(m['strict_pct'], 1), m['full'], rnd(m['full_pct'], 1),
                     m['recovered'], m['failing'], rnd(m['rate'], 2), rnd(m['f1_recovered'], 3),
                     m['f1_recovered']))
            print('  Manual: L1 %s%% of recoveries, L2 %s%%' % (rnd(m['share:L1'], 1), rnd(m['share:L2'], 1)))
        causes = ', '.join('%s %s%%' % (name, rnd(m['cause:%d' % i], 2)) for i, (name, _) in enumerate(CAUSES))
        print('  %s: recoveries by failure cause (Sect. 7.1): %s' % (lab, causes))


# ---------------------------------------------------------------------------
# --check-paper: the paper's current printed values
# ---------------------------------------------------------------------------
# (metric key, printed value, printed decimals, where in main.tex)
# '--' means "not reported" and passes iff the computed value is None.

PAPER = {
    'Table1': [
        ('n', '53', 0, 'l.308, Table 1 Total'),
        ('count:A', '8', 0, 'Table 1'), ('ratio:A', '15.1', 1, 'Table 1'),
        ('count:B', '4', 0, 'Table 1'), ('ratio:B', '7.5', 1, 'Table 1'),
        ('count:C', '26', 0, 'Table 1, l.310'), ('ratio:C', '49.1', 1, 'Table 1, l.311'),
        ('count:D', '0', 0, 'Table 1'), ('ratio:D', '0', 1, 'Table 1'),
        ('count:E', '2', 0, 'Table 1'), ('ratio:E', '3.8', 1, 'Table 1'),
        ('count:F', '1', 0, 'Table 1'), ('ratio:F', '1.9', 1, 'Table 1'),
        ('count:G', '12', 0, 'Table 1, l.311'), ('ratio:G', '22.6', 1, 'Table 1, l.312'),
        ('count:H', '0', 0, 'Table 1'), ('ratio:H', '0', 1, 'Table 1'),
        ('ratio:total', '100', 1, 'Table 1'),
        ('share:C+G', '72', 0, 'Sect. 4 "approximately 72%"'),
        ('share:E+G', '26.4', 1, 'l.351'),
    ],
    'CQA': [
        ('rows_csv', '545', 0, 'the 545-query re-run; the 549-query filtered set is described in Sect. 6.2'),
        ('n', '545', 0, 'l.610, l.620, Table 3 header, l.881'),
        ('strict', '471', 0, 'Table 3, Sect. 6.2'), ('strict_pct', '86.4', 1, 'Sect. 6.2, Conclusion'),
        ('failing', '69', 0, 'l.612, Table 3'), ('recovered', '22', 0, 'l.612, Table 3/4, l.660, l.762'),
        ('not_recovered', '47', 0, 'Table 3'), ('full', '493', 0, 'Table 3, Sect. 6.2'),
        ('full_pct', '90.5', 1, 'Sect. 6.2, Conclusion'), ('rate', '31.88', 2, 'Table 3, Sect. 6.2'),
        ('f1_recovered', '0.477', 3, 'Table 3, Sect. 6.2'),
        ('f1_initial', '0.676', 3, 'Sect. 6.2'), ('f1_final', '0.696', 3, 'Sect. 6.2'),
        ('f1_strict', '0.783', 3, 'Sect. 6.2'),
        ('p_initial', '74.1', 1, 'Sect. 6.2'), ('p_final', '76.8', 1, 'Sect. 6.2'),
        ('r_initial', '73.1', 1, 'Sect. 6.2'), ('r_final', '75.1', 1, 'Sect. 6.2'),
        ('phase_n:L1', '19', 0, 'Table 3'), ('phase_f1:L1', '0.454', 3, 'Table 3'),
        ('phase_n:L2', '0', 0, 'Table 4, l.664'), ('phase_f1:L2', '--', 3, 'Table 4'),
        ('phase_n:L3', '2', 0, 'Table 4, l.663'), ('phase_f1:L3', '0.691', 3, 'Table 4, l.663'),
        ('phase_n:L4a', '1', 0, 'Table 4, l.664'), ('phase_f1:L4a', '0.482', 3, 'Table 4'),
        ('phase_n:L4b+L5', '0', 0, 'Table 4'), ('phase_f1:L4b+L5', '--', 3, 'Table 4'),
        ('phase_total', '22', 0, 'Table 4 Total'),
        ('share:L1', '86.4', 1, 'l.660, l.770'),
        ('cause:0', '86.4', 1, 'l.763'), ('cause:1', '9.1', 1, 'l.764'), ('cause:2', '4.5', 1, 'l.764'),
        ('example_l1_title_f1', '0.838', 3, 'l.441-442'),
    ],
    'Manual': [
        ('n', '90', 0, 'l.576, Table 3 header, l.883'),
        ('strict', '2', 0, 'l.579-580, l.627, Table 3'), ('strict_pct', '2.2', 1, 'l.628'),
        ('failing', '88', 0, 'l.630, Table 3'), ('recovered', '80', 0, 'l.630-631, Table 3/4, l.667, l.764'),
        ('not_recovered', '8', 0, 'Table 3'), ('full', '82', 0, 'l.629, Table 3'),
        ('full_pct', '91.1', 1, 'l.629'), ('rate', '90.91', 2, 'l.630, Table 3, l.884'),
        ('f1_recovered', '0.776', 3, 'l.631, Table 3, l.885'),
        ('phase_n:L1', '42', 0, 'Table 4, l.667-668'), ('phase_f1:L1', '0.747', 3, 'Table 4, l.668'),
        ('phase_n:L2', '32', 0, 'Table 4, l.668'), ('phase_f1:L2', '0.907', 3, 'Table 4, l.669, l.791'),
        ('phase_n:L3', '5', 0, 'Table 4, l.673'), ('phase_f1:L3', '0.154', 3, 'Table 4, l.673, l.796, l.896'),
        ('phase_n:L4a', '1', 0, 'Table 4'), ('phase_f1:L4a', '0.891', 3, 'Table 4'),
        ('phase_n:L4b+L5', '0', 0, 'Table 4'), ('phase_f1:L4b+L5', '--', 3, 'Table 4'),
        ('phase_total', '80', 0, 'Table 4 Total'),
        ('share:L1', '52.5', 1, 'l.667'), ('share:L2', '40.0', 1, 'l.668'),
        ('cause:0', '52.5', 1, 'l.765'), ('cause:1', '46.25', 2, 'l.765'), ('cause:2', '1.25', 2, 'l.765'),
    ],
}


def run_checks(results):
    """results: dict section -> metrics. Returns (n_pass, n_fail)."""
    print('\n== --check-paper: computed vs. main.tex at printed precision ==')
    n_pass = n_fail = 0
    for section, checks in PAPER.items():
        if section not in results:
            print('  [skip] %s: input not given (%d checks skipped)' % (section, len(checks)))
            continue
        m = results[section]
        for key, printed, dec, where in checks:
            val = m.get(key)
            got = rnd(val, dec)
            if printed == '--':
                ok = val is None
            else:
                ok = val is not None and Decimal(got) == Decimal(printed)
            n_pass += ok
            n_fail += not ok
            raw = '' if val is None else (' raw=%.6g' % val)
            print('  [%s] %-9s %-22s paper=%-7s got=%-9s%s  (%s)'
                  % ('PASS' if ok else 'FAIL', section, key, printed, got, raw, where))
    print('  -> %d PASS, %d FAIL' % (n_pass, n_fail))
    return n_pass, n_fail


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


# --- added when this script was copied into the review artifact --------------
# Without any input argument, the frozen files shipped with the artifact are
# used (those that exist), so that `python reproduce_tables.py --check-paper`
# works as is.
ARTIFACT_DEFAULTS = [
    ('table1_csv', 'results/paper/table1/query_failure_classification_v3.csv'),
    ('cqa_csv', 'results/paper/exp1/full_pipeline_results.csv'),
    ('cqa_allowlist', 'data/populations/cqa_545.txt'),
    ('manual_csv', 'results/paper/manual90/relaxation_query_results.csv'),
]


def apply_artifact_defaults(args):
    """Fill the inputs from ARTIFACT_DEFAULTS when no input argument was given."""
    if any(getattr(args, a, None) for a in ('table1_csv', 'cqa_csv', 'manual_csv',
                                            'exp2_ai_csv', 'exp2_web_csv')):
        return
    root = os.path.dirname(os.path.abspath(__file__))
    used = 0
    for attr, rel in ARTIFACT_DEFAULTS:
        if attr == 'cqa_allowlist' and (args.cqa_allowlist or not args.cqa_csv):
            continue
        path = os.path.join(root, *rel.split('/'))
        if not os.path.isfile(path):
            continue
        try:
            path = os.path.relpath(path)
        except ValueError:  # path on another drive (Windows)
            pass
        setattr(args, attr, path)
        used += 1
    if used:
        print('No input argument given: using the frozen files shipped with the artifact.')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cqa-csv', help='Experiment 1 CQA per-query CSV (full_pipeline_results.csv)')
    ap.add_argument('--cqa-allowlist', help='pair_name,query_file allowlist restricting the CQA population')
    ap.add_argument('--manual-csv', help='Experiment 1 manual-90 CSV (relaxation_query_results.csv)')
    ap.add_argument('--table1-csv', help='Table 1 classification CSV (query_failure_classification_v3.csv)')
    ap.add_argument('--check-paper', action='store_true',
                    help='assert equality with the values printed in the current main.tex; exit 1 on any mismatch')
    args = ap.parse_args(argv)
    apply_artifact_defaults(args)
    try:
        sys.stdout.reconfigure(errors='replace')
    except AttributeError:
        pass
    _raise_csv_limit()

    inputs = [('table1-csv', args.table1_csv), ('cqa-csv', args.cqa_csv),
              ('cqa-allowlist', args.cqa_allowlist), ('manual-csv', args.manual_csv)]
    if not any(p for name, p in inputs if name != 'cqa-allowlist'):
        ap.print_usage()
        print('nothing to do: give at least one of --table1-csv, --cqa-csv, --manual-csv')
        return 2
    print('== Inputs ==')
    for name, path in inputs:
        print('  %-14s %s' % (name, ('%s  [sha256 %s]' % (path, sha256_16(path))) if path else '(not given, skipped)'))
    if args.cqa_allowlist and not args.cqa_csv:
        print('  WARNING --cqa-allowlist given without --cqa-csv; ignored')

    results, settings = {}, []
    if args.table1_csv:
        m, diag = analyse_table1(args.table1_csv)
        results['Table1'] = m
        print_table1(m, diag)
    diags = []
    if args.cqa_csv:
        m, diag = analyse_cqa(args.cqa_csv, args.cqa_allowlist)
        results['CQA'] = m
        settings.append(('CQA', m, True))
        diags.append(('CQA', diag))
    if args.manual_csv:
        m, diag = analyse_manual(args.manual_csv)
        results['Manual'] = m
        settings.append(('Manual', m, True))
        diags.append(('Manual', diag))

    if settings:
        print_table3(settings)
        print_table4(settings)
    if settings:
        print_text_numbers(settings)
        print('\n== Population construction and definition cross-checks ==')
        for lab, diag in diags:
            for d in diag:
                print('  %s: %s' % (lab, d))

    if args.check_paper:
        _, n_fail = run_checks(results)
        return 1 if n_fail else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
