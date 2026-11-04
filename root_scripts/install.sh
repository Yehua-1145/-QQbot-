#!/system/bin/sh
# install new aibot sources (backup + chown back to termux uid)
/data/data/com.termux/files/usr/bin/python3 - <<'EOF'
import os, shutil, time
src = "/sdcard/Download/new_aibot"
dst = "/data/data/com.termux/files/home/aibot"
st = os.stat(os.path.join(dst, "agent.py"))
ts = time.strftime("%Y%m%d_%H%M%S")
for name in ("agent.py", "qq_bot.py", "webui.py", "console.py"):
    p = os.path.join(dst, name)
    s = os.path.join(src, name)
    if os.path.exists(p):
        shutil.copyfile(p, p + ".bak." + ts)
    shutil.copyfile(s, p)
    os.chmod(p, 0o640)
    try:
        os.chown(p, st.st_uid, st.st_gid)
    except Exception as e:
        print("chown failed:", e)
    # syntax check with the termux interpreter
    print("installed %-12s %6d bytes  owner=%d" % (name, os.path.getsize(p), st.st_uid))
pc = os.path.join(dst, "__pycache__")
if os.path.isdir(pc):
    shutil.rmtree(pc, ignore_errors=True)
    print("removed stale __pycache__")
print("done at", ts)
EOF
