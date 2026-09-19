package com.familyfinance.app.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.view.View;

/** Small, decorative artwork for the household welcome and completed review cards. */
public final class HouseholdIllustrationView extends View {
    private static final int DEEP_GREEN = Color.rgb(25, 77, 58);
    private static final int SAGE = Color.rgb(212, 230, 217);
    private static final int GOLD = Color.rgb(232, 185, 92);
    private static final int CREAM = Color.rgb(255, 245, 223);
    private static final int CORAL = Color.rgb(201, 113, 82);

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path = new Path();
    private final boolean celebration;

    public HouseholdIllustrationView(Context context, boolean celebration) {
        super(context);
        this.celebration = celebration;
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        setClickable(false);
        setFocusable(false);
        int defaultSize = Math.round(88 * getResources().getDisplayMetrics().density);
        setMinimumWidth(defaultSize);
        setMinimumHeight(defaultSize);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float width = getWidth() - getPaddingLeft() - getPaddingRight();
        float height = getHeight() - getPaddingTop() - getPaddingBottom();
        float scale = Math.min(width, height) / 100f;
        if (scale <= 0) {
            return;
        }
        int saved = canvas.save();
        canvas.translate(getPaddingLeft() + (width - 100 * scale) / 2f,
                getPaddingTop() + (height - 100 * scale) / 2f);
        canvas.scale(scale, scale);
        if (celebration) {
            drawCelebration(canvas);
        } else {
            drawHome(canvas);
        }
        canvas.restoreToCount(saved);
    }

    private void drawHome(Canvas canvas) {
        fill(SAGE);
        canvas.drawCircle(50, 50, 42, paint);
        fill(CREAM);
        canvas.drawRoundRect(29, 43, 74, 78, 4, 4, paint);
        fill(CORAL);
        canvas.drawRoundRect(62, 22, 69, 42, 2, 2, paint);
        fill(DEEP_GREEN);
        path.reset();
        path.moveTo(23, 46);
        path.lineTo(51.5f, 20);
        path.lineTo(80, 46);
        path.lineTo(73, 49);
        path.lineTo(51.5f, 30);
        path.lineTo(30, 49);
        path.close();
        canvas.drawPath(path, paint);
        fill(GOLD);
        canvas.drawRoundRect(45, 56, 59, 78, 4, 4, paint);
        fill(DEEP_GREEN);
        canvas.drawCircle(55, 67, 1.2f, paint);
        canvas.drawRoundRect(34, 51, 41, 59, 1.5f, 1.5f, paint);
        canvas.drawRoundRect(63, 51, 70, 59, 1.5f, 1.5f, paint);

        // A tiny growing plant keeps the motif about the household, not a money total.
        stroke(DEEP_GREEN, 2);
        canvas.drawLine(22, 73, 22, 56, paint);
        leaf(canvas, 22, 66, 12, 53, DEEP_GREEN);
        leaf(canvas, 22, 60, 32, 49, DEEP_GREEN);
        fill(CORAL);
        path.reset();
        path.moveTo(14, 71);
        path.lineTo(30, 71);
        path.lineTo(27, 81);
        path.lineTo(17, 81);
        path.close();
        canvas.drawPath(path, paint);

        fill(GOLD);
        canvas.drawRoundRect(68, 74, 86, 80, 3, 3, paint);
        canvas.drawRoundRect(71, 68, 86, 73, 2.5f, 2.5f, paint);
        sparkle(canvas, 82, 32, 5, GOLD);
        sparkle(canvas, 18, 34, 3, CREAM);
    }

    private void drawCelebration(Canvas canvas) {
        fill(SAGE);
        canvas.drawCircle(50, 50, 39, paint);
        // A warm outer ring gives the checkmark a little achievement-medal character.
        fill(GOLD);
        canvas.drawCircle(50, 49, 29, paint);
        fill(DEEP_GREEN);
        canvas.drawCircle(50, 49, 24, paint);
        stroke(CREAM, 5);
        path.reset();
        path.moveTo(38, 49);
        path.lineTo(47, 58);
        path.lineTo(63, 40);
        canvas.drawPath(path, paint);

        leaf(canvas, 26, 79, 14, 64, DEEP_GREEN);
        leaf(canvas, 28, 80, 35, 70, DEEP_GREEN);
        leaf(canvas, 73, 79, 86, 64, DEEP_GREEN);
        leaf(canvas, 72, 80, 65, 70, DEEP_GREEN);
        sparkle(canvas, 18, 27, 7, GOLD);
        sparkle(canvas, 82, 23, 6, GOLD);
        sparkle(canvas, 83, 51, 4, CREAM);
        fill(CORAL);
        canvas.drawCircle(30, 13, 2.5f, paint);
        canvas.drawCircle(91, 39, 2.5f, paint);
        stroke(CORAL, 3);
        canvas.drawLine(9, 47, 12, 51, paint);
        canvas.drawLine(62, 12, 65, 8, paint);
        stroke(GOLD, 3);
        canvas.drawLine(41, 87, 42, 91, paint);
        canvas.drawLine(63, 86, 68, 89, paint);
    }

    private void leaf(Canvas canvas, float baseX, float baseY, float tipX, float tipY,
            int color) {
        float midX = (baseX + tipX) / 2f;
        float midY = (baseY + tipY) / 2f;
        float bendX = (tipY - baseY) * 0.34f;
        float bendY = (baseX - tipX) * 0.34f;
        fill(color);
        path.reset();
        path.moveTo(baseX, baseY);
        path.quadTo(midX + bendX, midY + bendY, tipX, tipY);
        path.quadTo(midX - bendX, midY - bendY, baseX, baseY);
        path.close();
        canvas.drawPath(path, paint);
    }

    private void sparkle(Canvas canvas, float centerX, float centerY, float radius,
            int color) {
        fill(color);
        path.reset();
        path.moveTo(centerX, centerY - radius);
        path.lineTo(centerX + radius * 0.3f, centerY - radius * 0.3f);
        path.lineTo(centerX + radius, centerY);
        path.lineTo(centerX + radius * 0.3f, centerY + radius * 0.3f);
        path.lineTo(centerX, centerY + radius);
        path.lineTo(centerX - radius * 0.3f, centerY + radius * 0.3f);
        path.lineTo(centerX - radius, centerY);
        path.lineTo(centerX - radius * 0.3f, centerY - radius * 0.3f);
        path.close();
        canvas.drawPath(path, paint);
    }

    private void fill(int color) {
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(color);
    }

    private void stroke(int color, float width) {
        paint.setStyle(Paint.Style.STROKE);
        paint.setColor(color);
        paint.setStrokeWidth(width);
        paint.setStrokeCap(Paint.Cap.ROUND);
        paint.setStrokeJoin(Paint.Join.ROUND);
    }
}
