package com.botagent;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.widget.Toast;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.util.zip.GZIPInputStream;

/**
 * 内置 Python 运行时：解压 assets/runtime.tar.gz，用 proot 起 python。
 *
 * 目录结构（首次启动生成）：
 *   files/rt/usr/bin/python3          运行时
 *   files/aibot/*.py                  我们的程序
 *   files/config.json                 配置
 */
public class RuntimeManager implements Runnable {

    private final MainActivity act;      // 可能为 null（Service 场景）
    private final android.content.Context ctx;
    private final boolean force;
    private final boolean silent;        // true = 日志打到通知栏，不弹页面

    /** 实际使用的控制台端口（8080 被占就自动换）。 */
    public static volatile int port = 8080;

    public static volatile Process webuiProc;
    public static volatile Process botProc;

    public RuntimeManager(MainActivity a, boolean force) {
        this.act = a;
        this.ctx = a;
        this.force = force;
        this.silent = false;
    }

    public RuntimeManager(android.content.Context c, boolean force, boolean silent) {
        this.act = null;
        this.ctx = c;
        this.force = force;
        this.silent = silent;
    }

    private void log(String msg) {
        if (act != null) {
            log(msg);
        } else {
            android.util.Log.i("botagent", msg);
        }
    }

    static boolean isAlive(Process p) {
        if (p == null) {
            return false;
        }
        try {
            p.exitValue();
            return false;
        } catch (IllegalThreadStateException e) {
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    private void done(String msg) {
        if (act != null) {
            act.uiDone(msg);
            act.uiRefresh();
        } else {
            android.util.Log.i("botagent", "done: " + msg);
        }
    }

    /** 准备运行时 + 起两个进程；成功返回 true。 */
    public boolean prepare() {
        try {
            log("准备运行时…");
            File rt = new File(ctx.getFilesDir(), "rt");
            File py = new File(rt, "usr/bin/python3");
            if (!py.exists() || force) {
                log("首次启动：解压运行时（约 45 MB）");
                extractRuntime(rt);
                log("运行时解压完成");
            } else {
                log("运行时已存在");
            }
            File aibot = new File(ctx.getFilesDir(), "aibot");
            copyAibot(aibot);
            log("程序文件就绪");

            String out = runPython(rt, "-c", "print('PY_OK')", 60);
            log("python 自检: " + oneLine(out));
            if (!out.contains("PY_OK")) {
                done("python 起不来");
                return false;
            }

            port = pickPort(8080);
            log("控制台端口: " + port);
            startService(rt, aibot, "webui.py", 1);
            Thread.sleep(4000);
            startService(rt, aibot, "qq_bot.py", 2);
            done("已启动");
            return true;
        } catch (Throwable t) {
            log("出错: " + t);
            done("启动失败：" + t);
            return false;
        }
    }

    /** 只重启挂掉的进程。 */
    public void restartDead(boolean webAlive, boolean botAlive) {
        try {
            File rt = new File(ctx.getFilesDir(), "rt");
            File aibot = new File(ctx.getFilesDir(), "aibot");
            if (!webAlive) {
                log("webui 挂了，重启");
                startService(rt, aibot, "webui.py", 1);
            }
            if (!botAlive) {
                log("qq_bot 挂了，重启");
                startService(rt, aibot, "qq_bot.py", 2);
            }
        } catch (Throwable t) {
            log("重启失败: " + t);
        }
    }

    @Override
    public void run() {
        prepare();
    }


    /** 从 preferred 开始找一个能绑的端口。 */
    static int pickPort(int preferred) {
        for (int p = preferred; p < preferred + 12; p++) {
            java.net.ServerSocket ss = null;
            try {
                ss = new java.net.ServerSocket(p, 1, java.net.InetAddress.getByName("127.0.0.1"));
                return p;
            } catch (Exception ignored) {
            } finally {
                try {
                    if (ss != null) {
                        ss.close();
                    }
                } catch (Exception ignored) {
                }
            }
        }
        return preferred;
    }

    private static String oneLine(String s) {
        if (s == null) {
            return "";
        }
        s = s.replace("\n", " ").trim();
        return s.length() > 120 ? s.substring(0, 120) : s;
    }

    /** 解压 assets/runtime.zip 到 files/rt（系统 ZipInputStream，稳）。 */
    private void extractRuntime(File rt) throws Exception {
        rt.mkdirs();
        java.util.zip.ZipInputStream zis =
                new java.util.zip.ZipInputStream(
                        new java.io.BufferedInputStream(ctx.getAssets().open("runtime.zip"), 1 << 16));
        byte[] buf = new byte[1 << 16];
        int count = 0;
        long lastLog = 0;
        String rootPath = rt.getCanonicalPath();
        java.util.zip.ZipEntry e;
        while ((e = zis.getNextEntry()) != null) {
            String nm = e.getName();
            if (nm == null || nm.length() == 0 || nm.endsWith("/")) {
                continue;
            }
            File f = new File(rt, nm);
            if (!f.getCanonicalPath().startsWith(rootPath)) {
                continue;
            }
            f.getParentFile().mkdirs();
            FileOutputStream out = new FileOutputStream(f);
            int n;
            while ((n = zis.read(buf)) > 0) {
                out.write(buf, 0, n);
            }
            out.close();
            zis.closeEntry();

            // java.util.zip.ZipEntry 拿不到 unix 权限位，按路径判断
            String lower = nm.toLowerCase();
            if (lower.startsWith("usr/bin/") || lower.startsWith("usr/libexec/")
                    || lower.endsWith(".so") || lower.contains(".so.")) {
                f.setExecutable(true, false);
            }
            count++;
            long now = System.currentTimeMillis();
            if (now - lastLog > 1200) {
                lastLog = now;
                log("解压中… " + count + " 个文件");
            }
        }
        zis.close();
        log("解压完成，共 " + count + " 个文件");
        int links = restoreSymlinks(new File(rt, "usr"));
        log("恢复符号链接 " + links + " 个");

        // 符号链接：zip 里是普通文件，内容就是目标路径，这里补成软链
        // 不修软链：直接跑 lib/ 里的 python，用不到 usr/bin 下的软链
    }

    /** zip 不保留符号链接类型，按内容重建 usr/bin 下的软链。 */
    private void fixSymlinks(File bin, File rt) {
        String[] names = bin.list();
        if (names == null) {
            return;
        }
        int fixed = 0;
        for (String n : names) {
            File f = new File(bin, n);
            if (f.isDirectory()) {
                continue;
            }
            try {
                if (f.length() > 256) {
                    continue;
                }
                byte[] body = new byte[(int) f.length()];
                java.io.FileInputStream in = new java.io.FileInputStream(f);
                in.read(body);
                in.close();
                String target = new String(body, "UTF-8").trim();
                if (target.startsWith("/") || target.contains("/")
                        || target.startsWith("python") || target.startsWith("proot")) {
                    if (target.length() < 200 && !target.contains("\n")) {
                        Runtime.getRuntime().exec(new String[]{"ln", "-sf", target,
                                f.getAbsolutePath()}).waitFor();
                        fixed++;
                    }
                }
            } catch (Exception ignored) {
            }
        }
        if (fixed > 0) {
            log("修正软链 " + fixed + " 个");
        }
    }

    /** 把 assets/aibot/ 下的程序复制到 files/aibot（写死文件名，getAssets().list 不可靠）。 */
    private static final String[] AIBOT_FILES = {
            "agent.py", "config.py", "console.py", "prefetch.py", "qq_bot.py", "webui.py"
    };
    private static final String[] AIBOT_ASSETS = {"bili_avatar.png", "welcome.gif"};

    private void copyAibot(File aibot) throws Exception {
        aibot.mkdirs();
        File imgDir = new File(aibot, "assets");
        imgDir.mkdirs();
        int ok = 0;
        for (String n : AIBOT_FILES) {
            if (copyAsset("aibot/" + n, new File(aibot, n))) {
                ok++;
            }
        }
        for (String n : AIBOT_ASSETS) {
            copyAsset("aibot/assets/" + n, new File(imgDir, n));
        }
        log("程序文件: " + ok + "/" + AIBOT_FILES.length);
        if (ok == 0) {
            throw new RuntimeException("assets 里的程序文件读不到");
        }
    }

    private boolean copyAsset(String assetPath, File dest) {
        try {
            InputStream in = ctx.getAssets().open(assetPath);
            FileOutputStream out = new FileOutputStream(dest);
            byte[] b = new byte[1 << 16];
            int r;
            while ((r = in.read(b)) > 0) {
                out.write(b, 0, r);
            }
            in.close();
            out.close();
            return true;
        } catch (Exception e) {
            log("拷贝失败 " + assetPath + ": " + e);
            return false;
        }
    }


    /** zip 里软链被存成「内容是目标名的小文件」，这里还原成真正的符号链接。 */
    private int restoreSymlinks(File usr) {
        int n = 0;
        String[] dirs = {"lib", "bin", "libexec"};
        for (String d : dirs) {
            File dir = new File(usr, d);
            File[] files = dir.listFiles();
            if (files == null) {
                continue;
            }
            for (File f : files) {
                if (!f.isFile() || f.length() > 256) {
                    continue;
                }
                try {
                    byte[] b = new byte[(int) f.length()];
                    java.io.FileInputStream in = new java.io.FileInputStream(f);
                    in.read(b);
                    in.close();
                    String target = new String(b, "UTF-8").trim();
                    if (target.length() == 0 || target.contains("\n") || target.contains(" ")) {
                        continue;
                    }
                    // 目标必须是个真实文件（同目录或相对路径）
                    File t = new File(dir, target);
                    if (!t.exists()) {
                        continue;
                    }
                    if (!target.matches("[\\w./+\\-]+")) {
                        continue;
                    }
                    if (f.delete()) {
                        android.system.Os.symlink(target, f.getAbsolutePath());
                        n++;
                    }
                } catch (Exception ignored) {
                }
            }
        }
        return n;
    }

    /** 直接跑内置 python（不用 proot，靠 PYTHONHOME 找标准库）。 */
    private String runPython(File rt, String a1, String a2, int timeoutSec) throws Exception {
        java.util.List<String> cmd = new java.util.ArrayList<>();
        cmd.add(rt.getAbsolutePath() + "/usr/bin/python3");
        cmd.add(a1);
        if (a2 != null) {
            cmd.add(a2);
        }
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.redirectErrorStream(true);
        fillEnv(pb, rt);
        Process p = pb.start();
        StringBuilder sb = new StringBuilder();
        Thread reader = new Thread(new StreamPump(p.getInputStream(), sb));
        reader.start();
        try {
            p.waitFor();
        } catch (InterruptedException ignored) {
        }
        reader.join(2000);
        return sb.toString();
    }

    /** 内置运行时的环境变量。 */
    private void fillEnv(ProcessBuilder pb, File rt) {
        String lib = ctx.getApplicationInfo().nativeLibraryDir;
        String prefix = rt.getAbsolutePath() + "/usr";
        String home = ctx.getFilesDir().getAbsolutePath();
        pb.environment().put("LD_LIBRARY_PATH", prefix + "/lib");
        pb.environment().put("PYTHONHOME", prefix);
        pb.environment().put("PYTHONPATH", prefix + "/lib/python3.14:"
                + prefix + "/lib/python3.14/site-packages");
        pb.environment().put("BOTAGENT_HOME_ROOT", home);
        pb.environment().put("BOTAGENT_PREFIX", prefix);
        pb.environment().put("BOTAGENT_PORT", String.valueOf(port));
        pb.environment().put("HOME", home);
        pb.environment().put("TMPDIR", ctx.getCacheDir().getAbsolutePath());
        pb.environment().put("PATH", lib + ":" + prefix + "/bin:"
                + "/system/bin:/system/xbin");
    }

    private void startService(File rt, File aibot, String script, int which) throws Exception {
        String lib = ctx.getApplicationInfo().nativeLibraryDir;
        java.util.List<String> cmd = new java.util.ArrayList<>();
        cmd.add(lib + "/libpybin.so");
        cmd.add(aibot.getAbsolutePath() + "/" + script);
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.redirectErrorStream(true);
        pb.directory(aibot);
        fillEnv(pb, rt);
        Process p = pb.start();
        if (which == 1) {
            webuiProc = p;
        } else {
            botProc = p;
        }
        Thread t = new Thread(new LogPump(p, act, script));
        t.setDaemon(true);
        t.start();
    }
}

/** 让 InputStream 读到 StringBuilder（简易泵）。 */
class StreamPump implements Runnable {

    private final InputStream in;
    private final StringBuilder sb;

    StreamPump(InputStream in, StringBuilder sb) {
        this.in = in;
        this.sb = sb;
    }

    @Override
    public void run() {
        try {
            BufferedReader r = new BufferedReader(new InputStreamReader(in));
            String line;
            while ((line = r.readLine()) != null) {
                synchronized (sb) {
                    sb.append(line).append('\n');
                }
            }
        } catch (Exception ignored) {
        }
    }
}

/** 把子进程输出打到页面上。 */
class LogPump implements Runnable {

    private final Process proc;
    private final MainActivity act;
    private final String tag;

    LogPump(Process p, MainActivity a, String tag) {
        this.proc = p;
        this.act = a;
        this.tag = tag;
    }

    @Override
    public void run() {
        try {
            BufferedReader r = new BufferedReader(
                    new InputStreamReader(proc.getInputStream()));
            String line;
            while ((line = r.readLine()) != null) {
                android.util.Log.i("botagent", "[" + tag + "] " + line);
            }
        } catch (Exception ignored) {
        }
    }
}
