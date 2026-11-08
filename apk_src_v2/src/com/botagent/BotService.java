package com.botagent;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/**
 * 前台服务：持有内置运行时的两个子进程，App 切后台也不会被杀。
 *
 * 启动顺序：解压（如需要）→ python 自检 → webui → qq_bot
 * 任何一步挂掉都会隔 5 秒重试，最多连续 5 次。
 */
public class BotService extends Service {

    public static final String CHANNEL_ID = "botagent_run";
    public static final int NOTI_ID = 1001;

    public static volatile boolean running = false;
    public static volatile String state = "未启动";
    private Thread worker;

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForegroundSafely();
        if (worker == null || !worker.isAlive()) {
            worker = new Thread(new Supervisor(this));
            worker.setDaemon(true);
            worker.start();
        }
        return START_STICKY;
    }

    private void startForegroundSafely() {
        try {
            if (Build.VERSION.SDK_INT >= 26) {
                NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
                NotificationChannel ch = new NotificationChannel(
                        CHANNEL_ID, "机器人运行状态", NotificationManager.IMPORTANCE_LOW);
                ch.setShowBadge(false);
                nm.createNotificationChannel(ch);
            }
            Intent i = new Intent(this, MainActivity.class);
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            PendingIntent pi = PendingIntent.getActivity(this, 0, i,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

            Notification.Builder b;
            if (Build.VERSION.SDK_INT >= 26) {
                b = new Notification.Builder(this, CHANNEL_ID);
            } else {
                b = new Notification.Builder(this);
            }
            b.setContentTitle("Botagent 正在运行")
                    .setContentText("点开可看控制台")
                    .setSmallIcon(android.R.drawable.stat_sys_download_done)
                    .setContentIntent(pi)
                    .setOngoing(true);
            startForeground(NOTI_ID, b.build());
        } catch (Throwable ignored) {
        }
    }

    @Override
    public void onDestroy() {
        running = false;
        state = "已停止";
        try {
            if (RuntimeManager.webuiProc != null) {
                RuntimeManager.webuiProc.destroy();
            }
            if (RuntimeManager.botProc != null) {
                RuntimeManager.botProc.destroy();
            }
        } catch (Exception ignored) {
        }
        super.onDestroy();
    }

    /** 状态文案同步到通知。 */
    void updateState(String s) {
        state = s;
        try {
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            Notification.Builder b;
            if (Build.VERSION.SDK_INT >= 26) {
                b = new Notification.Builder(this, CHANNEL_ID);
            } else {
                b = new Notification.Builder(this);
            }
            Intent i = new Intent(this, MainActivity.class);
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            PendingIntent pi = PendingIntent.getActivity(this, 0, i,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            b.setContentTitle("Botagent " + s)
                    .setContentText("点开可看控制台")
                    .setSmallIcon(android.R.drawable.stat_sys_download_done)
                    .setContentIntent(pi)
                    .setOngoing(true);
            nm.notify(NOTI_ID, b.build());
        } catch (Throwable ignored) {
        }
    }
}

/** 守护线程：看住两个子进程，挂了就重启。 */
class Supervisor implements Runnable {

    private final BotService svc;

    Supervisor(BotService s) {
        this.svc = s;
    }

    @Override
    public void run() {
        BotService.running = true;
        try {
            svc.updateState("启动中…");
            RuntimeManager mgr = new RuntimeManager(svc, false, true);
            boolean ok = mgr.prepare();
            if (!ok) {
                svc.updateState("启动失败");
                return;
            }
            svc.updateState("运行中");

            int fails = 0;
            while (fails < 5) {
                try {
                    Thread.sleep(8000);
                } catch (InterruptedException e) {
                    return;
                }
                boolean webOk = RuntimeManager.webuiProc != null
                        && RuntimeManager.isAlive(RuntimeManager.webuiProc);
                boolean botOk = RuntimeManager.botProc != null
                        && RuntimeManager.isAlive(RuntimeManager.botProc);
                if (!webOk || !botOk) {
                    fails++;
                    svc.updateState("重启中（" + fails + "/5）");
                    mgr.restartDead(webOk, botOk);
                } else {
                    fails = 0;
                }
            }
            svc.updateState("反复退出，已停");
        } catch (Throwable t) {
            svc.updateState("异常：" + t);
        }
    }
}
