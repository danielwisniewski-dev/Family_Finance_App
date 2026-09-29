package com.familyfinance.app.state;

/** Fences queued work and callbacks when the authenticated environment changes. */
public final class SessionGeneration {
    private volatile long generation;

    public long current() { return generation; }
    public boolean accepts(long captured) { return generation == captured; }
    public void advance() { generation++; }
}
