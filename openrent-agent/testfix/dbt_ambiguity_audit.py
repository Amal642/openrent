"""
dbt_ambiguity_audit.py -- Transfer-validity pre-screen for diff_kind_match.

Given a dbt project directory, reports:
  1. Candidate expressions per model (agg / join / arithmetic / filter)
  2. Which output columns each expression feeds (via CTE dependency tracing)
  3. Same-context-key ambiguous pairs (multiple candidates → same output cols)
  4. For each ambiguous group: is it mixed-diff_kind (diagnostic) or
     same-diff_kind (non-diagnostic for diff_kind_match)?

Transfer validity conditions (from PHASE2B-precommit.md):
  - VALID   : target has ≥1 ambiguous pair with mixed diff_kind
  - PARTIAL : ambiguous pairs exist but all share the same diff_kind
               → diff_kind_match expected decorative; target non-diagnostic
  - THIN    : no ambiguous pairs → diff_kind_match irrelevant

Usage:
    python dbt_ambiguity_audit.py <path_to_dbt_project>
    python dbt_ambiguity_audit.py                         # uses jaffle_shop_duckdb
"""

import re
import sys
import json
import pathlib
from typing import Dict, List, Set, Tuple, Optional

# ---- regex patterns (shared with diff_parser.py logic) ----

_AGG_RE = re.compile(
    r'\b(SUM|MIN|MAX|COUNT|AVG|STDDEV|STDDEV_POP|STDDEV_SAMP|VAR_POP|VAR_SAMP|'
    r'VARIANCE|MEDIAN|PERCENTILE_CONT|PERCENTILE_DISC|LISTAGG|STRING_AGG|'
    r'ARRAY_AGG|JSON_AGG|BOOL_AND|BOOL_OR|BIT_AND|BIT_OR|BIT_XOR)\s*\(',
    re.IGNORECASE,
)

_JOIN_RE = re.compile(
    r'\b(INNER\s+JOIN|LEFT\s+(?:OUTER\s+)?JOIN|RIGHT\s+(?:OUTER\s+)?JOIN|'
    r'FULL\s+(?:OUTER\s+)?JOIN|CROSS\s+JOIN|NATURAL\s+JOIN|JOIN)\b',
    re.IGNORECASE,
)

_ON_RE      = re.compile(r'\bON\b', re.IGNORECASE)
_COND_RE    = re.compile(r'!=|<>|<=|>=|(?<![!<>])=(?!=)|(?<!=)<(?![>=])|(?<!<)>(?![=])')
_ARITH_RE   = re.compile(r'[\w\)]\s*[+\-*/]\s*[\w\(]')
_FILTER_RE  = re.compile(r'\b(WHERE|HAVING)\b', re.IGNORECASE)
_ALIAS_RE   = re.compile(r'\bAS\s+(\w+)\s*$', re.IGNORECASE)
_JINJA_RE   = re.compile(r'\{\{.*?\}\}|\{%-?.*?-?%\}', re.DOTALL)


# ---- SQL pre-processing ----

def _strip_jinja(sql: str) -> str:
    """Replace Jinja blocks with a placeholder token so regex sees valid SQL."""
    return _JINJA_RE.sub('__JINJA__', sql)


def _strip_comments(sql: str) -> str:
    sql = re.sub(r'--[^\n]*', ' ', sql)
    sql = re.sub(r'/\*.*?\*/', ' ', sql, flags=re.DOTALL)
    return sql


def _normalise(sql: str) -> str:
    return _strip_jinja(_strip_comments(sql))


# ---- CTE extraction ----

def _extract_ctes(sql: str) -> Dict[str, str]:
    """
    Return {cte_name: cte_body} for all CTEs defined in a WITH clause.
    Handles nested parentheses (enough for typical dbt models).
    """
    ctes: Dict[str, str] = {}
    # Find 'name AS ('
    pattern = re.compile(r'\b(\w+)\s+AS\s*\(', re.IGNORECASE)
    for m in pattern.finditer(sql):
        name  = m.group(1).lower()
        start = m.end()          # position after '('
        depth = 1
        pos   = start
        while pos < len(sql) and depth > 0:
            if sql[pos] == '(':
                depth += 1
            elif sql[pos] == ')':
                depth -= 1
            pos += 1
        ctes[name] = sql[start : pos - 1]
    return ctes


