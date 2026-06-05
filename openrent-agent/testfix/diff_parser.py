"""
diff_parser.py -- SQL diff hunk classifier for diff_kind_match feature.

Classifies a unified diff hunk into one of:
  agg        -- aggregate function (SUM/MIN/MAX/COUNT/AVG/...) on changed line
  join       -- JOIN condition change: JOIN keyword in hunk + comparison op changed
  arithmetic -- arithmetic expression change (+/-/*//) on changed line
  filter     -- WHERE/HAVING predicate change
  unknown    -- none of the above

Priority: agg > join > arithmetic > filter > unknown.

Design notes:
  - Agg and arithmetic are detected on CHANGED lines only (strong local signal).
  - Join is detected via JOIN keyword in the FULL hunk (context + changed), because
    SQL style often puts "left join table" on one line and the ON clause on the next;
    the mutation changes the ON clause line, which doesn't contain "join" itself.
  - The parser deliberately uses full-hunk context for join to handle this pattern.
"""

import re
from typing import Tuple

# ---- regex patterns ----

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

# ON keyword as a standalone word — matches "on " in join conditions
_ON_RE = re.compile(r'\bON\b', re.IGNORECASE)

# Any comparison operator: !=, <>, <=, >=, plain = (not preceded by !, <, >), <, >
_COND_RE = re.compile(r'!=|<>|<=|>=|(?<![!<>])=(?!=)|(?<!=)<(?![>=])|(?<!<)>(?![=])')

# Arithmetic: an expression with +/-/*/% between identifiers/numbers
# Excludes * in COUNT(*), +/- in string context
_ARITH_RE = re.compile(r'[\w\)]\s*[+\-*/]\s*[\w\(]')

_FILTER_RE = re.compile(r'\b(WHERE|HAVING)\b', re.IGNORECASE)


# ---- hunk splitting ----

def _split_hunk(hunk: str) -> Tuple[str, str]:
    """
    Returns (changed_text, full_text) where:
    - changed_text: only lines starting with + or - (not +++ / ---)
    - full_text: all content lines (strip the +/-/space prefix)
    """
    changed, full = [], []
    for line in hunk.splitlines():
        if line.startswith(('+++', '---', '@@')):
            continue
        content = line[1:] if line and line[0] in '+-' else line
        full.append(content)
        if line and line[0] in '+-':
            changed.append(content)
    return '\n'.join(changed), '\n'.join(full)


# ---- classifier ----

def classify_diff_kind(hunk: str) -> str:
    """
    Classify a SQL diff hunk.

    Priority: agg > join > arithmetic > filter > unknown.

    Args:
        hunk: unified diff hunk (may include @@ header and context lines).
              Can also be a raw snippet of SQL if the diff is not available.

    Returns:
        One of: 'agg', 'join', 'arithmetic', 'filter', 'unknown'
    """
    changed, full = _split_hunk(hunk)

    # 1. Agg: aggregate function on changed line (strong, local)
    if _AGG_RE.search(changed):
        return 'agg'

    # 2. Join: JOIN keyword anywhere in hunk (context may carry it) AND
    #           a comparison change on the changed lines.
    #           Also: ON keyword on the changed line + comparison change.
    has_join = _JOIN_RE.search(full)
    has_on   = _ON_RE.search(changed)
    has_cond = _COND_RE.search(changed)
    if has_cond and (has_join or has_on):
        return 'join'

    # 3. Arithmetic: +/-/*/% between identifiers on changed line
    if _ARITH_RE.search(changed):
        return 'arithmetic'

    # 4. Filter: WHERE / HAVING on changed line
    if _FILTER_RE.search(changed):
        return 'filter'

    return 'unknown'


# ---- validation ----

# Synthetic diff hunks for jaffle_shop_duckdb mutations.
# Constructed from the actual model SQL; represent what `git diff -U2` would produce.
# Used to validate the parser and to run Phase 2b without requiring a live git repo.
#
# Key design note: join ON clauses often appear on a separate line from the JOIN
# keyword. The hunk therefore includes 2 lines of context so the JOIN keyword is
# present for the parser.  The changed line contains only the condition expression.

