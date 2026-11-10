package com.botagent;

import android.content.Context;

import org.json.JSONObject;

import java.io.File;

/**
 * 扩展包：用户自己提供的安装包 + 我们这边准备好的适配脚本。
 *
 * 原则：
 *   · App 不下载、不分发任何 QQ 客户端；用户把自己合法取得的包放进来，我们装进容器并运行。
 *   · NapCat 是开源的，许可证允许原样再分发（附全文 + 署名 + 非商业），所以我们内置。
 */
public class Extension {

    public static final String QQ_ID = "qq";

    /** NapCat 官方发布包（原样使用，不修改）。许可证见 assets/napcat/。 */
    public static final String NAPCAT_URL =
            "https://github.com/NapNeko/NapCatQQ/releases/download/v4.18.42/NapCat.Shell.zip";
    public static final String NAPCAT_SHA256 =
            "02e5ff0f79916c1e04c81c1b4590056406fb4293f1f1300c955e71fd08b2829d";
    public static final String NAPCAT_VER = "v4.18.42";

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

    /** 用户的安装包（.deb 等），没放就是 null。 */
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

    /** 写入适配脚本（幂等，每次执行前刷一遍）。 */
    public void writeScripts() {
        dir().mkdirs();
        write("install.sh", QQ_INSTALL);
        write("start.sh", QQ_START);
        write("stop.sh", QQ_STOP);
        write("status.sh", QQ_STATUS);
        write("napcat-install.sh", NAPCAT_INSTALL);
        write("napcat-start.sh", NAPCAT_START);
        write("napcat-onebot-fix.sh", NAPCAT_ONEBOT_FIX);
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

    private static final String CN_SOURCES =
            "if [ -f /etc/apt/sources.list ]; then\n"
            + "  cp /etc/apt/sources.list /etc/apt/sources.list.bak 2>/dev/null || true\n"
            + "  printf 'deb http://mirrors.aliyun.com/ubuntu-ports jammy main restricted "
            + "universe multiverse\\n"
            + "deb http://mirrors.aliyun.com/ubuntu-ports jammy-updates main restricted "
            + "universe multiverse\\n"
            + "deb http://mirrors.aliyun.com/ubuntu-ports jammy-security main restricted "
            + "universe multiverse\\n' > /etc/apt/sources.list\n"
            + "fi\n";

    // hostUnpackNote：QQ 的 deb 由宿主侧 python 解开（Android 硬链接受限，dpkg 会失败），
    // 这个脚本只负责装运行库、补依赖。
    static final String QQ_INSTALL = "set -e\n"
            + "export DEBIAN_FRONTEND=noninteractive\n"
            + "echo '== 换国内源 =='\n"
            + CN_SOURCES
            + "apt-get update -o Acquire::Retries=2 2>&1 | tail -2\n"
            + "echo '== 装 QQ 需要的运行库 =='\n"
            + "apt-get install -y --no-install-recommends xvfb libgtk-3-0 libnss3 "
            + "libasound2 libxss1 libgbm1 libxkbcommon0 fonts-noto-cjk "
            + "libxcb-image0 libxcb-keysyms1 libxcb-render-util0 2>&1 | tail -4\n"
            + "echo '== 装你提供的包 =='\n"
            + "dpkg -i /tmp/payload.deb 2>&1 | tail -15 || true\n"
            + "echo '== 补依赖 =='\n"
            + "apt-get install -fy 2>&1 | tail -4\n"
            + "echo '== 结果 =='\n"
            + "ls -d /opt/QQ 2>/dev/null && echo QQ_DIR_OK || echo QQ_DIR_MISSING\n";

    static final String QQ_START = "set -e\n"
            + "export DISPLAY=:99\n"
            + "pgrep Xvfb >/dev/null || (nohup Xvfb :99 -screen 0 1080x1920x24 "
            + ">/tmp/xvfb.log 2>&1 & sleep 3)\n"
            + "QBBIN=$(ls /opt/QQ/qq 2>/dev/null || ls /opt/QQ/bin/qq 2>/dev/null || echo '')\n"
            + "if [ -z \"$QBBIN\" ]; then echo 'QQ_NOT_FOUND 先装 QQ'; exit 2; fi\n"
            + "echo \"QQ: $QBBIN\"\n"
            + "nohup \"$QBBIN\" --no-sandbox >/tmp/qq.log 2>&1 &\n"
            + "sleep 10\n"
            + "echo '== qq 日志 =='\n"
            + "tail -8 /tmp/qq.log 2>/dev/null || true\n";

    static final String QQ_STOP = "pkill -f '/opt/QQ' 2>/dev/null || true\n"
            + "pkill Xvfb 2>/dev/null || true\n"
            + "echo stopped\n";

    static final String QQ_STATUS = "echo -n 'QQ 进程: '; pgrep -fc '/opt/QQ' 2>/dev/null || echo 0\n"
            + "echo -n 'Xvfb: '; pgrep -c Xvfb 2>/dev/null || echo 0\n"
            + "echo -n 'NapCat: '; pgrep -fc napcat 2>/dev/null || echo 0\n"
            + "(netstat -tln 2>/dev/null || ss -tln 2>/dev/null) | grep -E ':3001|:6099' "
            + "|| echo '端口还没起'\n";

        static final String NAPCAT_INSTALL = "set -e\n"
            + "export DEBIAN_FRONTEND=noninteractive\n"
            + "echo '== 换国内源 =='\n"
            + CN_SOURCES
            + "apt-get update -o Acquire::Retries=2 2>&1 | tail -2\n"
            + "echo '== 基础依赖（xvfb + jq）=='\n"
            + "apt-get install -y --no-install-recommends xvfb xauth jq curl ca-certificates 2>&1 | tail -3\n"
            + "QAPP=/opt/QQ/resources/app\n"
            + "test -d $QAPP || { echo 'QQ_NOT_FOUND 先把 QQ 安装包装进容器'; exit 1; }\n"
            + "echo '== 1/3 放 NapCat =='\n"
            + "rm -rf $QAPP/napcat\n"
            + "cp -a /opt/napcat $QAPP/napcat\n"
            + "ls $QAPP/napcat | head -5\n"
            + "echo '== 2/3 写加载器 =='\n"
            + "cat > $QAPP/loadNapCat.cjs <<'EOF'\n"
            + "const path = require('node:path');\n"
            + "const { pathToFileURL } = require('node:url');\n"
            + "if (process.argv.includes('--no-sandbox')) {\n"
            + "  import(pathToFileURL(path.join(__dirname, 'napcat/napcat.mjs')).href);\n"
            + "} else {\n"
            + "  const original = require('./package.napcat-original.json');\n"
            + "  require(path.resolve(__dirname, original.main));\n"
            + "  setTimeout(() => { global.launcher.installPathPkgJson.main = original.main; }, 0);\n"
            + "}\n"
            + "EOF\n"
            + "echo '== 3/3 改 QQ 入口 =='\n"
            + "if [ ! -f $QAPP/package.napcat-original.json ]; then cp -a $QAPP/package.json $QAPP/package.napcat-original.json; fi\n"
            + "jq '.main = \"./loadNapCat.cjs\"' $QAPP/package.napcat-original.json > $QAPP/package.json\n"
            + "grep -o '\"main\"[^,]*' $QAPP/package.json | head -1\n"
            + "echo NAPCAT_O\n";

    
    /** NapCat 登录后才生成 onebot11 配置，默认 websocketServers 为空；
     *  后台轮询补上 ws:3001（最多 15 分钟），否则用户装完永远连不上。 */
    static final String NAPCAT_ONEBOT_FIX = "set +e\n"
            + "set +e\n"
            + "CFG_DIR=/opt/QQ/resources/app/napcat/config\n"
            + "LOG=/tmp/onebot-fix.log\n"
            + "echo '[fix] wait for onebot11 config' >> $LOG\n"
            + "for i in $(seq 1 180); do\n"
            + "  cfg=$(ls $CFG_DIR/onebot11_*.json 2>/dev/null | head -1)\n"
            + "  if [ -n \"$cfg\" ]; then\n"
            + "    if grep -q '\"port\": *3001' \"$cfg\" 2>/dev/null; then\n"
            + "      echo '[fix] already has 3001' >> $LOG; exit 0\n"
            + "    fi\n"
            + "    printf '%s' '{\"network\":{\"httpServers\":[],\"httpSseServers\":[],\"httpClients\":[],\"websocketServers\":[{\"name\":\"ws\",\"enable\":true,\"host\":\"127.0.0.1\",\"port\":3001,\"messagePostFormat\":\"array\",\"reportSelfMessage\":false,\"token\":\"\",\"enableForcePushEvent\":true,\"debug\":false,\"heartInterval\":30000}],\"websocketClients\":[],\"plugins\":[]},\"musicSignUrl\":\"\",\"enableLocalFile2Url\":false,\"parseMultMsg\":false}' > /tmp/ob.json\n"
            + "    if [ -s /tmp/ob.json ]; then cp -f /tmp/ob.json \"$cfg\"; echo \"[fix] wrote ws:3001 to $cfg\" >> $LOG; exit 0; fi\n"
            + "  fi\n"
            + "  sleep 5\n"
            + "done\n"
            + "echo '[fix] timeout' >> $LOG\n";

    static final String NAPCAT_START = "set -e\n"
            + "export DISPLAY=:99\n"
            + "QAPP=/opt/QQ/resources/app\n"
            + "test -d $QAPP/napcat || { echo 'NAPCAT_NOT_INSTALLED 先点安装 NapCat'; exit 1; }\n"
            + "grep -q loadNapCat $QAPP/package.json || echo 'WARN 入口可能没改'\n"
            + "pgrep Xvfb >/dev/null || (nohup Xvfb :99 -screen 0 1080x1920x24 >/tmp/xvfb.log 2>&1 & sleep 3)\n"
            + "pgrep -f '/opt/QQ/qq' >/dev/null && { echo 'QQ 已在跑'; exit 0; }\n"
            + "cd /opt/QQ\n"
            + "nohup ./qq --no-sandbox > /tmp/napcat.log 2>&1 &\n"
            + "echo '== 等二维码（最多 60 秒）=='\n"
            + "for i in 1 2 3 4 5 6 7 8 9 10 11 12; do\n"
            + "  sleep 5\n"
            + "  grep -qa '二维码' /tmp/napcat.log 2>/dev/null && break\n"
            + "done\n"
            + "echo '== 日志（含二维码 URL / WebUI）=='\n"
            + "grep -aiE 'qrcode|二维码|WebUi|6099|3001|Token' /tmp/napcat.log 2>/dev/null | tail -12 || tail -20 /tmp/napcat.log\n"
            + "echo '== 端口 =='\n"
            + "(netstat -tln 2>/dev/null || ss -tln 2>/dev/null) | grep -E ':3001|:6099' || echo '端口还没起（多半还没扫码）'\n";

    static final String QQ_MANIFEST = "{\n"
            + "  \"id\": \"qq\",\n"
            + "  \"name\": \"QQ 协议端（用户自备安装包）\",\n"
            + "  \"version\": 1,\n"
            + "  \"note\": \"本扩展不包含任何 QQ 客户端。请自行从官方渠道获取 arm64 版安装包，"
            + "用「导入安装包」放进来，再点安装。\"\n"
            + "}\n";
}