def _final_select(sql: str) -> str:
    """Return the last SELECT statement (the model's final output)."""
    # Strip WITH block if present
    norm = sql.strip()
    # Find all top-level SELECT positions
    selects = [m.start() for m in re.finditer(r'\bSELECT\b', norm, re.IGNORECASE)]
    if not selects:
        return ""
    return norm[selects[-1]:]


# ---- expression classification ----

def _classify_expr(expr: str) -> str:
    """Classify a SELECT expression into agg / join / arithmetic / filter / plain."""
    if _AGG_RE.search(expr):
        return "agg"
    if _ARITH_RE.search(expr):
        return "arithmetic"
    if _FILTER_RE.search(expr):
        return "filter"
    return "plain"


def _classify_cte(body: str) -> Tuple[bool, bool]:
    """
    Return (has_agg, has_join) for a CTE body.
    has_agg  : at least one aggregate function in SELECT
    has_join : at least one JOIN keyword
    """
    has_join = bool(_JOIN_RE.search(body))
    # Check SELECT columns for aggregates
    sel_match = re.search(r'\bSELECT\b(.*?)(?:\bFROM\b|\Z)', body,
                          re.IGNORECASE | re.DOTALL)
    has_agg = bool(_AGG_RE.search(sel_match.group(1) if sel_match else body))
    return has_agg, has_join


# ---- column extraction ----

def _select_aliases(select_clause: str) -> List[Tuple[str, str]]:
    """
    Extract (alias, expression) pairs from a SELECT clause.
    Returns only columns that have an explicit alias.
    """
    pairs = []
    # Split on commas at depth 0
    parts = _split_select(select_clause)
    for part in parts:
        part = part.strip()
        alias_m = re.search(r'\bAS\s+(\w+)\s*$', part, re.IGNORECASE)
        if alias_m:
            alias = alias_m.group(1).lower()
            pairs.append((alias, part))
    return pairs


def _split_select(clause: str) -> List[str]:
    """Split a SELECT column list on commas, respecting parentheses."""
    parts, current, depth = [], [], 0
    for ch in clause:
        if ch == '(':
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append(''.join(current))
    return parts


# ---- join condition extraction ----

def _cte_join_candidates(cte_name: str, body: str) -> List[Dict]:
    """
    For a CTE that contains JOINs, return one candidate per JOIN condition.
    The candidate represents "mutate the ON condition of this join".
    """
    candidates = []
    # Find JOIN...ON patterns
    join_re = re.compile(
        r'\b((?:INNER|LEFT|RIGHT|FULL|CROSS|NATURAL)?\s*(?:OUTER\s+)?JOIN\s+(\w+)(?:\s+\w+)?'
        r'\s+ON\b)(.*?)(?=\b(?:INNER|LEFT|RIGHT|FULL|CROSS|NATURAL|JOIN|WHERE|GROUP|HAVING|'
        r'ORDER|LIMIT|UNION|SELECT)\b|\Z)',
        re.IGNORECASE | re.DOTALL,
    )
    for i, m in enumerate(join_re.finditer(body)):
        joined_table = (m.group(2) or "unknown").lower()
        candidates.append({
            "expr_id"    : f"{cte_name}_join_{i}_{joined_table}",
            "kind"       : "join",
            "cte"        : cte_name,
            "snippet"    : m.group(0)[:80].replace('\n', ' ').strip(),
        })
    return candidates


def _cte_agg_candidates(cte_name: str, body: str,
                         final_cols: Set[str]) -> List[Dict]:
    """
    For a CTE that contains aggregate functions, return one candidate per
    aggregate column in the SELECT list.
    """
    candidates = []
    sel_match = re.search(r'\bSELECT\b(.*?)(?:\bFROM\b|\Z)', body,
                          re.IGNORECASE | re.DOTALL)
    if not sel_match:
        return candidates
    for alias, expr in _select_aliases(sel_match.group(1)):
        if _AGG_RE.search(expr):
            candidates.append({
                "expr_id"    : f"{cte_name}_{alias}",
                "kind"       : "agg",
                "cte"        : cte_name,
                "alias"      : alias,
                "snippet"    : expr[:80].replace('\n', ' ').strip(),
            })
    return candidates