JAFFLE_DIFFS = {
    # customers.sql aggregates (lines 24-26, 37)
    "d_c01": """\
@@ -22,6 +22,6 @@
         customer_id,

-        min(order_date) as first_order,
+        min(order_date + 1) as first_order,
         max(order_date) as most_recent_order,
""",
    "d_c02": """\
@@ -23,6 +23,6 @@
         min(order_date) as first_order,
-        max(order_date) as most_recent_order,
+        max(order_date + 1) as most_recent_order,
         count(order_id) as number_of_orders
""",
    "d_c03": """\
@@ -24,5 +24,5 @@
         max(order_date) as most_recent_order,
-        count(order_id) as number_of_orders
+        count(order_id + 1) as number_of_orders
     from orders
""",
    # customers.sql: sum in customer_payments CTE (line 37)
    "d_c04": """\
@@ -35,5 +35,5 @@
     select
         orders.customer_id,
-        sum(amount) as total_amount
+        sum(amount + 1) as total_amount

     from payments
""",
    # customers.sql: inner join in customer_payments CTE (lines 41-42)
    # JOIN keyword is on line 41 (context); ON clause is on line 42 (changed)
    "d_c05": """\
@@ -39,6 +39,6 @@

     from payments

     left join orders on
-         payments.order_id = orders.order_id
+         payments.order_id != orders.order_id

""",
    # customers.sql: outer join to customer_orders (lines 61-62)
    # Changed line 62 starts with "on"; JOIN is on line 61 (context)
    "d003": """\
@@ -59,6 +59,6 @@

     from customers

-    left join customer_orders
-        on customers.customer_id = customer_orders.customer_id
+    left join customer_orders
+        on customers.customer_id != customer_orders.customer_id

""",
    # customers.sql: outer join to customer_payments (lines 64-65)
    # Changed line 65 starts with "on"; JOIN is on line 64 (context)
    "d001": """\
@@ -62,6 +62,6 @@

-    left join customer_payments
-        on  customers.customer_id = customer_payments.customer_id
+    left join customer_payments
+        on  customers.customer_id != customer_payments.customer_id

 )
""",
    # orders.sql: CASE WHEN inside SUM (line 21, Jinja template)
    "d_o01": """\
@@ -19,5 +19,5 @@
         order_id,

-        sum(case when payment_method = '{{ payment_method }}' then amount else 0 end) as {{ payment_method }}_amount,
+        sum(case when payment_method != '{{ payment_method }}' then amount else 0 end) as {{ payment_method }}_amount,
         sum(amount) as total_amount
""",
    # orders.sql: sum(amount) as total_amount (line 24)
    "d_o02": """\
@@ -22,5 +22,5 @@
         {%- endfor %}

-        sum(amount) as total_amount
+        sum(amount + 1) as total_amount

     from payments
""",
    # orders.sql: join to order_payments (lines 51-52)
    "d002": """\
@@ -49,6 +49,6 @@
     from orders

-    left join order_payments
-        on orders.order_id = order_payments.order_id
+    left join order_payments
+        on orders.order_id != order_payments.order_id

 )
""",
    # stg_payments.sql: amount / 100 (line 19)
    "d_s01": """\
@@ -17,5 +17,5 @@
         payment_id,
         order_id,
         payment_method,
-        amount / 100 as amount
+        amount / 10 as amount

""",
}

# Expected classifications for validation
_EXPECTED = {
    "d_c01": "agg",  "d_c02": "agg",  "d_c03": "agg",
    "d_c04": "agg",  "d_c05": "join",
    "d003":  "join", "d001":  "join", "d002":  "join",
    "d_o01": "agg",  "d_o02": "agg",  "d_s01": "arithmetic",
}


def validate(verbose: bool = True) -> bool:
    """Run parser against JAFFLE_DIFFS and check against expected kinds."""
    ok = True
    for case_id, hunk in JAFFLE_DIFFS.items():
        got      = classify_diff_kind(hunk)
        expected = _EXPECTED[case_id]
        status   = "OK" if got == expected else "FAIL"
        if verbose or got != expected:
            print(f"  {case_id:<8} expected={expected:<12} got={got:<12} {status}")
        if got != expected:
            ok = False
    return ok


if __name__ == "__main__":
    print("diff_parser validation (jaffle_shop_duckdb mutations):")
    passed = validate(verbose=True)
    print(f"\n{'ALL PASS' if passed else 'FAILURES FOUND'}")
