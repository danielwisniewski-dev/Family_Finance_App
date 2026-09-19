package com.familyfinance.app.ui;

import android.animation.Animator;
import android.animation.AnimatorListenerAdapter;
import android.animation.ValueAnimator;
import android.app.Activity;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.view.View;
import android.view.ViewGroup;
import android.view.animation.LinearInterpolator;

/** Brief, decorative celebrations. Overlay views never take input or accessibility focus. */
public final class CelebrationOverlay {
    private CelebrationOverlay() { }

    public static void show(Activity activity, boolean milestone) {
        if (activity == null || activity.isFinishing() || activity.isDestroyed()
                || !ValueAnimator.areAnimatorsEnabled()) return;
        View decor = activity.getWindow().getDecorView();
        if (!(decor instanceof ViewGroup)) return;
        ViewGroup host = (ViewGroup) decor;
        host.post(() -> {
            if (activity.isFinishing() || activity.isDestroyed() || !host.isAttachedToWindow()
                    || host.getWidth() == 0 || host.getHeight() == 0
                    || !ValueAnimator.areAnimatorsEnabled()) return;
            BurstView burst = new BurstView(activity, host, milestone);
            burst.layout(0, 0, host.getWidth(), host.getHeight());
            host.getOverlay().add(burst);
            burst.start();
        });
    }

    private static final class BurstView extends View {
        private static final int[] COLORS = {
                Color.rgb(38, 110, 80), Color.rgb(222, 164, 52),
                Color.rgb(222, 118, 91), Color.rgb(112, 159, 130)
        };
        private final ViewGroup host;
        private final boolean milestone;
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Path path = new Path();
        private final float density;
        private ValueAnimator animator;
        private float progress;
        private boolean finished;

        BurstView(Activity activity, ViewGroup host, boolean milestone) {
            super(activity);
            this.host = host;
            this.milestone = milestone;
            density = getResources().getDisplayMetrics().density;
            setClickable(false);
            setFocusable(false);
            setEnabled(false);
            setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        }

        void start() {
            animator = ValueAnimator.ofFloat(0f, 1f);
            animator.setDuration(milestone ? 1600L : 650L);
            animator.setInterpolator(new LinearInterpolator());
            animator.addUpdateListener(animation -> {
                progress = (float) animation.getAnimatedValue();
                invalidate();
            });
            animator.addListener(new AnimatorListenerAdapter() {
                @Override public void onAnimationEnd(Animator animation) { finish(); }
            });
            animator.start();
        }

        private void finish() {
            if (finished) return;
            finished = true;
            if (animator != null) {
                animator.removeAllUpdateListeners();
                animator.removeAllListeners();
                animator.cancel();
                animator = null;
            }
            host.getOverlay().remove(this);
        }

        @Override protected void onDetachedFromWindow() {
            finish();
            super.onDetachedFromWindow();
        }

        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            if (milestone) drawFireworks(canvas);
            else drawCheck(canvas);
        }

        private void drawCheck(Canvas canvas) {
            float cx = getWidth() * .5f;
            float cy = getHeight() * .28f;
            float appear = Math.min(1f, progress / .22f);
            float fade = Math.min(1f, (1f - progress) / .35f);
            float radius = (22f + 4f * appear) * density;
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(Color.rgb(219, 239, 215));
            paint.setAlpha((int) (235f * fade));
            canvas.drawCircle(cx, cy, radius, paint);
            paint.setColor(COLORS[0]);
            paint.setAlpha((int) (255f * fade));
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(3.5f * density);
            paint.setStrokeCap(Paint.Cap.ROUND);
            paint.setStrokeJoin(Paint.Join.ROUND);
            path.reset();
            path.moveTo(cx - 11f * density, cy);
            path.lineTo(cx - 3f * density, cy + 8f * density);
            path.lineTo(cx + 12f * density, cy - 9f * density);
            canvas.drawPath(path, paint);
            for (int i = 0; i < 8; i++) {
                double angle = Math.PI * 2d * i / 8d;
                float distance = (32f + 20f * progress) * density;
                float x = cx + (float) Math.cos(angle) * distance;
                float y = cy + (float) Math.sin(angle) * distance;
                paint.setColor(COLORS[i % COLORS.length]);
                paint.setAlpha((int) (220f * fade));
                float ray = (2f + 2f * appear) * density;
                paint.setStrokeWidth(1.7f * density);
                canvas.drawLine(x - ray, y, x + ray, y, paint);
                canvas.drawLine(x, y - ray, x, y + ray, paint);
            }
        }

        private void drawFireworks(Canvas canvas) {
            // Three gentle radial bursts with falling pieces; no flashing screen or sound.
            for (int burst = 0; burst < 3; burst++) {
                float t = Math.max(0f, Math.min(1f, (progress - burst * .08f) / .84f));
                if (t <= 0f || t >= 1f) continue;
                float cx = getWidth() * (burst == 0 ? .25f : burst == 1 ? .75f : .5f);
                float cy = getHeight() * (burst == 2 ? .33f : .24f);
                float fade = Math.min(1f, (1f - t) / .4f);
                float reach = Math.min(getWidth() * .28f, 125f * density);
                for (int i = 0; i < 22; i++) {
                    double angle = Math.PI * 2d * i / 22d + burst * .37d;
                    float speed = reach * (.62f + (i % 5) * .095f);
                    float vx = (float) Math.cos(angle) * speed;
                    float vy = (float) Math.sin(angle) * speed;
                    float x = cx + vx * t;
                    float y = cy + vy * t + 68f * density * t * t;
                    paint.setColor(COLORS[(i + burst) % COLORS.length]);
                    paint.setAlpha((int) (230f * fade));
                    if (i % 3 == 0) {
                        float trail = Math.max(0f, t - .075f);
                        paint.setStyle(Paint.Style.STROKE);
                        paint.setStrokeWidth(1.6f * density);
                        paint.setStrokeCap(Paint.Cap.ROUND);
                        path.reset();
                        path.moveTo(cx + vx * trail,
                                cy + vy * trail + 68f * density * trail * trail);
                        path.quadTo(cx + vx * (trail + t) / 2f,
                                cy + vy * (trail + t) / 2f + 68f * density * trail * t, x, y);
                        canvas.drawPath(path, paint);
                    }
                    paint.setStyle(Paint.Style.FILL);
                    canvas.save();
                    canvas.rotate(i * 23f + t * 180f, x, y);
                    canvas.drawRoundRect(x - 2f * density, y - 3.5f * density,
                            x + 2f * density, y + 3.5f * density, density, density, paint);
                    canvas.restore();
                }
            }
        }
    }
}