def _cte_arith_candidates(cte_name: str, body: str) -> List[Dict]:
    """Arithmetic expressions in SELECT columns."""
    candidates = []
    sel_match = re.search(r'\bSELECT\b(.*?)(?:\bFROM\b|\Z)', body,
                          re.IGNORECASE | re.DOTALL)
    if not sel_match:
        return candidates
    for alias, expr in _select_aliases(sel_match.group(1)):
        if _ARITH_RE.search(expr) and not _AGG_RE.search(expr):
            candidates.append({
                "expr_id"    : f"{cte_name}_{alias}_arith",
                "kind"       : "arithmetic",
                "cte"        : cte_name,
                "alias"      : alias,
                "snippet"    : expr[:80].replace('\n', ' ').strip(),
            })
    return candidates


# ---- CTE dependency tracing ----

def _cte_output_cols(body: str) -> Set[str]:
    """Return the set of output column aliases for a CTE."""
    sel_match = re.search(r'\bSELECT\b(.*?)(?:\bFROM\b|\Z)', body,
                          re.IGNORECASE | re.DOTALL)
    if not sel_match:
        return set()
    aliases = {a for a, _ in _select_aliases(sel_match.group(1))}
    if re.search(r'\bSELECT\s+\*', body, re.IGNORECASE):
        aliases.add("*")
    return aliases


def _which_ctes_feed_col(
    col: str,
    final_sel: str,
    ctes: Dict[str, str],
    cte_outputs: Dict[str, Set[str]],
) -> Set[str]:
    """
    Return the set of CTE names that contribute to a given final output column.
    Strategy: check if any CTE output alias matches the column name (or passes
    through a join).  Transitive: if CTE B references CTE A, A's influence on B
    is included.
    """
    contributing: Set[str] = set()
    # Direct: does any CTE export this column name?
    for cte_name, outputs in cte_outputs.items():
        if col in outputs or "*" in outputs:
            contributing.add(cte_name)
    # Indirect via joins: if a CTE's join references another CTE, that other
    # CTE's columns can flow through.  We do one-hop tracing only.
    transitive: Set[str] = set()
    for cte_name in list(contributing):
        body = ctes[cte_name]
        for other in cte_outputs:
            if other != cte_name and re.search(r'\b' + re.escape(other) + r'\b',
                                               body, re.IGNORECASE):
                transitive.add(other)
    return contributing | transitive


# ---- model-level analysis ----

