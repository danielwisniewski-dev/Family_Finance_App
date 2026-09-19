package com.familyfinance.app.state;

import org.junit.Test;
import java.time.LocalDate;
import static com.familyfinance.app.state.CelebrationPolicy.Reward.*;
import static org.junit.Assert.*;

public final class CelebrationPolicyTest {
    private final LocalDate today = LocalDate.of(2026, 9, 18);

    private String advance(int days, int best) {
        String yesterday = today.minusDays(1).toString();
        return CelebrationPolicy.streakMessage(today, yesterday, days, best,
                CheckInStreak.record(today, yesterday, days, best));
    }

    @Test public void failedOrPartialSavesNeverEarnRewardsEvenWithEmptyQueue() {
        assertEquals(NONE, CelebrationPolicy.reviewReward(false, true, true, true));
        assertEquals(NONE, CelebrationPolicy.reviewReward(true, true, true, false));
        assertEquals(NONE, CelebrationPolicy.reviewReward(false, false, false, false));
    }

    @Test public void completedReviewEarnsSmallRewardUntilRealQueueClear() {
        assertEquals(SMALL, CelebrationPolicy.reviewReward(true, true, false, true));
        assertEquals(QUEUE_CLEARED, CelebrationPolicy.reviewReward(true, true, true, true));
        assertEquals(SMALL, CelebrationPolicy.reviewReward(true, false, true, true));
    }

    @Test public void sevenFourteenThirtyAndLaterThirtyDayMilestonesAreRecognized() {
        for (int days : new int[]{7, 14, 30, 60, 90, 120}) {
            assertEquals(days + " days of checking in — nicely done!", advance(days - 1, 150));
        }
        assertNull(advance(20, 150));
        assertNull(advance(44, 150));
    }

    @Test public void establishedRecordMustBeBeatenRatherThanMatched() {
        assertNull(advance(11, 12));
        assertEquals("A new personal best: 13 days!", advance(12, 12));
        assertNull(advance(9, 0)); // Upgrade seeds an unstored record.
    }

    @Test public void sameDayRenderingDoesNotReplayMilestoneOrPersonalBest() {
        for (int days : new int[]{7, 13, 14, 30, 60}) {
            CheckInStreak current = CheckInStreak.record(today, today.toString(), days, days);
            assertNull(CelebrationPolicy.streakMessage(today, today.toString(), days, days, current));
        }
    }

    @Test public void firstCheckInAndResetAfterGapDoNotEarnRecordReward() {
        assertNull(CelebrationPolicy.streakMessage(today, "", 0, 0,
                CheckInStreak.record(today, "", 0, 0)));
        String oldDate = today.minusDays(3).toString();
        assertNull(CelebrationPolicy.streakMessage(today, oldDate, 6, 6,
                CheckInStreak.record(today, oldDate, 6, 6)));
    }

    @Test public void corruptFutureOrMissingHistoryCannotEarnReward() {
        CheckInStreak seven = CheckInStreak.record(today, today.minusDays(1).toString(), 6, 6);
        for (String date : new String[]{"bad date", "2026-02-30", "", null,
                today.plusDays(1).toString(), today.minusDays(2).toString()}) {
            assertNull(CelebrationPolicy.streakMessage(today, date, 6, 6, seven));
        }
        assertNull(CelebrationPolicy.streakMessage(today, today.minusDays(1).toString(), 3, 3, seven));
        assertNull(CelebrationPolicy.streakMessage(today, today.minusDays(1).toString(), -1, 6, seven));
    }

    @Test public void yearAndLeapDayBoundariesStillEarnMilestone() {
        for (LocalDate date : new LocalDate[]{LocalDate.of(2027, 1, 1), LocalDate.of(2028, 3, 1)}) {
            String previous = date.minusDays(1).toString();
            assertNotNull(CelebrationPolicy.streakMessage(date, previous, 6, 10,
                    CheckInStreak.record(date, previous, 6, 10)));
        }
    }
}
