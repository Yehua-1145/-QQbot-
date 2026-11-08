package com.botagent;

import android.content.Context;

import org.json.JSONObject;

import java.io.File;

/**
 * 扩展包：用户自己提供的安装包 + 我们这边准备好的适配脚本。
 *
 * 原则：App 不下载、不分发任何第三方软件；用户把自己合法取得的包放进来，
 * 我们负责装进容器、起起来、把状态和日志给他看。
 */
public class Extension {

    public static final String QQ_ID = "qq";

    public final String id;
    public final String name;
    public final String description;

    private final Context ctx;

    public Extension(Context c, String id, String name, String desc) {
        this.ctx = c;
        this.id = id;
        this.name = name;
        this.description = desc == null ? "" : desc;
    }

    public File dir() {
        return new File(new File(ctx.getFilesDir(), "ext"), id);
    }

    public File manifest() {
        return new File(dir(), "ext.json");
    }

    public boolean installed() {
        return new File(dir(), "installed.flag").exists();
    }

    public void markInstalled(boolean on) {
        try {
            File f = new File(dir(), "installed.flag");
            if (on) {
                dir().mkdirs();
                java.io.FileWriter w = new java.io.FileWriter(f);
                w.write(String.valueOf(System.currentTimeMillis()));
                w.close();
            } else {
                f.delete();
            }
        } catch (Exception ignored) {
        }
    }

    /** 用户的安装包（.deb / .tar.gz / .zip），没放就是 null。 */
    public File payload() {
        File[] fs = dir().listFiles();
        if (fs == null) {
            return null;
        }
        for (File f : fs) {
            String n = f.getName().toLowerCase();
            if (f.isFile() && (n.endsWith(".deb") || n.endsWith(".tar.gz") || n.endsWith(".zip"))) {
                return f;
            }
        }
        return null;
    }

    public JSONObject readManifest() {
        try {
            File m = manifest();
            if (!m.exists()) {
                return null;
            }
            byte[] b = new byte[(int) m.length()];
            java.io.FileInputStream in = new java.io.FileInputStream(m);
            in.read(b);
            in.close();
            return new JSONObject(new String(b, "UTF-8"));
        } catch (Exception e) {
            return null;
        }
    }

    /** 写入适配脚本（幂等，每次启动前都刷一遍，保证脚本是最新的）。 */
    public void writeScripts() {
        dir().mkdirs();
        write("install.sh", QQ_INSTALL);
        write("start.sh", QQ_START);
        write("stop.sh", QQ_STOP);
        write("status.sh", QQ_STATUS);
        if (!manifest().exists()) {
            write("ext.json", QQ_MANIFEST);
        }
    }

    private void write(String name, String body) {
        try {
            java.io.FileWriter w = new java.io.FileWriter(new File(dir(), name));
            w.write(body);
            w.close();
        } catch (Exception ignored) {
        }
    }

    /** QQ 适配：装依赖 + dpkg 装包 + 修依赖。 */
    static final String QQ_INSTALL = "set -e\n"
            + "export DEBIAN_FRONTEND=noninteractive\n"
            + "echo '== 更新索引 =='\n"
            + "apt-get update -o Acquire::Retries=2 2>&1 | tail -3\n"
            + "echo '== 装运行库（Xvfb + GTK + 截图工具）=='\n"
            + "apt-get install -y --no-install-recommends xvfb libgtk-3-0 libnss3 "
            + "libasound2 libxss1 libgbm1 libxkbcommon0 fonts-noto-cjk "
            + "x11-utils imagemagick 2>&1 | tail -5\n"
            + "echo '== 装用户提供的包 =='\n"
            + "dpkg -i /tmp/payload.deb 2>&1 | tail -20 || true\n"
            + "echo '== 修依赖 =='\n"
            + "apt-get install -fy 2>&1 | tail -5\n"
            + "echo '== 结果 =='\n"
            + "ls -d /opt/QQ 2>/dev/null && echo QQ_DIR_OK || echo QQ_DIR_MISSING\n";

    /** 起 QQ（无头 X + 关沙箱），并输出二维码截图路径。 */
    static final String QQ_START = "set -e\n"
            + "export DISPLAY=:99\n"
            + "pkill Xvfb 2>/dev/null || true\n"
            + "rm -f /tmp/.X99-lock 2>/dev/null || true\n"
            + "nohup Xvfb :99 -screen 0 1080x1920x24 >/tmp/xvfb.log 2>&1 &\n"
            + "sleep 3\n"
            + "QBBIN=$(ls /opt/QQ/qq 2>/dev/null || ls /opt/QQ/bin/qq 2>/dev/null || echo '')\n"
            + "if [ -z \"$QBBIN\" ]; then echo 'QQ_NOT_FOUND'; exit 2; fi\n"
            + "echo \"QQ 路径: $QBBIN\"\n"
            + "nohup \"$QBBIN\" --no-sandbox >/tmp/qq.log 2>&1 &\n"
            + "sleep 12\n"
            + "import -display :99 -window root /tmp/qr.png 2>/dev/null "
            + "&& echo 'QR_SAVED /tmp/qr.png' || echo 'QR_FAIL'\n"
            + "tail -5 /tmp/qq.log 2>/dev/null || true\n";

    static final String QQ_STOP = "pkill -f '/opt/QQ' 2>/dev/null || true\n"
            + "pkill Xvfb 2>/dev/null || true\n"
            + "echo stopped\n";

    static final String QQ_STATUS = "echo -n 'QQ 进程: '; pgrep -fc '/opt/QQ' 2>/dev/null || echo 0\n"
            + "echo -n 'Xvfb: '; pgrep -c Xvfb 2>/dev/null || echo 0\n"
            + "ls -l /tmp/qr.png 2>/dev/null || echo '还没二维码'\n";

    static final String QQ_MANIFEST = "{\n"
            + "  \"id\": \"qq\",\n"
            + "  \"name\": \"QQ 协议端（用户自备安装包）\",\n"
            + "  \"version\": 1,\n"
            + "  \"note\": \"本扩展不包含任何 QQ 客户端。请自行从官方渠道获取 arm64 版安装包，\"+\n"
            + "            \"用「导入安装包」放进来，再点安装。\"\n"
            + "}\n";
}
