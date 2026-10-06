#!/bin/bash
# Hetzner -> Contabo cutover (2026-10-06). Runs ON THE OLD (Hetzner) server.
# DRY_RUN=1 bash cutover_contabo.sh   -> preflight only, changes nothing.
# Rolls back to Hetzner automatically if any post-switch check fails.
set -u
NEW=178.238.237.246
KEY=/root/.ssh/migrate_tmp
SSHN="ssh -i $KEY -o IdentitiesOnly=yes -o ConnectTimeout=20 -o BatchMode=yes root@$NEW"
RSYNC_E="ssh -i $KEY -o IdentitiesOnly=yes -o BatchMode=yes"
APP=/opt/openrent-agent/openrent-agent
SERVICES="cloudflared openrent-backend openrent-rq-worker openrent-alert-bot"
WORKERS=4
DRY=${DRY_RUN:-0}
LOG=/root/cutover_contabo.log
exec >>"$LOG" 2>&1
say() { echo "[$(date -u +%H:%M:%S)] $*"; }

running_workers() {
  cd "$APP" && timeout 30 env PYTHONPATH=. venv/bin/python -c "
from app.db.repository import session_scope
from app.db.models import Account
with session_scope() as s:
    print(s.query(Account).filter(Account.worker_status == 'running').count())" 2>/dev/null
}

rollback() {
  say "ROLLBACK: $1"
  $SSHN "for u in $SERVICES; do systemctl disable --now \$u; done; crontab -r 2>/dev/null; true"
  for u in $SERVICES; do systemctl enable --now "$u"; done
  [ -f /root/crontab_pre_cutover ] && crontab /root/crontab_pre_cutover
  sleep 15
  say "rollback state (hetzner): $(for u in $SERVICES; do echo -n "$u=$(systemctl is-active $u) "; done)"
  say "=== CUTOVER FAILED, HETZNER RESTORED"
  exit 1
}

say "=== cutover start (dry_run=$DRY)"

# ---- preflight -------------------------------------------------------------
$SSHN true || { say "ABORT: new server unreachable"; exit 1; }
$SSHN "test -x $APP/venv/bin/python && test -f /root/prod_crontab.txt && command -v cloudflared >/dev/null" \
  || { say "ABORT: new server not staged"; exit 1; }
rsync -a --dry-run --delete -e "$RSYNC_E" --exclude="openrent-agent/venv/" --exclude="openrent-agent/screenshots/" \
  --exclude="openrent-agent/logs/" --exclude="__pycache__/" --exclude=".venv/" /opt/openrent-agent/ root@$NEW:/opt/openrent-agent/ \
  || { say "ABORT: rsync dry-run failed"; exit 1; }
say "preflight OK; running workers now: $(running_workers)"
if [ "$DRY" = "1" ]; then say "=== DRY RUN done, nothing changed"; exit 0; fi

# ---- 1. wait for an idle fleet (outside 08:00-24:00 UK nothing new starts) -
for i in $(seq 1 90); do
  n=$(running_workers); [ "$n" = "0" ] && break
  say "waiting: $n worker(s) still running"; sleep 30
done
[ "$(running_workers)" = "0" ] || { say "ABORT: workers still running after 45 min; nothing changed"; exit 1; }

# ---- 2. stop the old server -----------------------------------------------
crontab -l > /root/crontab_pre_cutover 2>/dev/null
for u in $SERVICES; do systemctl stop "$u"; systemctl disable "$u"; done
crontab -r 2>/dev/null
say "hetzner stopped: $(for u in $SERVICES; do echo -n "$u=$(systemctl is-active $u) "; done)"

# ---- 3. final sync (sessions, .env, secrets, any code deployed today) -----
rsync -a --delete -e "$RSYNC_E" --exclude="openrent-agent/venv/" --exclude="openrent-agent/screenshots/" \
  --exclude="openrent-agent/logs/" --exclude="__pycache__/" --exclude=".venv/" /opt/openrent-agent/ root@$NEW:/opt/openrent-agent/ \
  || rollback "final rsync failed"
rsync -a -e "$RSYNC_E" /root/.cloudflared/ root@$NEW:/root/.cloudflared/ || rollback "cloudflared rsync failed"
say "final sync done"

# ---- 4. start the new server ----------------------------------------------
$SSHN "set -e
  sed -i 's/^MAX_PARALLEL_WORKERS=.*/MAX_PARALLEL_WORKERS=$WORKERS/' $APP/.env
  sed -i 's/MAX_PARALLEL_WORKERS=[0-9]*/MAX_PARALLEL_WORKERS=$WORKERS/' /etc/systemd/system/openrent-rq-worker.service.d/*.conf
  systemctl daemon-reload
  for u in $SERVICES; do systemctl enable --now \$u; done
  crontab /root/prod_crontab.txt" || rollback "starting services on new server failed"
say "new server services started"

# ---- 5. verify --------------------------------------------------------------
ok=0
for i in $(seq 1 12); do
  sleep 10
  active=$($SSHN "for u in $SERVICES; do systemctl is-active \$u; done | grep -c '^active$'")
  local_h=$($SSHN "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health")
  public_h=$(curl -s -o /dev/null -w '%{http_code}' https://openrent-api.bricbybric.ae/api/health)
  wa=$($SSHN "journalctl -u openrent-backend --since '-5 min' --no-pager | grep -c 'WHATSAPP_KAPSO_WORKER_STARTED provider=meta'")
  rq=$($SSHN "journalctl -u openrent-rq-worker --since '-5 min' --no-pager | grep -c 'WORKER_STARTED worker_index'")
  say "check $i: active=$active/4 local=$local_h public=$public_h whatsapp_meta=$wa rq_workers=$rq"
  if [ "$active" = "4" ] && [ "$local_h" = "200" ] && [ "$public_h" = "200" ] && [ "$wa" -ge 1 ] && [ "$rq" -ge "$WORKERS" ]; then ok=1; break; fi
done
[ "$ok" = "1" ] || rollback "post-switch checks failed"

say "crontab on new server: $($SSHN 'crontab -l | grep -c .') lines"
say "=== CUTOVER SUCCESS: production now runs on Contabo $NEW (Hetzner stopped + disabled, kept as fallback)"
