# Random test generator for `dojo stress`: prints ONE test. dojo runs it as `gen.py <seed>`,
# so the same seed always gives the same test. Bugs hide in small cases: keep n tiny and
# values small, so edges like n = 1 or all-equal values come up often.
from dojo.gen import *

seed_from_argv()

t = 1                       # one test case per input: the failing input stays short
out(t)
for _ in range(t):
    n = rint(1, 8)
    a = rarray(n, 1, 10)
    out(n, a)

# More helpers: perm(n), distinct(n, lo, hi), rstring(n, "ab"), tree_edges(n),
# graph_edges(n, m, connected=True), choice(seq), chance(0.2)
