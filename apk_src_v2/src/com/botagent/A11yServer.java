package com.botagent;

import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;

/** 无障碍服务的本地 HTTP 循环（独立类，避免匿名/内部类）。 */
public class A11yServer implements Runnable {

    private final A11yService svc;
    private ServerSocket socket;

    public A11yServer(A11yService svc) {
        this.svc = svc;
    }

    public void close() {
        try {
            if (socket != null) socket.close();
        } catch (Exception ignored) {
        }
        socket = null;
    }

    @Override
    public void run() {
        try {
            ServerSocket s = new ServerSocket(8081, 8, InetAddress.getByName("127.0.0.1"));
            socket = s;
            while (!s.isClosed()) {
                Socket c = null;
                try {
                    c = s.accept();
                    svc.handle(c);
                } catch (Exception ignored) {
                } finally {
                    if (c != null) try { c.close(); } catch (Exception ignored) { }
                }
            }
        } catch (Exception ignored) {
        }
    }
}
