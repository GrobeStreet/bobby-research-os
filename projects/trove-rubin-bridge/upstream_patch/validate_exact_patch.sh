#!/usr/bin/env bash
set +e

ROOT="${TROVE_RUBIN_BRIDGE_ROOT:?set TROVE_RUBIN_BRIDGE_ROOT}"
TROVE_ROOT="${TROVE_ROOT:?set TROVE_ROOT}"
UPSTREAM="$ROOT/upstream_patch"
OUT="$UPSTREAM/validation-output.txt"
STATUS="$UPSTREAM/validation-status.json"
PATCH="$UPSTREAM/trove-rubin-issue-23.patch"
TNLE_SHA="d877e0281c6c826d753b19442a7452dbaafb00c5"

: > "$OUT"
TROVE_SHA="$(git -C "$TROVE_ROOT" rev-parse HEAD)"
BRIDGE_SHA="$(git -C "$ROOT/../.." rev-parse HEAD 2>/dev/null || true)"

echo '=== environment ===' | tee -a "$OUT"
python --version 2>&1 | tee -a "$OUT"
echo "trove_commit=$TROVE_SHA" | tee -a "$OUT"
echo "bridge_commit=$BRIDGE_SHA" | tee -a "$OUT"
echo "tom_nonlocalizedevents_reproduction_pin=$TNLE_SHA" | tee -a "$OUT"

python - <<PY
from pathlib import Path
src = Path("$TROVE_ROOT/requirements.txt").read_text().splitlines()
pin = "tom-nonlocalizedevents @ git+https://github.com/TOMToolkit/tom_nonlocalizedevents.git@$TNLE_SHA"
Path('/tmp/trove-repro-requirements.txt').write_text(
    '\n'.join(pin if line.startswith('tom-nonlocalizedevents @') else line for line in src) + '\n'
)
PY

python -m pip install --upgrade pip wheel setuptools 2>&1 | tee -a "$OUT"
python -m pip install -r /tmp/trove-repro-requirements.txt pytest pytest-django 2>&1 | tee -a "$OUT"
INSTALL_STATUS=${PIPESTATUS[0]}

cat > "$TROVE_ROOT/trove_tom/settings_local.py" <<'EOF'
ALLOWED_HOST = 'localhost'
ATLAS_API_KEY = ''
DEBUG = True
FORCE_SCRIPT_NAME = ''
GCN_CLIENT_ID = ''
GCN_CLIENT_SECRET = ''
HOPSKOTCH_GROUP_ID = 'ci-test'
LASAIR_TOKEN = ''
POSTGRES_DB = ''
POSTGRES_HOST = ''
POSTGRES_PASSWORD = ''
POSTGRES_PORT = 5432
POSTGRES_USER = ''
POSTGRES_DB2 = ''
POSTGRES_HOST2 = ''
POSTGRES_PASSWORD2 = ''
POSTGRES_PORT2 = 5432
POSTGRES_USER2 = ''
SAVE_TEST_ALERTS = False
SCIMMA_AUTH_USERNAME = ''
SCIMMA_AUTH_PASSWORD = ''
SECRET_KEY = 'ci-test-secret-key-not-for-production'
NLE_LINKS = []
TARGET_LINKS = []
SLACK_TOKENS_GW = []
SLACK_TOKEN_EP = ''
SLACK_TOKEN_TNS = ''
TNS_API_KEY = ''
TREASUREMAP_API_KEY = ''
ZTF_INFO = {'email_server':'', 'email_password':'', 'email_address':'', 'user_address':'', 'user_password':''}
EOF

if [ "$INSTALL_STATUS" -eq 0 ]; then
  echo '=== patch upstream migrations exactly as TROVE CI ===' | tee -a "$OUT"
  python - <<'PY' 2>&1 | tee -a "$OUT"
import os, site
patches = [
    (('tom_targets','migrations','0025_auto_20250206_2017.py'), "from django.db import migrations\nclass Migration(migrations.Migration):\n    dependencies=[('tom_targets','0024_basetarget_permissions')]\n    operations=[]\n"),
    (('tom_nonlocalizedevents','migrations','0016_externalcoincidence_alter_eventsequence_options_and_more.py'), "from django.db import migrations\nclass Migration(migrations.Migration):\n    dependencies=[('tom_nonlocalizedevents','0015_eventsequence_and_more')]\n    operations=[]\n"),
    (('tom_nonlocalizedevents','migrations','0017_alter_eventsequence_external_coincidence_and_more.py'), "from django.db import migrations\nclass Migration(migrations.Migration):\n    dependencies=[('tom_nonlocalizedevents','0016_externalcoincidence_alter_eventsequence_options_and_more')]\n    operations=[]\n"),
]
for parts, content in patches:
    for sp in site.getsitepackages():
        path=os.path.join(sp,*parts)
        if os.path.exists(path):
            open(path,'w').write(content)
            print('patched', path)
            break