def analyse_model(sql_path: pathlib.Path, project_root: pathlib.Path) -> Dict:
    """
    Analyse one dbt model SQL file.
    Returns a dict with:
      - model_rel       : relative path string (as context-key prefix)
      - candidates      : list of candidate dicts {expr_id, kind, feeds_cols, ...}
      - ambiguous_groups: groups with >1 candidate sharing same output-col set
      - has_mixed       : True if any ambiguous group has mixed diff_kind
    """
    rel  = sql_path.relative_to(project_root).as_posix()
    raw  = sql_path.read_text(encoding="utf-8", errors="replace")
    norm = _normalise(raw)

    ctes = _extract_ctes(norm)
    cte_outputs = {name: _cte_output_cols(body) for name, body in ctes.items()}
    final_sel   = _final_select(norm)

    # Collect all final output columns from the model
    final_sel_body = re.search(r'\bSELECT\b(.*?)(?:\bFROM\b|\Z)',
                               final_sel, re.IGNORECASE | re.DOTALL)
    final_aliases: Set[str] = set()
    if final_sel_body:
        final_aliases = {a for a, _ in _select_aliases(final_sel_body.group(1))}
    if re.search(r'\bSELECT\s+\*', final_sel, re.IGNORECASE):
        # SELECT * — all CTE outputs pass through
        for outs in cte_outputs.values():
            final_aliases |= outs

    # For each CTE, extract candidates
    all_candidates: List[Dict] = []
    for cte_name, body in ctes.items():
        has_agg, has_join = _classify_cte(body)
        if has_join:
            all_candidates.extend(_cte_join_candidates(cte_name, body))
        if has_agg:
            all_candidates.extend(_cte_agg_candidates(cte_name, body, final_aliases))
        all_candidates.extend(_cte_arith_candidates(cte_name, body))

    # Also look for joins in the final SELECT
    if _JOIN_RE.search(final_sel):
        all_candidates.extend(_cte_join_candidates("__final__", final_sel))

    # Assign feeds_cols: which final output columns does this candidate influence?
    # Heuristic: for agg candidates, the CTE alias flows → match by alias name.
    # For join candidates, the joined CTE's outputs flow into the parent.
    for cand in all_candidates:
        cte_name   = cand["cte"]
        cand_alias = cand.get("alias", "")
        feeds: Set[str] = set()

        if cand["kind"] == "agg":
            # Does this alias appear in the final model's output?
            if cand_alias in final_aliases:
                feeds.add(cand_alias)
            # Or does it flow through a parent CTE?
            for other_name, other_body in ctes.items():
                if other_name == cte_name:
                    continue
                if re.search(r'\b' + re.escape(cte_name) + r'\b',
                             other_body, re.IGNORECASE):
                    # This CTE uses cte_name; the alias might flow through
                    for fa in final_aliases:
                        if fa == cand_alias or re.search(
                                r'\b' + re.escape(cand_alias) + r'\b',
                                other_body, re.IGNORECASE):
                            feeds.add(fa)

        elif cand["kind"] == "join":
            # The joined table's columns flow into the parent CTE and onwards
            joined = cand["expr_id"].split("_join_")[-1]  # last segment = table
            # Find outputs of the joined CTE (if it's a CTE, not a raw table)
            joined_cte_name = next(
                (c for c in ctes if c.lower() == joined.lower()), None)
            if joined_cte_name:
                # Columns from the joined CTE that appear in final_aliases
                for out_col in cte_outputs.get(joined_cte_name, set()):
                    if out_col in final_aliases:
                        feeds.add(out_col)
            else:
                # External/staging table: any output column from this CTE/final
                feeds = set(final_aliases)

        elif cand["kind"] == "arithmetic":
            if cand_alias in final_aliases:
                feeds.add(cand_alias)
            else:
                feeds = set(final_aliases)

        if not feeds:
            feeds = set(final_aliases) or {"__unknown__"}
        cand["feeds_cols"] = frozenset(feeds)

    # Group candidates by feeds_cols → context key
    groups: Dict[frozenset, List[Dict]] = {}
    for cand in all_candidates:
        key = cand["feeds_cols"]
        groups.setdefault(key, []).append(cand)

    ambiguous_groups = {k: v for k, v in groups.items() if len(v) > 1}

    # Check for mixed diff_kind in each ambiguous group
    has_mixed = False
    mixed_groups = []
    for cols, group in ambiguous_groups.items():
        kinds = {c["kind"] for c in group}
        is_mixed = len(kinds) > 1 and \
                   (("agg" in kinds and "join" in kinds) or
                    ("agg" in kinds and "arithmetic" in kinds) or
                    ("join" in kinds and "arithmetic" in kinds))
        if is_mixed:
            has_mixed = True
        mixed_groups.append({
            "output_cols"  : sorted(cols),
            "candidates"   : [{k: v for k, v in c.items()
                               if k != "feeds_cols"} for c in group],
            "kinds_present": sorted(kinds),
            "is_mixed"     : is_mixed,
        })

    return {
        "model_rel"        : rel,
        "n_candidates"     : len(all_candidates),
        "n_ctes"           : len(ctes),
        "cte_names"        : sorted(ctes.keys()),
        "final_cols"       : sorted(final_aliases),
        "ambiguous_groups" : mixed_groups,
        "has_mixed"        : has_mixed,
    }


# ---- project-level analysis ----

