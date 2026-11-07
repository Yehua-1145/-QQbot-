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

    private final MainActivity act;
    private final boolean force;

    public RuntimeManager(MainActivity a, boolean force) {
        this.act = a;
        this.force = force;
    }

    // 运行中标记
    public static volatile Process webuiProc;
    public static volatile Process botProc;

    @Override
    public void run() {
        try {
            act.uiLog("准备运行时…");
            File rt = new File(act.getFilesDir(), "rt");
            File py = new File(rt, "usr/bin/python3");
            if (!py.exists() || force) {
                act.uiLog("首次启动：解压运行时（约 45 MB）");
                extractRuntime(rt);
                act.uiLog("运行时解压完成");
            } else {
                act.uiLog("运行时已存在");
            }
            File aibot = new File(act.getFilesDir(), "aibot");
            copyAibot(aibot);
            act.uiLog("程序文件就绪");

            // 先测一下 python 能不能跑
            String out = runPython(rt, "-c", "print('PY_OK')", 40);
            act.uiLog("python 自检: " + oneLine(out));
            if (!out.contains("PY_OK")) {
                act.uiDone("运行时启动失败，看下面日志");
                return;
            }

            startService(rt, aibot, "webui.py", 1);
            Thread.sleep(4000);
            startService(rt, aibot, "qq_bot.py", 2);
            act.uiDone("已启动");
            act.uiRefresh();
        } catch (Throwable t) {
            act.uiLog("出错: " + t);
            act.uiDone("启动失败：" + t);
        }
    }

    private static String oneLine(String s) {
        if (s == null) {
            return "";
        }
        s = s.replace("\n", " ").trim();
        return s.length() > 120 ? s.substring(0, 120) : s;
    }

    /** 解压 assets/runtime.tar.gz 到 files/rt（tar.gz，纯 Java 解析）。 */
    private void extractRuntime(File rt) throws Exception {
        rt.mkdirs();
        InputStream raw = act.getAssets().open("runtime.tar.gz");
        GZIPInputStream gz = new GZIPInputStream(raw, 1 << 16);
        TarReader tar = new TarReader(gz);

        byte[] buf = new byte[1 << 16];
        TarReader.Entry e;
        int count = 0;
        long lastLog = 0;
        String pendingName = null;
        while ((e = tar.next()) != null) {
            // pax / GNU 扩展头：不是真文件，名字在它们的内容里
            if (e.type == 'x' || e.type == 'g' || e.type == 'K') {
                long left = e.size;
                while (left > 0) {
                    int n = tar.read(buf, 0, (int) Math.min(buf.length, left));
                    if (n <= 0) {
                        break;
                    }
                    left -= n;
                }
                continue;
            }
            if (e.type == 'L') {
                java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
                long left = e.size;
                while (left > 0) {
                    int n = tar.read(buf, 0, (int) Math.min(buf.length, left));
                    if (n <= 0) {
                        break;
                    }
                    bo.write(buf, 0, n);
                    left -= n;
                }
                pendingName = new String(bo.toByteArray(), "UTF-8");
                int z = pendingName.indexOf(0);
                if (z >= 0) {
                    pendingName = pendingName.substring(0, z);
                }
                pendingName = pendingName.trim();
                continue;
            }
            if (pendingName != null) {
                e.name = pendingName;
                pendingName = null;
            }
            // tar 里的名字可能是 "./usr/..." 或者空
            String nm = e.name == null ? "" : e.name;
            while (nm.startsWith("./")) {
                nm = nm.substring(2);
            }
            if (nm.length() == 0 || nm.equals(".")) {
                continue;
            }
            File f = new File(rt, nm);
            if (!f.getCanonicalPath().startsWith(rt.getCanonicalPath())) {
                continue;   // 防目录穿越
            }
            if (e.isDir()) {
                f.mkdirs();
                continue;
            }
            if (e.isLink()) {
                f.getParentFile().mkdirs();
                try {
                    Runtime.getRuntime().exec(new String[]{"ln", "-sf", e.link, f.getAbsolutePath()})
                            .waitFor();
                } catch (Exception ignored) {
                }
                continue;
            }
            f.getParentFile().mkdirs();
            FileOutputStream out = new FileOutputStream(f);
            long left = e.size;
            while (left > 0) {
                int n = tar.read(buf, 0, (int) Math.min(buf.length, left));
                if (n <= 0) {
                    break;
                }
                out.write(buf, 0, n);
                left -= n;
            }
            out.close();
            if ((e.mode & 0111) != 0) {
                f.setExecutable(true, false);
            }
            count++;
            long now = System.currentTimeMillis();
            if (now - lastLog > 1500) {
                lastLog = now;
                act.uiLog("解压中… " + count + " 个文件");
            }
        }
        act.uiLog("解压完成，共 " + count + " 个文件");
    }

    /** 把 assets/aibot/ 下的程序复制到 files/aibot。 */
    private void copyAibot(File aibot) throws Exception {
        aibot.mkdirs();
        String[] list = act.getAssets().list("aibot");
        if (list == null) {
            return;
        }
        for (String n : list) {
            if (n.endsWith("/")) {
                continue;
            }
            InputStream in = act.getAssets().open("aibot/" + n);
            FileOutputStream out = new FileOutputStream(new File(aibot, n));
            byte[] b = new byte[1 << 16];
            int r;
            while ((r = in.read(b)) > 0) {
                out.write(b, 0, r);
            }
            in.close();
            out.close();
        }
    }

    /** 在 proot 里跑 python（把我们的 usr 映射到 Termux 的硬编码前缀）。 */
    private String runPython(File rt, String a1, String a2, int timeoutSec) throws Exception {
        String home = new File(act.getFilesDir(), "aibot").getAbsolutePath();
        String prefix = rt.getAbsolutePath() + "/usr";
        String fakeRoot = rt.getAbsolutePath();
        java.util.List<String> cmd = new java.util.ArrayList<>();
        cmd.add(rt.getAbsolutePath() + "/usr/bin/proot");
        cmd.add("--link2symlink");
        cmd.add("-0");
        cmd.add("-r");
        cmd.add(fakeRoot);
        cmd.add("-b");
        cmd.add(prefix + ":/data/data/com.termux/files/usr");
        cmd.add("-b");
        cmd.add("/dev");
        cmd.add("-b");
        cmd.add("/proc");
        cmd.add("-b");
        cmd.add("/sys");
        cmd.add("-w");
        cmd.add(home);
        cmd.add("/data/data/com.termux/files/usr/bin/python3");
        cmd.add(a1);
        if (a2 != null) {
            cmd.add(a2);
        }

        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.redirectErrorStream(true);
        pb.environment().put("LD_LIBRARY_PATH", prefix + "/lib");
        pb.environment().put("HOME", home);
        pb.environment().put("TMPDIR", prefix + "/tmp");
        pb.environment().put("PROOT_TMP_DIR", prefix + "/tmp");
        pb.environment().put("PROOT_LOADER", prefix + "/libexec/proot/loader");
        pb.environment().put("PROOT_NO_SECCOMP", "1");
        Process p = pb.start();
        StringBuilder sb = new StringBuilder();
        BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream()));
        String line;
        long end = System.currentTimeMillis() + timeoutSec * 1000L;
        Thread reader = new Thread(new StreamPump(p.getInputStream(), sb));
        reader.start();
        try {
            p.waitFor();
        } catch (InterruptedException ignored) {
        }
        reader.join(2000);
        return sb.toString();
    }

    private void startService(File rt, File aibot, String script, int which) throws Exception {
        String home = aibot.getAbsolutePath();
        String prefix = rt.getAbsolutePath() + "/usr";
        java.util.List<String> cmd = new java.util.ArrayList<>();
        cmd.add(prefix + "/bin/proot");
        cmd.add("--link2symlink");
        cmd.add("-0");
        cmd.add("-r");
        cmd.add(rt.getAbsolutePath());
        cmd.add("-b");
        cmd.add(prefix + ":/data/data/com.termux/files/usr");
        cmd.add("-b");
        cmd.add("/dev");
        cmd.add("-b");
        cmd.add("/proc");
        cmd.add("-b");
        cmd.add("/sys");
        cmd.add("-w");
        cmd.add(home);
        cmd.add("/data/data/com.termux/files/usr/bin/python3");
        cmd.add(home + "/" + script);

        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.redirectErrorStream(true);
        pb.environment().put("LD_LIBRARY_PATH", prefix + "/lib");
        pb.environment().put("HOME", home);
        pb.environment().put("TMPDIR", prefix + "/tmp");
        pb.environment().put("PROOT_TMP_DIR", prefix + "/tmp");
        pb.environment().put("PROOT_LOADER", prefix + "/libexec/proot/loader");
        pb.environment().put("PROOT_NO_SECCOMP", "1");
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

/** 极简 tar 读取（只处理普通文件/目录/符号链接）。 */
class TarReader {

    private final InputStream in;
    private final byte[] hdr = new byte[512];

    TarReader(InputStream in) {
        this.in = in;
    }

    static class Entry {
        String name;
        long size;
        int mode;
        char type;
        String link;

        boolean isDir() {
            return type == '5' || name.endsWith("/");
        }

        boolean isLink() {
            return type == '2';
        }
    }

    Entry next() throws Exception {
        int got = readFully(hdr, 512);
        if (got <= 0) {
            return null;
        }
        // 连续两个全零块 = 结束
        boolean allZero = true;
        for (byte b : hdr) {
            if (b != 0) {
                allZero = false;
                break;
            }
        }
        if (allZero) {
            return null;
        }
        Entry e = new Entry();
        e.name = str(0, 100);
        e.mode = (int) oct(100, 8);
        e.size = oct(124, 12);
        e.type = (char) hdr[156];
        String pfx = str(345, 155);
        if (pfx.length() > 0) {
            e.name = pfx + "/" + e.name;
        }
        if (e.type == '2') {
            e.link = str(157, 100);
        }
        return e;
    }

    private String str(int off, int len) {
        int end = off;
        while (end < off + len && hdr[end] != 0) {
            end++;
        }
        return new String(hdr, off, end - off).trim();
    }

    private long oct(int off, int len) {
        String s = str(off, len).trim();
        if (s.length() == 0) {
            return 0;
        }
        try {
            return Long.parseLong(s, 8);
        } catch (Exception e) {
            return 0;
        }
    }

    private int readFully(byte[] b, int len) throws Exception {
        int got = 0;
        while (got < len) {
            int n = in.read(b, got, len - got);
            if (n <= 0) {
                break;
            }
            got += n;
        }
        return got;
    }

    int read(byte[] b, int off, int len) throws Exception {
        return in.read(b, off, len);
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
                act.uiLog("[" + tag + "] " + line);
            }
        } catch (Exception ignored) {
        }
    }
}
