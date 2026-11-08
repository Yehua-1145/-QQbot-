package com.botagent;

import android.content.Context;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 本地容器：在 App 私有目录里放一个 Ubuntu rootfs，用自带的 proot 跑起来。
 *
 * 用途：给需要 Linux 环境的组件提供沙箱（比如以后要装的东西）。
 * 原则：容器本身只是环境，装什么由使用者决定；App 不代替任何人分发软件。
 */
public class Container {

    /** 官方地址（Ubuntu base，公开镜像，可自由取得）。 */
    public static final String DEFAULT_URL =
            "https://cdimage.ubuntu.com/ubuntu-base/releases/22.04/release/"
                    + "ubuntu-base-22.04.5-base-arm64.tar.gz";

    private final Context ctx;

    public Container(Context c) {
        this.ctx = c;
    }

    public File dir() {
        return new File(ctx.getFilesDir(), "ubuntu");
    }

    public boolean ready() {
        return new File(dir(), "bin/sh").exists() && new File(dir(), "lib").exists();
    }

    /** 容器占用（字节）。 */
    public long totalBytes() {
        return du(dir());
    }

    private long du(File f) {
        if (f == null || !f.exists()) {
            return 0;
        }
        if (f.isFile()) {
            return f.length();
        }
        long n = 0;
        File[] kids = f.listFiles();
        if (kids != null) {
            for (File k : kids) {
                n += du(k);
            }
        }
        return n;
    }

    /** 建容器：下载 → 解压 → 写 DNS。返回空字符串表示成功。 */
    public String create(MainActivity ui) {
        try {
            File target = dir();
            if (ready()) {
                return "容器已存在";
            }
            File tgz = new File(ctx.getCacheDir(), "rootfs.tar.gz");
            if (!tgz.exists() || tgz.length() < 5 * 1024 * 1024) {
                if (ui != null) {
                    ui.uiLog("下载 Ubuntu rootfs（约 26 MB）…");
                }
                String err = download(DEFAULT_URL, tgz, ui);
                if (err != null) {
                    return err;
                }
            }
            if (ui != null) {
                ui.uiLog("下载完成 " + (tgz.length() / 1048576) + " MB，开始解压");
            }

            target.mkdirs();
            String out = tarExtract(tgz, target, ui);
            if (out == null) {
                return "解压失败";
            }
            // DNS
            try {
                java.io.FileWriter w = new java.io.FileWriter(new File(target, "etc/resolv.conf"));
                w.write("nameserver 223.5.5.5\nnameserver 8.8.8.8\n");
                w.close();
            } catch (Exception ignored) {
            }
            tgz.delete();
            if (!ready()) {
                return "解压后结构不完整";
            }
            if (ui != null) {
                ui.uiLog("容器就绪");
            }
            return "";
        } catch (Throwable t) {
            return "建容器失败：" + t;
        }
    }