def audit_project(project_root: pathlib.Path) -> Dict:
    """
    Walk all .sql files under <project_root>/models/ and run analyse_model.
    Returns an audit report dict.
    """
    models_dir = project_root / "models"
    if not models_dir.exists():
        models_dir = project_root  # fallback: treat root as models dir

    sql_files = list(models_dir.rglob("*.sql"))
    sql_files.sort()

    model_results = []
    for f in sql_files:
        try:
            result = analyse_model(f, project_root)
            model_results.append(result)
        except Exception as e:
            model_results.append({
                "model_rel": f.relative_to(project_root).as_posix(),
                "error": str(e),
            })

    total_ambiguous  = sum(len(r.get("ambiguous_groups", [])) for r in model_results)
    total_mixed      = sum(1 for r in model_results if r.get("has_mixed", False))
    total_candidates = sum(r.get("n_candidates", 0) for r in model_results)

    # Transfer validity verdict
    if total_mixed >= 1:
        validity = "VALID"
        validity_reason = (
            f"{total_mixed} model(s) have >=1 ambiguous pair with mixed diff_kind "
            f"-- diff_kind_match is diagnostic for this target."
        )
    elif total_ambiguous > 0:
        validity = "PARTIAL"
        validity_reason = (
            f"{total_ambiguous} ambiguous group(s) found but all share the same diff_kind "
            f"-- diff_kind_match expected decorative; target non-diagnostic."
        )
    else:
        validity = "THIN"
        validity_reason = (
            "No ambiguous pairs found -- diff_kind_match irrelevant; "
            "all mutations unambiguously identifiable by structural features alone."
        )

    return {
        "project_root"   : str(project_root),
        "n_models"       : len(sql_files),
        "total_candidates": total_candidates,
        "total_ambiguous_groups": total_ambiguous,
        "models_with_mixed": total_mixed,
        "transfer_validity": validity,
        "validity_reason"  : validity_reason,
        "models"           : model_results,
    }


# ---- reporting ----

def print_report(report: Dict) -> None:
    print(f"\n{'='*72}")
    print(f"dbt Ambiguity Audit: {report['project_root']}")
    print(f"{'='*72}")
    print(f"  Models scanned     : {report['n_models']}")
    print(f"  Total candidates   : {report['total_candidates']}")
    print(f"  Ambiguous groups   : {report['total_ambiguous_groups']}")
    print(f"  Models with mixed  : {report['models_with_mixed']}")
    print(f"\nTransfer validity: {report['transfer_validity']}")
    validity_reason = report['validity_reason'].encode('ascii', errors='replace').decode('ascii')
    print(f"  {validity_reason}")

    for m in report["models"]:
        if "error" in m:
            print(f"\n  [{m['model_rel']}] ERROR: {m['error']}")
            continue
        if not m["ambiguous_groups"] and m["n_candidates"] == 0:
            continue
        print(f"\n  [{m['model_rel']}]  "
              f"ctes={m['n_ctes']}  candidates={m['n_candidates']}  "
              f"final_cols={m['final_cols']}")
        if m["ambiguous_groups"]:
            for g in m["ambiguous_groups"]:
                tag = "MIXED -- diagnostic" if g["is_mixed"] else "same-kind"
                print(f"    ambiguous group [{tag}] cols={g['output_cols']}")
                for c in g["candidates"]:
                    print(f"      {c['expr_id']:<40} kind={c['kind']:<12} "
                          f"snippet={c.get('snippet','')[:50]}")
        else:
            print(f"    (no ambiguous groups)")

    print(f"\n{'='*72}\n")


# ---- entry point ----

if __name__ == "__main__":
    if len(sys.argv) > 1:
        root = pathlib.Path(sys.argv[1])
    else:
        # Default: jaffle_shop_duckdb training set (for self-check)
        root = pathlib.Path(r"D:\transfer-rung1\jaffle_shop_duckdb")

    if not root.exists():
        print(f"ERROR: {root} does not exist")
        sys.exit(1)

    report = audit_project(root)
    print_report(report)

    # Save report
    out = pathlib.Path(__file__).parent / "dbt_audit_results.json"
    # Convert frozensets for JSON serialisation
    def _serialise(obj):
        if isinstance(obj, frozenset):
            return sorted(obj)
        raise TypeError(f"Not serialisable: {type(obj)}")
    out.write_text(json.dumps(report, indent=2, default=_serialise), encoding="utf-8")
    print(f"Report saved: {out}")
