package com.familyfinance.app.state;

import org.junit.Test;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import static org.junit.Assert.*;

public final class SessionGenerationTest {
    @Test
    public void lateResponseFromAbandonedDemoCannotReplaceRestoredRealScreen() throws Exception {
        SessionGeneration scope = new SessionGeneration();
        long demo = scope.current();
        CountDownLatch response = new CountDownLatch(1);
        AtomicBoolean rendered = new AtomicBoolean();
        Thread delayed = new Thread(() -> {
            try {
                if (response.await(2, TimeUnit.SECONDS) && scope.accepts(demo)) rendered.set(true);
            } catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
        });
        delayed.start();
        scope.advance();
        long real = scope.current();
        response.countDown();
        delayed.join(2500);
        assertFalse(delayed.isAlive());
        assertFalse(rendered.get());
        assertTrue(scope.accepts(real));
        scope.advance(); // Reentry is fresh; even the preceding real screen can no longer render.
        assertFalse(scope.accepts(real));
        assertFalse(scope.accepts(demo));
    }
}