    private String download(String url, File dst, MainActivity ui) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(20000);
            c.setReadTimeout(60000);
            c.setInstanceFollowRedirects(true);
            c.setRequestProperty("User-Agent", "Botagent");
            int code = c.getResponseCode();
            if (code != 200) {
                return "下载失败 HTTP " + code;
            }
            long total = c.getContentLengthLong();
            InputStream in = c.getInputStream();
            FileOutputStream out = new FileOutputStream(dst);
            byte[] b = new byte[1 << 16];
            long got = 0;
            long last = 0;
            int n;
            while ((n = in.read(b)) > 0) {
                out.write(b, 0, n);
                got += n;
                long now = System.currentTimeMillis();
                if (ui != null && now - last > 1500) {
                    last = now;
                    ui.uiLog("下载 " + (got / 1048576) + " / "
                            + (total > 0 ? (total / 1048576) + " MB" : "?"));
                }
            }
            in.close();
            out.close();
            return null;
        } catch (Exception e) {
            return "下载失败：" + e;
        } finally {
            if (c != null) {
                c.disconnect();
            }
        }
    }

    /** 用系统 tar 解压（toybox tar，稳）。 */
    private String tarExtract(File tgz, File dst, MainActivity ui) {
        try {
            ProcessBuilder pb = new ProcessBuilder(
                    "/system/bin/tar", "-xzf", tgz.getAbsolutePath(),
                    "-C", dst.getAbsolutePath());
            pb.redirectErrorStream(true);
            Process p = pb.start();
            StringBuilder sb = new StringBuilder();
            InputStream in = p.getInputStream();
            byte[] b = new byte[8192];
            int n;
            while ((n = in.read(b)) > 0) {
                sb.append(new String(b, 0, n));
            }
            int rc = p.waitFor();
            if (rc != 0 && !ready()) {
                if (ui != null) {
                    ui.uiLog("tar 返回 " + rc + "：" + oneLine(sb.toString()));
                }
                return null;
            }
            return sb.toString();
        } catch (Exception e) {
            return null;
        }
    }

    private static String oneLine(String s) {
        String t = s.replace("\n", " ").trim();
        return t.length() > 160 ? t.substring(0, 160) : t;
    }

    /** proot 启动参数（容器用）。 */
    private java.util.List<String> prootCmd() {
        File rt = new File(ctx.getFilesDir(), "rt");
        java.util.List<String> cmd = new java.util.ArrayList<>();
        cmd.add(rt.getAbsolutePath() + "/usr/bin/proot");
        cmd.add("-r");
        cmd.add(dir().getAbsolutePath());
        cmd.add("-w");
        cmd.add("/");
        cmd.add("-0");
        cmd.add("-b");
        cmd.add("/dev");
        cmd.add("-b");
        cmd.add("/proc");
        cmd.add("-b");
        cmd.add("/sys");
        return cmd;
    }

    private void prootEnv(ProcessBuilder pb) {
        File rt = new File(ctx.getFilesDir(), "rt");
        String prefix = rt.getAbsolutePath() + "/usr";
        pb.environment().put("PROOT_TMP_DIR", ctx.getCacheDir().getAbsolutePath());
        pb.environment().put("PROOT_NO_SECCOMP", "1");
        pb.environment().put("PROOT_LOADER", prefix + "/libexec/proot/loader");
        pb.environment().put("LD_LIBRARY_PATH", prefix + "/lib");
        pb.environment().put("HOME", "/root");
        pb.environment().put("PATH", "/usr/sbin:/usr/bin:/sbin:/bin");
        pb.environment().put("TERM", "xterm");
    }

    /** 把 App 外部目录里的文件拷进容器，返回容器内路径。 */
    public String importFile(java.io.InputStream in, String name, MainActivity ui) {
        try {
            File tmp = new File(dir(), "tmp");
            tmp.mkdirs();
            File dst = new File(tmp, name);
            FileOutputStream out = new FileOutputStream(dst);
            byte[] b = new byte[1 << 16];
            int n;
            long got = 0;
            while ((n = in.read(b)) > 0) {
                out.write(b, 0, n);
                got += n;
            }
            in.close();
            out.close();
            if (ui != null) {
                ui.uiLog("已导入 " + name + "（" + (got / 1048576) + " MB）");
            }
            return "/tmp/" + name;
        } catch (Exception e) {
            if (ui != null) {
                ui.uiLog("导入失败：" + e);
            }
            return null;
        }
    }

    /** 容器里安装一个 deb（dpkg，失败再用 apt 修依赖）。 */
    public String installDeb(String guestPath, MainActivity ui) {
        String out = run(new String[]{"/bin/sh", "-c",
                "dpkg -i --force-depends " + guestPath + " 2>&1 | tail -20"}, 600, ui);
        return out;
    }

    /** 在容器里跑一条命令，返回输出。 */
    public String run(String[] argv, int timeoutSec, MainActivity ui) {
        try {
            java.util.List<String> cmd = prootCmd();
            cmd.add("/usr/bin/env");
            cmd.add("-i");
            cmd.add("PATH=/usr/sbin:/usr/bin:/sbin:/bin");
            cmd.add("HOME=/root");
            cmd.add("TERM=xterm");
            cmd.add("LC_ALL=C.UTF-8");
            for (String a : argv) {
                cmd.add(a);
            }
            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.redirectErrorStream(true);
            prootEnv(pb);
            Process p = pb.start();
            StringBuilder sb = new StringBuilder();
            InputStream in = p.getInputStream();
            byte[] b = new byte[8192];
            long deadline = System.currentTimeMillis() + timeoutSec * 1000L;
            int n;
            while ((n = in.read(b)) > 0) {
                sb.append(new String(b, 0, n));
                if (ui != null) {
                    String chunk = new String(b, 0, n);
                    for (String line : chunk.split("\n")) {
                        if (line.trim().length() > 0) {
                            ui.uiLog("[容器] " + line);
                        }
                    }
                }
                if (System.currentTimeMillis() > deadline) {
                    p.destroy();
                    sb.append("\n(超时)");
                    break;
                }
            }
            p.waitFor();
            return sb.toString();
        } catch (Exception e) {
            return "运行失败：" + e;
        }
    }
}
