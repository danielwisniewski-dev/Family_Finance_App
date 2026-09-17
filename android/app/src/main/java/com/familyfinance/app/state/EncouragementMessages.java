package com.familyfinance.app.state;

import java.time.LocalDate;

/** Original encouragement, rotated once per local calendar day. */
public final class EncouragementMessages {
    private static final String[] MESSAGES = {
            "Small steps count. Today's check-in is one of them.",
            "Give every dollar a purpose that matters to you.",
            "You don't need a perfect month to make a thoughtful choice today.",
            "A few minutes of attention today can bring more clarity tomorrow.",
            "Build the habit first. Let the streak follow.",
            "Your goals deserve a little room in today's plan.",
            "Progress can be quiet: a checked balance, a reviewed bill, a clear plan.",
            "A pause before a purchase gives your priorities a voice.",
            "Make the next helpful choice small enough to do today.",
            "Consistency grows one ordinary day at a time.",
            "A budget is a plan you can learn from and adjust.",
            "Rest, movement, and a money check-in: small ways to care for tomorrow.",
            "You're practicing attention, and that is a skill worth building.",
            "A fresh start is available whenever you show up again.",
            "Celebrate the effort you can control today.",
            "A shared goal starts with an honest conversation.",
            "Future you can appreciate the care you're taking today.",
            "Leave room in your plan for what makes life meaningful.",
            "One reviewed transaction is one less unknown.",
            "Discipline can be gentle: choose a useful step and repeat it.",
            "You can be proud of showing up, even when the numbers feel hard.",
            "Turn a big goal into one small action for today.",
            "Healthy habits grow better with patience than with punishment.",
            "The best plan is one you can return to on a busy day.",
            "Checking in is a chance to notice, learn, and choose.",
            "A thoughtful no can make room for a meaningful yes.",
            "Your pace can be steady without being fast.",
            "Saving starts with making room, even a little, when you can.",
            "Plans change. Your next step can change with them.",
            "Teamwork is listening, planning, and taking the next step together.",
            "A missed day doesn't erase what you've learned. Welcome back.",
            "Give yourself credit for the habits you're practicing.",
            "Before you spend, give your goal a moment of attention.",
            "Small routines can make big decisions feel more manageable.",
            "Let your budget reflect your priorities, not someone else's pace.",
            "You don't have to solve everything during one check-in.",
            "A short walk, a deep breath, a clear plan: simple things can help.",
            "Make today's goal progress you can repeat tomorrow.",
            "Every honest look at your plan is a chance to learn.",
            "Keep showing up for the life you're working toward."
    };

    private EncouragementMessages() { }

    public static String forDate(LocalDate date) {
        return MESSAGES[Math.floorMod(date.toEpochDay(), MESSAGES.length)];
    }
}
