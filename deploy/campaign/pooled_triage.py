"""Pool the M1 triage figure across campaigns, from close-out's own rows.

Each campaign's close-out persists its perturbation-stability AUC and its side
counts to ``closeout_triage``. No node id or label is stored, so pooling never
touches the sidecar. Pairs are only compared within a campaign, so the pooled
figure is the stratified (van Elteren-style) AUC:

    AUC_pooled = sum(U_i) / sum(n_null_i * n_real_i),   U_i = AUC_i * n_null_i * n_real_i

Usage: python -I deploy/campaign/pooled_triage.py [DATABASE_PATH] [CAMPAIGN_ID ...]
With no campaign ids, every campaign with a non-null AUC is pooled.
"""

import os
import sqlite3
import sys

path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/.local/share/nullius/research.db"
)
wanted = set(sys.argv[2:])
connection = sqlite3.connect(path)
rows = connection.execute(
    "SELECT campaign_id, auc, null_count, real_count FROM closeout_triage "
    "WHERE auc IS NOT NULL ORDER BY campaign_id"
).fetchall()
rows = [row for row in rows if not wanted or row[0] in wanted]
if not rows:
    sys.exit("no campaign has a triage figure yet")
u_total = sum(auc * n0 * n1 for _, auc, n0, n1 in rows)
pairs = sum(n0 * n1 for _, _, n0, n1 in rows)
for campaign, auc, n0, n1 in rows:
    print(f"{campaign}  auc {auc:.3f}  nulls {n0}  reals {n1}")
print(
    f"pooled over {len(rows)} campaign(s): AUC {u_total / pairs:.3f}, "
    f"nulls {sum(r[2] for r in rows)}, reals {sum(r[3] for r in rows)}, pairs {pairs}"
)
