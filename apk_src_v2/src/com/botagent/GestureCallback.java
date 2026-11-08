package com.botagent;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** 手势结果回调（顶层类，不要用匿名内部类）。 */
public class GestureCallback extends AccessibilityService.GestureResultCallback {

    final CountDownLatch latch = new CountDownLatch(1);
    volatile boolean ok = false;

    @Override
    public void onCompleted(GestureDescription g) {
        ok = true;
        latch.countDown();
    }

    @Override
    public void onCancelled(GestureDescription g) {
        ok = false;
        latch.countDown();
    }

    boolean await(long ms) {
        try {
            return latch.await(ms, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            return false;
        }
    }
}
