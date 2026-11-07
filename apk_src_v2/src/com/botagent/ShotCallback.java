package com.botagent;

import android.accessibilityservice.AccessibilityService;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** 截图回调（独立类，避免匿名内部类）。 */
public class ShotCallback implements AccessibilityService.TakeScreenshotCallback {

    public volatile AccessibilityService.ScreenshotResult result;
    public final CountDownLatch latch = new CountDownLatch(1);

    @Override
    public void onSuccess(AccessibilityService.ScreenshotResult r) {
        result = r;
        latch.countDown();
    }

    @Override
    public void onFailure(int errorCode) {
        latch.countDown();
    }

    public boolean waitFor(long seconds) {
        try {
            return latch.await(seconds, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return false;
        }
    }
}