PY
fi

if [ "$INSTALL_STATUS" -eq 0 ]; then
  echo '=== build exact patch ===' | tee -a "$OUT"
  TROVE_RUBIN_BRIDGE_ROOT="$ROOT" TROVE_ROOT="$TROVE_ROOT" PYTHONPATH="$UPSTREAM" \
    python "$UPSTREAM/run_build.py" 2>&1 | tee -a "$OUT"
  BUILD_STATUS=${PIPESTATUS[0]}
else
  BUILD_STATUS=99
fi

if [ "$BUILD_STATUS" -eq 0 ]; then
  echo '=== frozen changed files ===' | tee -a "$OUT"
  cat "$UPSTREAM/changed-files.txt" | tee -a "$OUT"
  echo '=== reset to pristine TROVE and apply-check frozen patch ===' | tee -a "$OUT"
  git -C "$TROVE_ROOT" reset --hard HEAD 2>&1 | tee -a "$OUT"
  git -C "$TROVE_ROOT" clean -fd 2>&1 | tee -a "$OUT"
  git -C "$TROVE_ROOT" apply --check "$PATCH" 2>&1 | tee -a "$OUT"
  APPLY_CHECK_STATUS=${PIPESTATUS[0]}
else
  APPLY_CHECK_STATUS=99
fi

if [ "$APPLY_CHECK_STATUS" -eq 0 ]; then
  git -C "$TROVE_ROOT" apply "$PATCH" 2>&1 | tee -a "$OUT"
  APPLY_STATUS=${PIPESTATUS[0]}
else
  APPLY_STATUS=99
fi

if [ "$APPLY_STATUS" -eq 0 ]; then
  echo '=== django check with exact applied patch ===' | tee -a "$OUT"
  (cd "$TROVE_ROOT" && POSTGRES_DB='' SKIP_DUSTMAP=1 python manage.py check) 2>&1 | tee -a "$OUT"
  CHECK_STATUS=${PIPESTATUS[0]}
else
  CHECK_STATUS=99
fi

if [ "$APPLY_STATUS" -eq 0 ]; then
  echo '=== focused Rubin upstream tests ===' | tee -a "$OUT"
  (cd "$TROVE_ROOT" && POSTGRES_DB='' SKIP_DUSTMAP=1 python -m pytest tests/test_rubin_alertstream.py -q) 2>&1 | tee -a "$OUT"
  FOCUSED_STATUS=${PIPESTATUS[0]}
else
  FOCUSED_STATUS=99
fi

if [ "$APPLY_STATUS" -eq 0 ]; then
  echo '=== existing TROVE test suite ===' | tee -a "$OUT"
  (cd "$TROVE_ROOT" && POSTGRES_DB='' SKIP_DUSTMAP=1 python -m pytest tests/ -q) 2>&1 | tee -a "$OUT"
  FULL_STATUS=${PIPESTATUS[0]}
else
  FULL_STATUS=99
fi

if [ -f "$PATCH" ]; then
  PATCH_SHA="$(sha256sum "$PATCH" | awk '{print $1}')"
else
  PATCH_SHA=""
fi

cat > "$STATUS" <<EOF
{
  "install_status": $INSTALL_STATUS,
  "build_status": $BUILD_STATUS,
  "apply_check_status": $APPLY_CHECK_STATUS,
  "apply_status": $APPLY_STATUS,
  "django_check_status": $CHECK_STATUS,
  "focused_test_status": $FOCUSED_STATUS,
  "full_trove_test_status": $FULL_STATUS,
  "trove_commit": "$TROVE_SHA",
  "bridge_commit_before_results": "$BRIDGE_SHA",
  "tom_nonlocalizedevents_reproduction_pin": "$TNLE_SHA",
  "patch_sha256": "$PATCH_SHA"
}
EOF

if [ "$INSTALL_STATUS" -ne 0 ] || [ "$BUILD_STATUS" -ne 0 ] || [ "$APPLY_CHECK_STATUS" -ne 0 ] || [ "$APPLY_STATUS" -ne 0 ] || [ "$CHECK_STATUS" -ne 0 ] || [ "$FOCUSED_STATUS" -ne 0 ] || [ "$FULL_STATUS" -ne 0 ]; then
  exit 1
fi
